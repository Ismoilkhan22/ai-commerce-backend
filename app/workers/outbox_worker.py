"""outbox_worker (05 §5): `PENDING` event'larni olib, har tinglovchi uchun vazifa qo'yadi.

    har schema: BEGIN → 100 tadan FOR UPDATE SKIP LOCKED → enqueue(dispatch_event, job_id=event:consumer)
                → PUBLISHED → COMMIT → inline tinglovchilar (alohida tranzaksiyada)

- 1–2 nusxa: SKIP LOCKED tufayli bir qatorni ikkitasi olmaydi.
- Redis ishlamasa: qator PENDING qoladi, 2, 4, 8 … s (≤ 5 daq) kutib qayta uriniladi — Redis sabab hech
  qachon DEAD bo'lmaydi. DEAD — faqat buzilgan envelope.
- Tinglovchisi yo'q event ham PUBLISHED (14 kun tarix).

    python -m app.workers.outbox_worker
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog
from pydantic import ValidationError
from sqlalchemy import select, update

from app.shared.clock import utcnow
from app.shared.events.envelope import EventEnvelope
from app.shared.events.models import OUTBOX_SCHEMAS, outbox_table
from app.shared.events.registry import Subscriber
from app.workers.dispatch import error_code, run_subscriber
from app.workers.runtime import WorkerRuntime

logger = structlog.get_logger(__name__)

BATCH = 100
POLL_INTERVAL_S = 0.5
MAX_REDIS_BACKOFF_S = 300


def job_id(event_id: object, consumer: str) -> str:
    return f"{event_id}:{consumer}"


async def enqueue_dispatch(rt: WorkerRuntime, schema: str, envelope: EventEnvelope, sub: Subscriber) -> bool:
    return await rt.queue.enqueue(
        "dispatch_event",
        job_id=job_id(envelope.event_id, sub.consumer),
        schema=schema,
        event_id=str(envelope.event_id),
        consumer=sub.consumer,
    )


async def dispatch_schema(rt: WorkerRuntime, schema: str, limit: int = BATCH) -> int:
    table = outbox_table(schema)
    now = utcnow()
    inline: list[tuple[Subscriber, EventEnvelope]] = []
    async with rt.database.transaction() as db:
        rows = (
            await db.execute(
                select(table.c.event_id, table.c.envelope, table.c.attempts)
                .where(table.c.status == "PENDING", table.c.next_attempt_at <= now)
                .order_by(table.c.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        published = []
        for event_id, raw, attempts in rows:
            try:
                envelope = EventEnvelope.model_validate(raw)
            except ValidationError:
                await db.execute(
                    update(table)
                    .where(table.c.event_id == event_id)
                    .values(status="DEAD", last_error="InvalidEnvelope")
                )
                logger.error("outbox.dead_event", schema=schema)
                continue
            subs = rt.registry.for_event(envelope.event_type)
            try:
                for sub in subs:
                    if sub.inline:
                        inline.append((sub, envelope))
                    else:
                        await enqueue_dispatch(rt, schema, envelope, sub)
            except Exception as exc:  # navbat (Redis) ishlamayapti — keyinroq
                inline = [(s, e) for s, e in inline if e.event_id != event_id]
                delay = min(2 ** (attempts + 1), MAX_REDIS_BACKOFF_S)
                await db.execute(
                    update(table)
                    .where(table.c.event_id == event_id)
                    .values(
                        attempts=attempts + 1,
                        next_attempt_at=now + timedelta(seconds=delay),
                        last_error=error_code(exc),
                    )
                )
                logger.warning("outbox.enqueue_failed", schema=schema, error=error_code(exc))
                continue
            published.append(event_id)
        if published:
            await db.execute(
                update(table)
                .where(table.c.event_id.in_(published))
                .values(status="PUBLISHED", published_at=now)
            )
    for sub, envelope in inline:  # arzon, o'z schemasiga tegadigan tinglovchilar (05 §5.1)
        try:
            await run_subscriber(rt, sub, envelope)
        except Exception as exc:
            logger.warning("outbox.inline_failed", consumer=sub.consumer, error=error_code(exc))
            try:  # oddiy vazifaga tushadi; navbat ham ishlamasa — rekonsilyatsiya tiklaydi
                await enqueue_dispatch(rt, schema, envelope, sub)
            except Exception as enqueue_exc:
                logger.warning("outbox.inline_fallback_failed", error=error_code(enqueue_exc))
    return len(rows)


async def dispatch_pending(rt: WorkerRuntime, limit: int = BATCH) -> int:
    """Bitta aylanish: hamma schemalar. Nechta event ko'rilgani."""
    total = 0
    for schema in OUTBOX_SCHEMAS:
        total += await dispatch_schema(rt, schema, limit)
    return total


async def run_forever(rt: WorkerRuntime, poll_interval: float = POLL_INTERVAL_S) -> None:
    logger.info("outbox_worker.started", schemas=list(OUTBOX_SCHEMAS))
    while True:
        try:
            seen = await dispatch_pending(rt)
        except Exception as exc:  # baza vaqtincha ishlamasa — jarayon o'lmaydi
            logger.error("outbox_worker.loop_failed", error=error_code(exc))
            seen = 0
        if seen == 0:
            await asyncio.sleep(poll_interval)


async def _main() -> None:
    from app.config.logging import configure_logging
    from app.config.settings import get_settings
    from app.workers.task_worker import arq_queue

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "local")
    queue, pool = await arq_queue(settings)
    from app.workers.runtime import build_runtime

    rt = build_runtime(settings, queue)
    try:
        await run_forever(rt)
    finally:
        await rt.close()
        await pool.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
