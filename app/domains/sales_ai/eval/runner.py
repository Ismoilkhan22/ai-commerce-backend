"""Baholash yugurishi (16 §7, M06 §9): arq vazifasi — outbox event'lari zanjiri, bitta event = bitta holat.

```
POST /platform/ai-eval/runs ──▶ eval_runs QUEUED + event [sales_ai.eval.step]
   sales_ai.eval_runner (worker, tranzaksiyasiz):
     1. qisqa tranzaksiya: yugurish qulfi → RUNNING; xarajat chegarasi → BUDGET_EXCEEDED; holat yo'q →
        yakun (metrikalar, PASSED/FAILED)
     2. tranzaksiyasiz: haqiqiy agent loop (quruq rejim: yozuvchi tool'lar hech narsa yozmaydi) — nishon shop
        katalogi, tanlangan provayder/model; deterministik ball; ixtiyoriy judge
     3. qisqa tranzaksiya: ai_usage (shop_id'siz, EVAL / EVAL_JUDGE), natija (run_id+case_key unikal),
        hisoblagichlar, signal [sales_ai.eval.run.changed] (faqat ID va sonlar) + keyingi [sales_ai.eval.step]
```

Bitta holat arq vazifasi muddatiga (30 s) sig'adi: agent ≤ 20 s (TURN_BUDGET_S), judge — qolgan vaqtda.
Xarajat chegarasi har holatdan OLDIN tekshiriladi (bitta holat chegarani biroz oshirishi mumkin).
"""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.agent import AgentLoop, LoopResult, detect_locale, load_profile, precheck
from app.domains.sales_ai.common import DEFAULT_HANDOFF_RULES, TOOLS
from app.domains.sales_ai.eval.judge import Judge, JudgeError, JudgeVerdict
from app.domains.sales_ai.eval.scoring import CaseRun, Expectations, Score, score_case
from app.domains.sales_ai.models.orm import AgentSettings, EvalCase, EvalResult, EvalRun
from app.domains.sales_ai.prompts import HistoryItem, ShopProfile, history_messages, system_blocks
from app.domains.sales_ai.tools import ToolBroker, ToolContext
from app.platform.llm.port import LlmResponse
from app.platform.llm.pricing import ModelPrice
from app.platform.llm.redaction import MemoryPiiStore, redact
from app.platform.llm.router import LlmRouter
from app.platform.llm.usage import record_usage
from app.shared.clock import utcnow
from app.shared.db.ids import uuid7
from app.shared.db.session import Database
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

STEP_EVENT = "sales_ai.eval.step"
CHANGED_EVENT = "sales_ai.eval.run.changed"
AGGREGATE = "sales_ai.eval_run"
EVAL_DEMO_SHOP_SLUG = "techpc"  # dev seed'dagi PC qismlari katalogi (RTX 4060, Ryzen 5 7600, B650M …)
CASE_BUDGET_S = 27.0
MIN_JUDGE_S = 2.0
TERMINAL = frozenset({"PASSED", "FAILED", "ERROR", "BUDGET_EXCEEDED", "CANCELLED"})

RouterFactory = Callable[[str, Mapping[str, Sequence[str]] | None], LlmRouter]


@dataclass(frozen=True)
class EvalEngine:
    """Composition root (main.py) beradi: provayder bo'yicha router, tool broker, reliz SHA'si."""

    routers: RouterFactory
    brokers: Callable[[Database], ToolBroker]
    git_sha: str
    gemini_free: bool = True

    def router(self, provider: str, model: str | None, alias: str = "seller") -> LlmRouter:
        return self.routers(provider, {alias: (model,)} if model else None)


@dataclass
class CaseInput:
    case_id: UUID
    case_key: str
    ordinal: int
    category: str
    language: str
    message: str
    history: list[dict[str, Any]]
    expectations: Expectations


@dataclass
class CaseExecution:
    score: Score
    loop: LoopResult
    reply: str | None
    latency_ms: int
    judge: JudgeVerdict | None = None
    judge_error: str | None = None
    judge_responses: list[LlmResponse] = field(default_factory=list)


def _actor() -> ActorContext:
    return ActorContext.system(None)


