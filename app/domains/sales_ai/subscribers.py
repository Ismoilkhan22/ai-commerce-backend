"""sales_ai tinglovchisi: xaridor yozdi → AI navbati (M06 §2).

Tranzaksiyasiz (`transactional=False`): ichida LLM chaqiruvi bor, DB tranzaksiyalarini navbat o'zi qisqa-qisqa
ochadi. Idempotentlik — `ai_turns (conversation_id, trigger_message_id)` unikal va holat (`QUEUED` dan boshqa
bo'lsa — qaytadan ishlanmaydi). Debounce — `RetryLater` (xabar kelganidan 2,5 s o'tmaguncha kutadi).
"""

from __future__ import annotations

from uuid import UUID

import structlog

from app.domains.sales_ai.providers import from_state
from app.shared.events.registry import EventContext, subscriber

logger = structlog.get_logger(__name__)


@subscriber("sales_ai.ai_reply", "messaging.message.received", schema="sales_ai", transactional=False)
async def ai_reply(ctx: EventContext) -> None:
    envelope = ctx.envelope
    conversation_id = envelope.payload.get("conversation_id")
    if envelope.shop_id is None or conversation_id is None:
        return
    services = from_state(ctx.services)
    if services.conversations is None:
        return
    result = await services.runner(ctx.database).on_message(
        envelope.shop_id, UUID(str(conversation_id)), envelope.aggregate_id
    )
    logger.info("sales_ai.turn", result=result, message_id=str(envelope.aggregate_id))


@subscriber("sales_ai.eval_runner", "sales_ai.eval.step", schema="sales_ai", transactional=False)
async def eval_step(ctx: EventContext) -> None:
    """6c: baholash yugurishining bitta holati (tranzaksiyasiz — ichida LLM chaqiruvi). Idempotent: natija
    `(run_id, case_key)` bo'yicha unikal, yakunlangan yugurish qayta ishlanmaydi."""
    run_id = ctx.envelope.payload.get("run_id")
    if run_id is None:
        return
    result = await from_state(ctx.services).eval.runner.step(ctx.database, UUID(str(run_id)))
    logger.info("sales_ai.eval_step", result=result, run_id=str(run_id))
