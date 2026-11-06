"""Tinglovchini bajarish (05 §6) va dead-letter (05 §7).

    BEGIN
      set_config('app.shop_id', envelope.shop_id)
      INSERT INTO <schema>.consumer_receipts (consumer, event_id) ON CONFLICT DO NOTHING
      qator qo'shilmadi → allaqachon bajarilgan → chiqish
      tinglovchi (o'z o'zgarishlari + o'z outbox'i)
    COMMIT

Tranzaksiyasiz tinglovchi (tashqi effekt) — avval belgi tekshiriladi, ish bajariladi, keyin belgi yoziladi:
o'rtada jarayon o'lsa ish takrorlanishi mumkin, shuning uchun u o'z holati bilan idempotent bo'ladi.
8 urinishdan keyin — `platform.dead_letters` (xato matni emas, faqat turi — PII'siz).
"""

from __future__ import annotations

import random
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.platform.jobs.models.orm import DeadLetter
from app.shared.clock import utcnow
from app.shared.events.envelope import EventEnvelope
from app.shared.events.models import outbox_table, receipts_table
from app.shared.events.registry import EventContext, RetryLater, Subscriber
from app.workers.runtime import WorkerRuntime

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 8  # 06 §4.2: 2 s → ~4 daqiqa
MAX_BACKOFF_SECONDS = 240


def backoff_seconds(attempt: int) -> float:
    return min(2.0**attempt, MAX_BACKOFF_SECONDS) + random.uniform(0, 1)  # noqa: S311 — jitter


def error_code(exc: BaseException) -> str:
    """Dead-letter va log uchun: faqat xato turi va (bo'lsa) kodi — xabar matni PII bo'lishi mumkin."""
    code = getattr(exc, "code", None)
    return f"{type(exc).__name__}:{code}" if isinstance(code, str) else type(exc).__name__


async def load_envelope(rt: WorkerRuntime, schema: str, event_id: UUID) -> EventEnvelope | None:
    table = outbox_table(schema)
    async with rt.database.transaction() as db:
        raw = await db.scalar(select(table.c.envelope).where(table.c.event_id == event_id))
    return EventEnvelope.model_validate(raw) if raw is not None else None


async def run_subscriber(rt: WorkerRuntime, sub: Subscriber, envelope: EventEnvelope) -> bool:
    """True — bajarildi; False — avval bajarilgan (dublikat, TC-022)."""
    receipts = receipts_table(sub.schema)
    receipt = (
        insert(receipts)
        .values(consumer=sub.consumer, event_id=envelope.event_id)
        .on_conflict_do_nothing()
        .returning(receipts.c.event_id)
    )
    if sub.transactional:
        async with rt.database.transaction(envelope.shop_id) as db:
            if await db.scalar(receipt) is None:
                return False
            await sub.handler(EventContext(envelope, rt.database, rt.services, db))
        return True
    async with rt.database.transaction() as db:
        done = await db.scalar(
            select(receipts.c.event_id).where(
                receipts.c.consumer == sub.consumer, receipts.c.event_id == envelope.event_id
            )
        )
    if done is not None:
        return False
    await sub.handler(EventContext(envelope, rt.database, rt.services, None))
    async with rt.database.transaction() as db:
        await db.execute(receipt)
    return True


async def dead_letter(
    rt: WorkerRuntime,
    schema: str,
    envelope: EventEnvelope | None,
    event_id: UUID,
    consumer: str,
    attempts: int,
    exc: BaseException,
) -> None:
    now = utcnow()
    values = {
        "event_id": event_id,
        "source_schema": schema,
        "event_type": envelope.event_type if envelope else "unknown",
        "consumer": consumer,
        "shop_id": envelope.shop_id if envelope else None,
        "attempts": attempts,
        "last_error": error_code(exc),
        "first_failed_at": now,
        "last_failed_at": now,
        "status": "OPEN",
    }
    async with rt.database.transaction() as db:
        await db.execute(
            insert(DeadLetter)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["event_id", "consumer"],
                set_={
                    "attempts": values["attempts"],
                    "last_error": values["last_error"],
                    "last_failed_at": now,
                    "status": "OPEN",  # qayta yuborilgan ish yana yiqildi
                    "resolved_at": None,
                    "resolved_by": None,
                },
            )
        )
    logger.error(
        "event.dead_letter", consumer=consumer, event_type=values["event_type"], error=values["last_error"]
    )


async def deliver(rt: WorkerRuntime, schema: str, event_id: UUID, consumer: str, attempt: int) -> str:
    """`dispatch_event` vazifasining yadrosi. Oxirgi urinishdan oldingi xatolar qayta ko'tariladi (retry),
    oxirgisi — dead-letter. Natija: ok | duplicate | missing | dead."""
    sub = rt.registry.get(consumer)
    envelope = await load_envelope(rt, schema, event_id)
    if envelope is None:
        return "missing"  # event 14 kundan keyin tozalangan
    if sub is None:
        await dead_letter(rt, schema, envelope, event_id, consumer, attempt, LookupError("unknown consumer"))
        return "dead"
    try:
        applied = await run_subscriber(rt, sub, envelope)
    except Exception as exc:
        if attempt >= MAX_ATTEMPTS:
            await dead_letter(rt, schema, envelope, event_id, consumer, attempt, exc)
            return "dead"
        if not isinstance(exc, RetryLater):
            logger.warning("event.retry", consumer=consumer, attempt=attempt, error=error_code(exc))
        raise
    return "ok" if applied else "duplicate"