async def execute_case(
    router: LlmRouter,
    broker: ToolBroker,
    judge_router: LlmRouter | None,
    case: CaseInput,
    profile: ShopProfile,
    shop_id: UUID,
    *,
    budget_s: float = CASE_BUDGET_S,
) -> CaseExecution:
    """Haqiqiy agent loop (sinov oynasi bilan bir xil: prompt, tool'lar, validator, AUTO tekshiruvi), lekin
    hech narsa saqlanmaydi va xaridorga hech narsa ketmaydi. Matn provayderga faqat redact holatida."""
    started = time.monotonic()
    store = MemoryPiiStore()
    items = [HistoryItem(h["role"], await redact(store, str(h["text"]))) for h in case.history]
    items.append(HistoryItem("customer", await redact(store, case.message)))
    reason = precheck(case.message, DEFAULT_HANDOFF_RULES)
    if reason is not None:
        loop = LoopResult(handoff=reason)
    else:
        loop = await AgentLoop(router, broker).run(
            system_blocks(profile),
            history_messages(items),
            ToolContext(
                shop_id=shop_id,
                conversation_id=None,  # quruq: lead/taklif/buyurtma yaratilmaydi
                customer_ref=None,
                locale=detect_locale(case.message, None),
                allowed=frozenset(TOOLS),
                memory_pii=store,
            ),
            check="closed",  # AUTO sharoiti: tekshirib bo'lmasa — operatorga
        )
    provider_texts = [i.text for i in items] + [o.content for o in loop.outcomes]
    score = score_case(
        case.expectations,
        CaseRun(
            language=case.language,
            reply=loop.reply,
            handoff=loop.handoff,
            error_code=loop.error_code,
            outcomes=loop.outcomes,
            validator_codes=loop.validator_codes,
            provider_texts=provider_texts,
        ),
    )
    execution = CaseExecution(score=score, loop=loop, reply=loop.reply, latency_ms=0)
    remaining = budget_s - (time.monotonic() - started)
    if judge_router is not None and loop.reply is not None and not score.zero_tolerance_codes:
        if remaining < MIN_JUDGE_S:
            execution.judge_error = "JUDGE_SKIPPED_TIMEOUT"
        else:
            try:
                execution.judge = await Judge(judge_router).grade(
                    message=items[-1].text,
                    reply=loop.reply,
                    language=case.language,
                    timeout_s=min(8.0, remaining),
                )
                execution.judge_responses.append(execution.judge.response)
            except JudgeError as exc:
                execution.judge_error = exc.code
                if exc.response is not None:
                    execution.judge_responses.append(exc.response)
    execution.latency_ms = int((time.monotonic() - started) * 1000)
    return execution


def _transcript(execution: CaseExecution) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "seq": seq,
            "tool": o.name,
            "decision": o.decision,
            "input": o.args_redacted,
            "output": o.summary or None,
            "error_code": o.error_code,
            "latency_ms": o.latency_ms,
        }
        for seq, o in enumerate(execution.loop.outcomes, start=1)
    ]
    if execution.loop.validator_codes:
        steps.append(
            {"validator_codes": execution.loop.validator_codes, "rewrites": execution.loop.rewrite_count}
        )
    return steps


# ------------------------------------------------------------------ metrikalar
def _pct(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def percentile(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))]  # nearest-rank


