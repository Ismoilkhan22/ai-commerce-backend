"""Baholash servisi (platforma admini): to'plamlar, yugurishlar, natijalar, bake-off solishtiruvi (A15).

- To'plam muzlatilsa (`frozen`) — o'zgarmaydi; yugurishi bor to'plamning holatlari ham o'zgarmaydi (natijalar
  holatga bog'langan) — yangi versiya klon bilan (`key` bir xil, `version` + 1).
- Yugurish faqat sozlangan provayder bilan (kalit bor; `fake` — har doim). Bepul Gemini kaliti bilan faqat
  demo shop katalogi (A14). Nishon shop — faol bo'lishi kerak; undan faqat o'qiladi.
- Hamma o'zgarish audit jurnaliga (matnsiz).
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.common import PROMPT_VERSION
from app.domains.sales_ai.eval.golden import (
    GOLDEN_CASES,
    GOLDEN_KEY,
    GOLDEN_MANIFEST,
    GOLDEN_NAME,
    GOLDEN_VERSION,
    dataset_checksum,
)
from app.domains.sales_ai.eval.runner import EVAL_DEMO_SHOP_SLUG, TERMINAL, EvalEngine, EvalRunner, aggregate
from app.domains.sales_ai.eval.schemas import (
    BakeoffIn,
    BakeoffOut,
    CaseDiff,
    CaseIn,
    CaseOut,
    CaseSide,
    CompareOut,
    DatasetDetail,
    DatasetIn,
    DatasetList,
    DatasetOut,
    DatasetPatch,
    Delta,
    HistoryTurn,
    ModelChoice,
    ResultList,
    ResultOut,
    RunIn,
    RunList,
    RunOut,
    RunTarget,
)
from app.domains.sales_ai.eval.scoring import Expectations
from app.domains.sales_ai.models.orm import EvalCase, EvalDataset, EvalResult, EvalRun
from app.platform.audit.services.audit_service import AuditService
from app.platform.llm.port import ModelAlias
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.db.ids import uuid7
from app.shared.errors.base import (
    BusinessRuleError,
    InvalidTransitionError,
    NotFoundError,
    ProviderUnavailableError,
    ShopNotActiveError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

DATASET = "sales_ai.eval_dataset"
RUN = "sales_ai.eval_run"


def _field(name: str, code: str) -> dict[str, Any]:
    return {"field": name, "code": code, "params": {}}


def _case_rows(dataset_id: UUID, cases: list[CaseIn]) -> list[EvalCase]:
    return [
        EvalCase(
            id=uuid7(),
            dataset_id=dataset_id,
            case_key=case.case_key,
            ordinal=index,
            category=case.category,
            language=case.language,
            message=case.message,
            history=[h.model_dump() for h in case.history],
            expectations=case.expectations.model_dump(mode="json", exclude_defaults=True),
            notes=case.notes,
        )
        for index, case in enumerate(cases, start=1)
    ]


def _checksum(cases: list[CaseIn]) -> str:
    return dataset_checksum(
        {
            "case_key": c.case_key,
            "category": c.category,
            "language": c.language,
            "message": c.message,
            "history": [h.model_dump() for h in c.history],
            "expectations": c.expectations.model_dump(mode="json", exclude_defaults=True),
        }
        for c in cases
    )


def _delta(base: float | int | None, candidate: float | int | None) -> Delta:
    b = float(base) if base is not None else None
    c = float(candidate) if candidate is not None else None
    return Delta(base=b, candidate=c, delta=round(c - b, 4) if b is not None and c is not None else None)


def _side(result: EvalResult | None) -> CaseSide | None:
    if result is None:
        return None
    return CaseSide(
        passed=result.passed,
        failure_codes=list(result.failure_codes),
        handoff_reason=result.handoff_reason,
        tools_called=list(result.tools_called),
        judge_score=result.judge_score,
        latency_ms=result.latency_ms,
        cost_micros=result.cost_micros + result.judge_cost_micros,
    )


def _result_out(r: EvalResult) -> ResultOut:
    return ResultOut(
        case_key=r.case_key,
        ordinal=r.ordinal,
        category=r.category,
        language=r.language,
        passed=r.passed,
        outcome=r.outcome,
        handoff_reason=r.handoff_reason,
        failure_codes=list(r.failure_codes),
        zero_tolerance_codes=list(r.zero_tolerance_codes),
        validator_codes=list(r.validator_codes),
        tools_called=list(r.tools_called),
        reply_text=r.reply_text,
        judge_score=r.judge_score,
        judge=r.judge,
        transcript=r.transcript,
        error_code=r.error_code,
        latency_ms=r.latency_ms,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        cost_micros=r.cost_micros,
        judge_cost_micros=r.judge_cost_micros,
    )


class EvalService:
    def __init__(self, engine: EvalEngine, audit: AuditService) -> None:
        self.engine = engine
        self.audit = audit
        self.runner = EvalRunner(engine)

    # ------------------------------------------------------------------ to'plamlar
    async def _dataset(self, db: AsyncSession, dataset_id: UUID, *, lock: bool = False) -> EvalDataset:
        dataset = await db.get(EvalDataset, dataset_id, with_for_update=lock)
        if dataset is None:
            raise NotFoundError("Eval dataset not found")
        return dataset

    async def _runs_count(self, db: AsyncSession, dataset_id: UUID) -> int:
        return int(await db.scalar(select(func.count()).where(EvalRun.dataset_id == dataset_id)) or 0)

    async def _dataset_out(self, db: AsyncSession, dataset: EvalDataset) -> DatasetOut:
        rows = (
            await db.execute(
                select(EvalCase.category, EvalCase.language).where(EvalCase.dataset_id == dataset.id)
            )
        ).all()
        return DatasetOut(
            id=dataset.id,
            key=dataset.key,
            version=dataset.version,
            name=dataset.name,
            description=dataset.description,
            manifest=dataset.manifest or {},
            checksum=dataset.checksum,
            rows=dataset.rows,
            frozen=dataset.frozen,
            archived=dataset.archived_at is not None,
            revision=dataset.revision,
            categories=dict(sorted(Counter(c for c, _ in rows).items())),
            languages=dict(sorted(Counter(lang for _, lang in rows).items())),
            runs=await self._runs_count(db, dataset.id),
            created_at=dataset.created_at,
            updated_at=dataset.updated_at,
        )

    async def _detail(self, db: AsyncSession, dataset: EvalDataset) -> DatasetDetail:
        await db.flush()
        await db.refresh(dataset)
        cases = (
            await db.execute(
                select(EvalCase).where(EvalCase.dataset_id == dataset.id).order_by(EvalCase.ordinal)
            )
        ).scalars()
        out = await self._dataset_out(db, dataset)
        return DatasetDetail(
            **out.model_dump(),
            cases=[
                CaseOut(
                    id=c.id,
                    case_key=c.case_key,
                    ordinal=c.ordinal,
                    category=c.category,
                    language=c.language,
                    message=c.message,
                    history=[HistoryTurn.model_validate(h) for h in c.history or []],
                    expectations=Expectations.model_validate(c.expectations),
                    notes=c.notes,
                )
                for c in cases
            ],
        )

    async def list_datasets(self, db: AsyncSession, *, include_archived: bool = False) -> DatasetList:
        query = select(EvalDataset).order_by(EvalDataset.key, EvalDataset.version.desc())
        if not include_archived:
            query = query.where(EvalDataset.archived_at.is_(None))
        datasets = (await db.execute(query)).scalars().all()
        return DatasetList(items=[await self._dataset_out(db, d) for d in datasets])

    async def get_dataset(self, db: AsyncSession, dataset_id: UUID) -> DatasetDetail:
        return await self._detail(db, await self._dataset(db, dataset_id))

    async def _create(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        key: str,
        name: str,
        description: str | None,
        manifest: dict[str, Any],
        cases: list[CaseIn],
        frozen: bool = False,
        version: int | None = None,
    ) -> EvalDataset:
        if version is None:
            latest = await db.scalar(select(func.max(EvalDataset.version)).where(EvalDataset.key == key))
            version = int(latest or 0) + 1
        dataset = EvalDataset(
            id=uuid7(),
            key=key,
            version=version,
            name=name,
            description=description,
            manifest=manifest,
            checksum=_checksum(cases),
            rows=len(cases),
            frozen=frozen,
            created_by=actor.actor_id,
        )
        db.add(dataset)
        await db.flush()
        db.add_all(_case_rows(dataset.id, cases))
        await self.audit.record(
            db,
            action="sales_ai.eval.dataset_created",
            entity_type=DATASET,
            entity_id=dataset.id,
            actor=actor,
            entity_version=dataset.revision,
            diff={"key": key, "version": version, "rows": len(cases)},
        )
        return dataset

    async def create_dataset(self, db: AsyncSession, actor: ActorContext, body: DatasetIn) -> DatasetDetail:
        dataset = await self._create(
            db,
            actor,
            key=body.key,
            name=body.name,
            description=body.description,
            manifest=body.manifest,
            cases=body.cases,
        )
        return await self._detail(db, dataset)

    async def install_golden(self, db: AsyncSession, actor: ActorContext) -> tuple[DatasetDetail, bool]:
        """Kodda yozilgan golden to'plamni bazaga qo'yadi (muzlatilgan). Takroriy chaqiruv — o'sha to'plam."""
        existing = (
            await db.execute(
                select(EvalDataset).where(
                    EvalDataset.key == GOLDEN_KEY, EvalDataset.version == GOLDEN_VERSION
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return await self._detail(db, existing), False
        cases = [CaseIn.model_validate(c) for c in GOLDEN_CASES]
        dataset = await self._create(
            db,
            actor,
            key=GOLDEN_KEY,
            name=GOLDEN_NAME,
            description="Boshlang'ich sintetik to'plam: qidiruv, yig'ma, moslik, qoldiq, chegirma, prompt "
            "injection, PII, mavzudan tashqari, buyurtma qoralamasi (uz, uz-Cyrl, ru, en).",
            manifest=dict(GOLDEN_MANIFEST),
            cases=cases,
            frozen=True,
            version=GOLDEN_VERSION,
        )
        return await self._detail(db, dataset), True

    async def patch_dataset(
        self, db: AsyncSession, actor: ActorContext, dataset_id: UUID, revision: int, body: DatasetPatch
    ) -> DatasetDetail:
        dataset = await self._dataset(db, dataset_id, lock=True)
        check_version(dataset.revision, revision)
        if dataset.frozen or dataset.archived_at is not None:
            raise InvalidTransitionError(
                "Frozen or archived dataset cannot be changed — clone it",
                entity=DATASET,
                **{"from": "FROZEN" if dataset.frozen else "ARCHIVED"},
                command="EDIT",
                reason="DATASET_FROZEN",
            )
        changed: list[str] = []
        for name in ("name", "description", "manifest"):
            if name in body.model_fields_set:
                value = getattr(body, name)
                if name == "name" and value is None:
                    raise ValidationError("Name is required", fields=[_field("name", "required")])
                setattr(dataset, name, value if value is not None or name == "description" else {})
                changed.append(name)
        if body.cases is not None:
            if await self._runs_count(db, dataset.id):
                raise InvalidTransitionError(
                    "Dataset already has runs — clone it to change cases",
                    entity=DATASET,
                    **{"from": "HAS_RUNS"},
                    command="EDIT_CASES",
                    reason="DATASET_HAS_RUNS",
                )
            await db.execute(delete(EvalCase).where(EvalCase.dataset_id == dataset.id))
            db.add_all(_case_rows(dataset.id, body.cases))
            dataset.checksum, dataset.rows = _checksum(body.cases), len(body.cases)
            changed.append("cases")
        if body.frozen:
            dataset.frozen = True
            changed.append("frozen")
        if changed:
            dataset.updated_at = utcnow()
            await db.flush()
            await self.audit.record(
                db,
                action="sales_ai.eval.dataset_updated",
                entity_type=DATASET,
                entity_id=dataset.id,
                actor=actor,
                entity_version=dataset.revision,
                diff={"fields": changed},
            )
        return await self._detail(db, dataset)

    async def clone_dataset(self, db: AsyncSession, actor: ActorContext, dataset_id: UUID) -> DatasetDetail:
        source = await self.get_dataset(db, dataset_id)
        dataset = await self._create(
            db,
            actor,
            key=source.key,
            name=source.name,
            description=source.description,
            manifest={**source.manifest, "cloned_from": str(source.id)},
            cases=[CaseIn.model_validate(c.model_dump(exclude={"id", "ordinal"})) for c in source.cases],
        )
        return await self._detail(db, dataset)

    async def delete_dataset(self, db: AsyncSession, actor: ActorContext, dataset_id: UUID) -> None:
        """Yugurishi yo'q — o'chiriladi; bor bo'lsa — arxivlanadi (natijalar tarixi saqlanadi)."""
        dataset = await self._dataset(db, dataset_id, lock=True)
        if await self._runs_count(db, dataset.id):
            if dataset.archived_at is None:
                dataset.archived_at = utcnow()
            action = "sales_ai.eval.dataset_archived"
        else:
            await db.delete(dataset)
            action = "sales_ai.eval.dataset_deleted"
        await self.audit.record(db, action=action, entity_type=DATASET, entity_id=dataset_id, actor=actor)

    # ------------------------------------------------------------------ yugurishlar
    async def _target(self, db: AsyncSession, target: RunTarget) -> UUID:
        if target.kind == "DEMO":
            shop = (
                await db.execute(select(Shop).where(Shop.slug == EVAL_DEMO_SHOP_SLUG))
            ).scalar_one_or_none()
            if shop is None or shop.status != "ACTIVE":
                raise BusinessRuleError("Demo shop is not available", reason="EVAL_DEMO_SHOP_MISSING")
            return shop.id
        assert target.shop_id is not None
        shop = await db.get(Shop, target.shop_id)
        if shop is None:
            raise NotFoundError("Shop not found")
        if shop.status != "ACTIVE":
            raise ShopNotActiveError("Shop is not active")
        return shop.id

    def _model(self, choice: ModelChoice, alias: ModelAlias, target: RunTarget) -> str:
        router = self.engine.router(choice.provider, choice.model, alias)
        if choice.provider != "fake" and not router.status.key_present:
            raise ProviderUnavailableError("AI provider is not configured", reason="AI_NOT_CONFIGURED")
        if choice.provider == "gemini" and self.engine.gemini_free and target.kind != "DEMO":
            # A14: bepul kalit ma'lumotdan o'rganishi mumkin — shop katalogi unga yuborilmaydi
            raise BusinessRuleError("Free Gemini key — demo shop only", reason="EVAL_FREE_TIER_DEMO_ONLY")
        return choice.model or router.models_for(alias)[0]

    async def _create_run(
        self,
        db: AsyncSession,
        actor: ActorContext,
        options: RunIn | BakeoffIn,
        choice: ModelChoice,
        bakeoff_id: UUID | None,
    ) -> EvalRun:
        dataset = await self._dataset(db, options.dataset_id)
        if dataset.archived_at is not None:
            raise InvalidTransitionError(
                "Dataset is archived",
                entity=DATASET,
                **{"from": "ARCHIVED"},
                command="RUN",
                reason="DATASET_ARCHIVED",
            )
        keys = set(
            (await db.execute(select(EvalCase.case_key).where(EvalCase.dataset_id == dataset.id))).scalars()
        )
        if options.case_keys is not None:
            unknown = sorted(set(options.case_keys) - keys)
            if unknown:
                raise ValidationError(
                    "Unknown case keys", fields=[_field("case_keys", "invalid")], unknown=unknown[:10]
                )
        total = len(set(options.case_keys)) if options.case_keys is not None else len(keys)
        if total == 0:
            raise ValidationError("Dataset has no cases", fields=[_field("dataset_id", "empty")])
        model_id = self._model(choice, "seller", options.target)
        judge_model = self._model(options.judge, "judge", options.target) if options.judge else None
        shop_id = await self._target(db, options.target)
        run = EvalRun(
            id=uuid7(),
            dataset_id=dataset.id,
            dataset_checksum=dataset.checksum,
            bakeoff_id=bakeoff_id,
            label=options.label,
            prompt_version=PROMPT_VERSION,
            provider=choice.provider,
            model_alias="seller",
            model_id=model_id,
            models_used=[],
            git_sha=self.engine.git_sha,
            target_kind=options.target.kind,
            target_shop_id=shop_id,
            judge_provider=options.judge.provider if options.judge else None,
            judge_model_id=judge_model,
            case_keys=sorted(set(options.case_keys)) if options.case_keys is not None else None,
            min_pass_rate=options.min_pass_rate,
            status="QUEUED",
            total_cases=total,
            done_cases=0,
            passed_cases=0,
            zero_tolerance_violations=0,
            cost_cap_micros=options.cost_cap_micros,
            cost_micros=0,
            metrics={},
            started_by=actor.actor_id,
        )
        db.add(run)
        await db.flush()
        await self.audit.record(
            db,
            action="sales_ai.eval.run_started",
            entity_type=RUN,
            entity_id=run.id,
            actor=actor,
            diff={
                "dataset_id": str(dataset.id),
                "provider": choice.provider,
                "model": model_id,
                "target": options.target.kind,
                "cost_cap_micros": options.cost_cap_micros,
            },
        )
        await self.runner.signal(db, run)
        await self.runner.enqueue_step(db, run)
        return run

    async def start_run(self, db: AsyncSession, actor: ActorContext, body: RunIn) -> RunOut:
        run = await self._create_run(
            db, actor, body, ModelChoice(provider=body.provider, model=body.model), None
        )
        return await self._run_out(db, run)

    async def start_bakeoff(self, db: AsyncSession, actor: ActorContext, body: BakeoffIn) -> BakeoffOut:
        bakeoff_id = uuid7()
        runs = [await self._create_run(db, actor, body, choice, bakeoff_id) for choice in body.candidates]
        return BakeoffOut(bakeoff_id=bakeoff_id, runs=[await self._run_out(db, r) for r in runs])

    async def _run(self, db: AsyncSession, run_id: UUID, *, lock: bool = False) -> EvalRun:
        run = await db.get(EvalRun, run_id, with_for_update=lock)
        if run is None:
            raise NotFoundError("Eval run not found")
        return run

    async def _run_out(self, db: AsyncSession, run: EvalRun) -> RunOut:
        dataset = await db.get(EvalDataset, run.dataset_id)
        assert dataset is not None
        return RunOut(
            id=run.id,
            dataset_id=run.dataset_id,
            dataset_key=dataset.key,
            dataset_version=dataset.version,
            dataset_checksum=run.dataset_checksum,
            bakeoff_id=run.bakeoff_id,
            label=run.label,
            status=run.status,
            provider=run.provider,
            model_id=run.model_id,
            models_used=list(run.models_used or []),
            prompt_version=run.prompt_version,
            ruleset_version=run.ruleset_version,
            git_sha=run.git_sha,
            target_kind=run.target_kind,
            target_shop_id=run.target_shop_id,
            judge_provider=run.judge_provider,
            judge_model_id=run.judge_model_id,
            total_cases=run.total_cases,
            done_cases=run.done_cases,
            passed_cases=run.passed_cases,
            pass_rate=round(run.passed_cases / run.done_cases, 4) if run.done_cases else None,
            zero_tolerance_violations=run.zero_tolerance_violations,
            cost_cap_micros=run.cost_cap_micros,
            cost_micros=run.cost_micros,
            min_pass_rate=run.min_pass_rate,
            metrics=run.metrics or {},
            error_code=run.error_code,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )

    async def list_runs(
        self,
        db: AsyncSession,
        *,
        dataset_id: UUID | None,
        bakeoff_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> RunList:
        query = (
            select(EvalRun).order_by(EvalRun.created_at.desc(), EvalRun.id.desc()).limit(limit).offset(offset)
        )
        if dataset_id is not None:
            query = query.where(EvalRun.dataset_id == dataset_id)
        if bakeoff_id is not None:
            query = query.where(EvalRun.bakeoff_id == bakeoff_id)
        if status is not None:
            query = query.where(EvalRun.status == status)
        runs = (await db.execute(query)).scalars().all()
        return RunList(items=[await self._run_out(db, r) for r in runs])

    async def get_run(self, db: AsyncSession, run_id: UUID) -> RunOut:
        return await self._run_out(db, await self._run(db, run_id))

    async def results(self, db: AsyncSession, run_id: UUID, *, failed_only: bool = False) -> ResultList:
        await self._run(db, run_id)
        query = select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.ordinal)
        if failed_only:
            query = query.where(EvalResult.passed.is_(False))
        return ResultList(items=[_result_out(r) for r in (await db.execute(query)).scalars()])

    async def cancel(self, db: AsyncSession, actor: ActorContext, run_id: UUID) -> RunOut:
        run = await self._run(db, run_id, lock=True)
        if run.status in TERMINAL:
            raise InvalidTransitionError(
                "Run already finished", entity=RUN, **{"from": run.status}, command="CANCEL"
            )
        run.status, run.finished_at, run.error_code = "CANCELLED", utcnow(), "CANCELLED_BY_ADMIN"
        await self.runner.finish(db, run, "CANCELLED")
        await self.audit.record(
            db, action="sales_ai.eval.run_cancelled", entity_type=RUN, entity_id=run.id, actor=actor
        )
        return await self._run_out(db, run)

    # ------------------------------------------------------------------ bake-off (A15)
    async def _live_metrics(self, db: AsyncSession, run: EvalRun) -> tuple[dict[str, Any], list[EvalResult]]:
        results = list((await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))).scalars())
        rows = (
            await db.execute(
                select(EvalCase.case_key, EvalCase.expectations).where(EvalCase.dataset_id == run.dataset_id)
            )
        ).all()
        return aggregate(results, {k: Expectations.model_validate(v) for k, v in rows}), results

    async def compare(self, db: AsyncSession, base_id: UUID, candidate_id: UUID) -> CompareOut:
        base, candidate = await self._run(db, base_id), await self._run(db, candidate_id)
        if base.dataset_id != candidate.dataset_id:
            raise BusinessRuleError("Runs use different datasets", reason="EVAL_DATASET_MISMATCH")
        bm, b_results = await self._live_metrics(db, base)
        cm, c_results = await self._live_metrics(db, candidate)
        aggregate_delta = {
            "pass_rate": _delta(bm["pass_rate"], cm["pass_rate"]),
            "zero_tolerance_violations": _delta(
                sum(bm["zero_tolerance"].values()), sum(cm["zero_tolerance"].values())
            ),
            "tool_selection_acc": _delta(bm["tool_selection_acc"], cm["tool_selection_acc"]),
            "handoff_acc": _delta(bm["handoff_acc"], cm["handoff_acc"]),
            "validator_hit_rate": _delta(bm["validator_hit_rate"], cm["validator_hit_rate"]),
            "avg_judge_score": _delta(bm["avg_judge_score"], cm["avg_judge_score"]),
            "avg_latency_ms": _delta(bm["latency"]["avg_ms"], cm["latency"]["avg_ms"]),
            "p50_latency_ms": _delta(bm["latency"]["p50_ms"], cm["latency"]["p50_ms"]),
            "p95_latency_ms": _delta(bm["latency"]["p95_ms"], cm["latency"]["p95_ms"]),
            "cost_per_case_micros": _delta(bm["cost"]["per_case_micros"], cm["cost"]["per_case_micros"]),
            "total_cost_micros": _delta(bm["cost"]["total_micros"], cm["cost"]["total_micros"]),
        }

        def by(key: str) -> dict[str, Delta]:
            names = sorted({*bm[key], *cm[key]})
            return {
                n: _delta(bm[key].get(n, {}).get("pass_rate"), cm[key].get(n, {}).get("pass_rate"))
                for n in names
            }

        b_map = {r.case_key: r for r in b_results}
        c_map = {r.case_key: r for r in c_results}
        diffs: list[CaseDiff] = []
        for key in sorted({*b_map, *c_map}, key=lambda k: (b_map.get(k) or c_map[k]).ordinal):
            b, c = b_map.get(key), c_map.get(key)
            if b and c:
                change = (
                    "BOTH_PASS"
                    if b.passed and c.passed
                    else "BOTH_FAIL"
                    if not b.passed and not c.passed
                    else "REGRESSION"
                    if b.passed
                    else "IMPROVEMENT"
                )
            else:
                change = "ONLY_BASE" if b else "ONLY_CANDIDATE"
            ref = b or c
            assert ref is not None
            judge_delta = (
                round(float(c.judge_score) - float(b.judge_score), 2)
                if b and c and b.judge_score is not None and c.judge_score is not None
                else None
            )
            diffs.append(
                CaseDiff(
                    case_key=key,
                    category=ref.category,
                    language=ref.language,
                    change=change,
                    base=_side(b),
                    candidate=_side(c),
                    judge_delta=judge_delta,
                )
            )
        counts = dict(Counter(d.change for d in diffs))
        return CompareOut(
            base=await self._run_out(db, base),
            candidate=await self._run_out(db, candidate),
            aggregate=aggregate_delta,
            by_category=by("by_category"),
            by_language=by("by_language"),
            counts={k: counts.get(k, 0) for k in ("REGRESSION", "IMPROVEMENT", "BOTH_PASS", "BOTH_FAIL")},
            cases=diffs,
        )
