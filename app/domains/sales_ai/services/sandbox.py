"""Sinov oynasi — "AI bilan gaplashib ko'rish" (M06 §11, 6b). Haqiqiy suhbat yo'q, xaridorga hech narsa
ketmaydi.

- Sessiya keshda (1 soat): faqat REDACT qilingan tarix va token hisoblagichi — shaxsiy ma'lumot qiymati
  keshga yozilmaydi. Javobdagi tokenlar faqat shu so'rov ichida tiklanadi.
- Agent loop xuddi suhbatdagidek: o'sha prompt, tool'lar, validator. Yozuvchi tool'lar "quruq" — lead,
  taklif, buyurtma yaratilmaydi (`SANDBOX_NOT_SAVED`).
- Rejim OFF bo'lsa ham ishlaydi (AI'ni yoqishdan oldin sinash uchun), lekin provayder sozlangan bo'lishi
  kerak, favqulodda to'xtatish (kill switch) yoqilmagan bo'lishi kerak (F-31).
- Xarajat `ai_usage` ga `SANDBOX` bo'lib yoziladi va **alohida** kunlik limitga kiradi (kunlik limitning 10%,
  limit yo'q bo'lsa $1) — sinov jonli AI'ni hech qachon to'xtatmaydi (F-13).
- Sessiya xodimga bog'langan: boshqa xodim UUID'ni bilsa ham davom ettira olmaydi (F-31).
- Javob tekshiruvi: rejim AUTO bo'lsa — yopiq (xuddi jonli AUTO kabi), aks holda — ochiq.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from app.domains.sales_ai.agent import (
    AgentLoop,
    CheckPolicy,
    LoopResult,
    allowed_tools,
    detect_locale,
    load_profile,
    precheck,
)
from app.domains.sales_ai.common import DEFAULT_HANDOFF_RULES, PROMPT_VERSION, TOOLS
from app.domains.sales_ai.models.orm import AgentSettings
from app.domains.sales_ai.prompts import HistoryItem, history_messages, system_blocks
from app.domains.sales_ai.schemas import SandboxIn, SandboxOut, ToolCallOut, TurnOut
from app.domains.sales_ai.services.gate import MICROS_PER_CENT, AiGateService
from app.domains.sales_ai.tools import ToolBroker, ToolContext
from app.platform.llm.redaction import MemoryPiiStore, redact, restore
from app.platform.llm.router import LlmRouter
from app.platform.llm.usage import day_start, record_usage, spent_since
from app.shared.cache import Cache
from app.shared.clock import utcnow
from app.shared.db.session import Database
from app.shared.errors.base import AIQuotaExceededError, NotFoundError, ProviderUnavailableError
from app.shared.types.actor import ActorContext

SESSION_TTL = 3600
MAX_SESSION_MESSAGES = 40
SANDBOX_DEFAULT_CAP_MICROS = 1_000_000  # $1/kun, jonli limit yo'q bo'lsa
SANDBOX_CAP_SHARE = 10  # jonli kunlik limitning 10%
_TOKEN = re.compile(r"\[([A-Z]+)_(\d+)\]")


def _key(shop_id: UUID, actor_id: UUID | None, session_id: UUID) -> str:
    return f"sales_ai:sandbox:{shop_id}:{actor_id}:{session_id}"


def sandbox_cap_micros(settings: AgentSettings | None) -> int:
    daily = settings.daily_cost_cap_minor if settings else None
    if daily is None:
        return SANDBOX_DEFAULT_CAP_MICROS
    return max(daily * MICROS_PER_CENT // SANDBOX_CAP_SHARE, 100_000)


class SandboxService:
    def __init__(
        self, router: LlmRouter, brokers: Callable[[Database], ToolBroker], gate: AiGateService, cache: Cache
    ) -> None:
        self.router = router
        self.brokers = brokers
        self.gate = gate
        self.cache = cache

    async def message(self, database: Database, actor: ActorContext, body: SandboxIn) -> SandboxOut:
        assert actor.shop_id is not None
        shop_id = actor.shop_id
        if not self.gate.provider_ready:
            raise ProviderUnavailableError("AI provider is not configured", reason="AI_NOT_CONFIGURED")
        session_id = body.session_id or uuid4()
        key = _key(shop_id, actor.actor_id, session_id)
        raw = await self.cache.get(key) if body.session_id else None
        if body.session_id and raw is None:
            raise NotFoundError("Sandbox session expired")
        state = json.loads(raw) if raw else {"history": []}
        history: list[list[str]] = state["history"]
        if len(history) >= MAX_SESSION_MESSAGES:
            raise AIQuotaExceededError(
                "Sandbox session is full — start a new one", reason="SANDBOX_SESSION_FULL"
            )
        store = MemoryPiiStore()
        for _role, text in history:  # oldingi tokenlar raqamini band qilish (qiymatsiz)
            for kind, number in _TOKEN.findall(text):
                store._values.setdefault(f"{kind}_{number}", (kind, f"[{kind}_{number}]"))
        async with database.transaction(shop_id) as db:
            settings = await db.get(AgentSettings, shop_id)
            if settings is not None and settings.kill_switch_at is not None:
                raise ProviderUnavailableError("AI is stopped by the owner", reason="KILL_SWITCH")
            spent, _, _ = await spent_since(db, shop_id, day_start(utcnow()), only=("SANDBOX",))
            if spent >= sandbox_cap_micros(settings):
                raise AIQuotaExceededError("Sandbox cost limit reached", reason="SANDBOX_BUDGET_EXCEEDED")
            profile, profile_version = await load_profile(db, shop_id, settings)
        user_text = await redact(store, body.text)
        history.append(["customer", user_text])
        rules = (settings.handoff_rules if settings else None) or DEFAULT_HANDOFF_RULES
        locale = detect_locale(body.text, None)
        allowed = allowed_tools(settings)
        check: CheckPolicy = "closed" if settings is not None and settings.mode == "AUTO" else "open"
        started = time.monotonic()
        reason = precheck(body.text, rules)
        if reason is not None:
            result = LoopResult(handoff=reason)
        else:
            result = await AgentLoop(self.router, self.brokers(database)).run(
                system_blocks(profile),
                history_messages([HistoryItem(r, t) for r, t in history]),
                ToolContext(
                    shop_id=shop_id,
                    conversation_id=None,
                    customer_ref=None,
                    locale=locale,
                    allowed=allowed,
                    memory_pii=store,
                ),
                check=check,
            )
        cost = 0
        if result.responses or result.check_responses:
            async with database.transaction(shop_id) as db:
                for response in [*result.responses, *result.check_responses]:
                    cost += await record_usage(
                        db,
                        shop_id=shop_id,
                        response=response,
                        price=self.router.price_for(response),
                        purpose="SANDBOX",
                        ref_id=session_id,
                    )
        if result.reply is not None:
            history.append(["assistant", result.reply])
        await self.cache.set(key, json.dumps({"history": history}), SESSION_TTL)
        outcome = "REPLY" if result.reply is not None else ("ERROR" if result.error_code else "HANDOFF")
        turn = TurnOut(
            id=uuid4(),
            conversation_id=None,
            mode="AUTO",
            status="COMPLETED",
            outcome=outcome,
            handoff_reason=result.handoff,
            reply_text=result.reply,
            reply_locale=locale,
            suggestion_status=None,
            provider=result.responses[-1].provider if result.responses else self.router.status.provider,
            model=result.responses[-1].model_id if result.responses else None,
            fallback_used=any(r.fallback_used for r in result.responses),
            prompt_version=f"{PROMPT_VERSION}/p{profile_version or 0}",
            tokens_in=sum(r.usage.input_tokens for r in result.responses),
            tokens_out=sum(r.usage.output_tokens + r.usage.thinking_tokens for r in result.responses),
            cache_read_tokens=sum(r.usage.cache_read_tokens for r in result.responses),
            cost_micros=cost,
            latency_ms=int((time.monotonic() - started) * 1000),
            validator_codes=result.validator_codes,
            rewrite_count=result.rewrite_count,
            error_code=result.error_code,
            tool_calls=[
                ToolCallOut(
                    seq=seq,
                    tool=TOOLS.get(o.name, o.name),
                    decision=o.decision,
                    input=o.args_redacted,
                    output=o.summary or None,
                    error_code=o.error_code,
                    latency_ms=o.latency_ms,
                )
                for seq, o in enumerate(result.outcomes, start=1)
            ],
            drafts=[],
            created_at=None,
        )
        return SandboxOut(
            session_id=session_id,
            reply_text=await restore(store, result.reply) if result.reply is not None else None,
            outcome=outcome,
            handoff_reason=result.handoff,
            turn=turn,
        )

    async def reset(self, actor: ActorContext, session_id: UUID) -> None:
        assert actor.shop_id is not None
        await self.cache.delete(_key(actor.shop_id, actor.actor_id, session_id))