def _group(results: Sequence[EvalResult], key: Callable[[EvalResult], str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in sorted({key(r) for r in results}):
        rows = [r for r in results if key(r) == name]
        judged = [float(r.judge_score) for r in rows if r.judge_score is not None]
        passed = sum(1 for r in rows if r.passed)
        out[name] = {
            "cases": len(rows),
            "passed": passed,
            "pass_rate": _pct(passed, len(rows)),
            "avg_judge": round(sum(judged) / len(judged), 2) if judged else None,
        }
    return out


def aggregate(results: Sequence[EvalResult], expectations: Mapping[str, Expectations]) -> dict[str, Any]:
    """Yugurish metrikalari (DBML `eval_runs.metrics`): o'tish ulushi, nol toqat, kategoriya/til bo'yicha,
    tool tanlash va handoff aniqligi, validator, judge, latency, xarajat."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    tool_cases = [
        r for r in results if (e := expectations.get(r.case_key)) and (e.required_tools or e.any_tools)
    ]
    tool_ok = sum(
        1
        for r in tool_cases
        if not any(c.startswith(("MISSING_TOOL", "NO_EXPECTED_TOOL")) for c in r.failure_codes)
    )
    handoff_cases = [r for r in results if (e := expectations.get(r.case_key)) and e.handoff != "ANY"]
    handoff_ok = sum(1 for r in handoff_cases if not any(c.startswith("HANDOFF_") for c in r.failure_codes))
    judged = [r for r in results if r.judge]
    criteria: dict[str, float] = {}
    for name in ("helpfulness", "language", "tone"):
        values = [
            float(r.judge[name]) for r in judged if r.judge and isinstance(r.judge.get(name), int | float)
        ]
        if values:
            criteria[name] = round(sum(values) / len(values), 2)
    scores = [float(r.judge_score) for r in results if r.judge_score is not None]
    latencies = [r.latency_ms for r in results]
    agent_cost = sum(r.cost_micros for r in results)
    judge_cost = sum(r.judge_cost_micros for r in results)
    return {
        "cases": total,
        "passed": passed,
        "pass_rate": _pct(passed, total),
        "zero_tolerance": dict(sorted(Counter(c for r in results for c in r.zero_tolerance_codes).items())),
        "failure_codes": dict(sorted(Counter(c for r in results for c in r.failure_codes).items())),
        "outcomes": dict(sorted(Counter(r.outcome for r in results).items())),
        "handoff_reasons": dict(
            sorted(Counter(r.handoff_reason for r in results if r.handoff_reason).items())
        ),
        "by_category": _group(results, lambda r: r.category),
        "by_language": _group(results, lambda r: r.language),
        "tool_selection_acc": _pct(tool_ok, len(tool_cases)),
        "handoff_acc": _pct(handoff_ok, len(handoff_cases)),
        "validator_hit_rate": _pct(sum(1 for r in results if r.validator_codes), total),
        "avg_judge_score": round(sum(scores) / len(scores), 2) if scores else None,
        "judged_cases": len(scores),
        "judge": criteria,
        "latency": {
            "avg_ms": round(sum(latencies) / total) if total else None,
            "p50_ms": percentile(latencies, 0.5),
            "p95_ms": percentile(latencies, 0.95),
        },
        "cost": {
            "total_micros": agent_cost + judge_cost,
            "agent_micros": agent_cost,
            "judge_micros": judge_cost,
            "per_case_micros": round((agent_cost + judge_cost) / total) if total else None,
        },
        "tokens": {"in": sum(r.tokens_in for r in results), "out": sum(r.tokens_out for r in results)},
    }


# ------------------------------------------------------------------ yugurish qadami
class EvalRunner:
    def __init__(self, engine: EvalEngine) -> None:
        self.engine = engine

    async def step(self, database: Database, run_id: UUID) -> str:
        async with database.transaction() as db:
            run = await db.get(EvalRun, run_id, with_for_update=True)
            if run is None or run.status in TERMINAL:
                return "SKIPPED"
            now = utcnow()
            if run.status == "QUEUED":
                run.status, run.started_at = "RUNNING", now
            run.heartbeat_at = now
            if run.cost_micros >= run.cost_cap_micros:
                await self.finish(db, run, "BUDGET_EXCEEDED")
                return "BUDGET_EXCEEDED"
            case = await self._next_case(db, run)
            if case is None:
                await self.finish(db, run)
                return run.status
            spec = (run.provider, run.model_id, run.judge_provider, run.judge_model_id, run.target_shop_id)
        provider, model, judge_provider, judge_model, shop_id = spec
        try:
            async with database.transaction(shop_id) as db:
                settings = await db.get(AgentSettings, shop_id)
                profile, _ = await load_profile(db, shop_id, settings)
            router = self.engine.router(provider, model)
            judge = self.engine.router(judge_provider, judge_model, "judge") if judge_provider else None
            execution = await execute_case(
                router, self.engine.brokers(database), judge, case, profile, shop_id
            )
        except Exception as exc:  # kutilmagan xato — holat ERROR bilan yoziladi, yugurish davom etadi
            logger.exception("sales_ai.eval_case_failed", error=type(exc).__name__)
            execution = CaseExecution(
                score=Score(False, "ERROR", ["ERROR:EVAL_CASE_FAILED"]),
                loop=LoopResult(error_code="EVAL_CASE_FAILED"),
                reply=None,
                latency_ms=0,
            )
        return await self._save(database, run_id, case, execution)

    async def _next_case(self, db: AsyncSession, run: EvalRun) -> CaseInput | None:
        done = select(EvalResult.case_key).where(EvalResult.run_id == run.id)
        query = select(EvalCase).where(EvalCase.dataset_id == run.dataset_id, EvalCase.case_key.not_in(done))
        if run.case_keys:
            query = query.where(EvalCase.case_key.in_(run.case_keys))
        row = (await db.execute(query.order_by(EvalCase.ordinal).limit(1))).scalar_one_or_none()
        if row is None:
            return None
        return CaseInput(
            case_id=row.id,
            case_key=row.case_key,
            ordinal=row.ordinal,
            category=row.category,
            language=row.language,
            message=row.message,
            history=list(row.history or []),
            expectations=Expectations.model_validate(row.expectations),
        )

    async def _save(self, database: Database, run_id: UUID, case: CaseInput, execution: CaseExecution) -> str:
        loop, score = execution.loop, execution.score
        async with database.transaction() as db:
            run = await db.get(EvalRun, run_id, with_for_update=True)
            if run is None:
                return "SKIPPED"
            agent_cost = judge_cost = 0
            for response in [*loop.responses, *loop.check_responses]:
                agent_cost += await record_usage(
                    db,
                    shop_id=None,
                    response=response,
                    price=self.price(response),
                    purpose="EVAL",
                    ref_id=run_id,
                )
            for response in execution.judge_responses:
                judge_cost += await record_usage(
                    db,
                    shop_id=None,
                    response=response,
                    price=self.price(response),
                    purpose="EVAL_JUDGE",
                    ref_id=run_id,
                )
            judge_json: dict[str, Any] | None = None
            if execution.judge is not None:
                judge_json = execution.judge.as_json()
            elif execution.judge_error:
                judge_json = {"error": execution.judge_error}
            inserted = await db.scalar(
                insert(EvalResult)
                .values(
                    id=uuid7(),
                    run_id=run_id,
                    case_id=case.case_id,
                    case_key=case.case_key,
                    ordinal=case.ordinal,
                    category=case.category,
                    language=case.language,
                    passed=score.passed,
                    outcome=score.outcome,
                    handoff_reason=loop.handoff,
                    failure_codes=score.failure_codes,
                    zero_tolerance_codes=score.zero_tolerance_codes,
                    validator_codes=list(loop.validator_codes),
                    tools_called=score.tools_called,
                    reply_text=execution.reply,
                    judge_score=execution.judge.score if execution.judge else None,
                    judge=judge_json,
                    transcript=None if score.passed else _transcript(execution),
                    error_code=loop.error_code,
                    latency_ms=execution.latency_ms,
                    tokens_in=sum(r.usage.input_tokens for r in loop.responses),
                    tokens_out=sum(r.usage.output_tokens + r.usage.thinking_tokens for r in loop.responses),
                    cost_micros=agent_cost,
                    judge_cost_micros=judge_cost,
                )
                .on_conflict_do_nothing(index_elements=["run_id", "case_key"])
                .returning(EvalResult.id)
            )
            if inserted is None:
                return "DUPLICATE"  # boshqa ishchi shu holatni yozib bo'lgan
            run.done_cases += 1
            run.passed_cases += 1 if score.passed else 0
            run.zero_tolerance_violations += len(score.zero_tolerance_codes)
            run.cost_micros += agent_cost + judge_cost
            run.heartbeat_at = utcnow()
            used = {r.model_id for r in loop.responses} - set(run.models_used or [])
            if used:
                run.models_used = sorted({*(run.models_used or []), *used})
            await self.signal(db, run)
            if run.status not in TERMINAL:
                await self.enqueue_step(db, run)
            return "CASE_DONE"

    def price(self, response: LlmResponse) -> ModelPrice | None:
        """Narx — javob bergan provayder routeridan (model ID bo'yicha; noma'lum — ehtiyotkor narx)."""
        return self.engine.routers(response.provider, None).price_for(response)

    async def finish(self, db: AsyncSession, run: EvalRun, forced: str | None = None) -> None:
        results = list((await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))).scalars())
        cases = (
            await db.execute(
                select(EvalCase.case_key, EvalCase.expectations).where(EvalCase.dataset_id == run.dataset_id)
            )
        ).all()
        expectations = {key: Expectations.model_validate(raw) for key, raw in cases}
        run.metrics = aggregate(results, expectations)
        run.done_cases = len(results)
        run.passed_cases = sum(1 for r in results if r.passed)
        run.zero_tolerance_violations = sum(len(r.zero_tolerance_codes) for r in results)
        if forced is not None:
            run.status = forced
        elif run.zero_tolerance_violations:
            run.status = "FAILED"
        elif run.min_pass_rate is not None and run.passed_cases * 100 < run.min_pass_rate * max(
            1, run.done_cases
        ):
            run.status = "FAILED"
        else:
            run.status = "PASSED"
        run.finished_at = utcnow()
        await self.signal(db, run)

    @staticmethod
    async def enqueue_step(db: AsyncSession, run: EvalRun) -> None:
        await db.flush()
        await write_outbox(
            db,
            schema="sales_ai",
            event_type=STEP_EVENT,
            actor=_actor(),
            shop_id=None,
            aggregate_type=AGGREGATE,
            aggregate_id=run.id,
            aggregate_version=run.done_cases + 1,
            payload={"run_id": run.id},
        )

    @staticmethod
    async def signal(db: AsyncSession, run: EvalRun) -> None:
        """Realtime: faqat ID, holat va sonlar (matn yo'q) — platforma adminlari (08 §6.3)."""
        await db.flush()
        await write_outbox(
            db,
            schema="sales_ai",
            event_type=CHANGED_EVENT,
            actor=_actor(),
            shop_id=None,
            aggregate_type=AGGREGATE,
            aggregate_id=run.id,
            aggregate_version=run.done_cases + (2 if run.status in TERMINAL else 1),
            payload={
                "run_id": run.id,
                "bakeoff_id": run.bakeoff_id,
                "status": run.status,
                "done": run.done_cases,
                "total": run.total_cases,
            },
        )
