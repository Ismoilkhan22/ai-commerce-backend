"""`outbox_reconcile` (06 §5.2, §6): Redis ma'lumoti yo'qolsa ham ish yo'qolmaydi.

1. Event `PUBLISHED` bo'lganiga 10 daqiqadan oshgan (1 kun ichida), lekin kutilgan tinglovchida
   `consumer_receipts` belgisi yo'q (va ochiq/ataylab qoldirilgan dead-letter yo'q) → `dispatch_event` qayta
   qo'yiladi. Platforma admini "qayta yuborish" bosgan dead-letter (`REPLAYED`) — event YOSHIDAN QAT'I
   NAZAR (QA 5a F1): replay bir necha kun keyin bosilsa ham ish yo'qolmaydi.
2. Xodim xabari 5 daqiqadan beri `PENDING/SCHEDULED` (tinch soati tugagan yoki navbati yo'qolgan) →
   `notification_send`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text

from app.platform.notifications.services.delivery import due_scheduled
from app.shared.events.models import OUTBOX_SCHEMAS
from app.shared.events.registry import JobContext, JobResult, ScheduledJob, Subscriber

STUCK_AFTER = timedelta(minutes=10)
LOOKBACK = timedelta(days=1)
LIMIT = 500


def _type_filter(sub: Subscriber) -> tuple[str, dict[str, Any]]:
    exact = [t for t in sub.event_types if not t.endswith(".*")]
    prefixes = [t[:-1] + "%" for t in sub.event_types if t.endswith(".*")]
    return "(e.event_type = ANY(:exact) OR e.event_type LIKE ANY(:prefixes))", {
        "exact": exact,
        "prefixes": prefixes,
    }


async def _missing(ctx: JobContext, schema: str, sub: Subscriber) -> list[tuple[str, str | None]]:
    """(event_id, replay belgisi) — belgisi yo'q eventlar. Replay bo'lsa job_id yangi (arq eski natijani
    eslab qolgan bo'lishi mumkin)."""
    condition, params = _type_filter(sub)
    statement = text(
        f"""
        SELECT e.event_id::text, d.resolved_at::text
          FROM {schema}.outbox_events e
          LEFT JOIN platform.dead_letters d ON d.event_id = e.event_id AND d.consumer = :consumer
         WHERE e.status = 'PUBLISHED'
           AND e.published_at < :stuck AND (e.published_at > :since OR d.status = 'REPLAYED')
           AND {condition}
           AND NOT EXISTS (SELECT 1 FROM {sub.schema}.consumer_receipts r
                            WHERE r.consumer = :consumer AND r.event_id = e.event_id)
           AND (d.id IS NULL OR d.status = 'REPLAYED')
         ORDER BY e.published_at
         LIMIT :limit
        """  # noqa: S608 — schema nomlari kod ro'yxatidan
    )
    async with ctx.database.transaction() as db:
        rows = await db.execute(
            statement,
            {
                **params,
                "consumer": sub.consumer,
                "stuck": ctx.now - STUCK_AFTER,
                "since": ctx.now - LOOKBACK,
                "limit": LIMIT,
            },
        )
        return [(event_id, replayed) for event_id, replayed in rows]


async def outbox_reconcile(ctx: JobContext) -> JobResult:
    rt = ctx.services.worker_runtime
    requeued = notifications = 0
    for schema in OUTBOX_SCHEMAS:
        for sub in rt.registry.subscribers:
            for event_id, replayed in await _missing(ctx, schema, sub):
                suffix = f":replay:{replayed}" if replayed else ""
                if await rt.queue.enqueue(
                    "dispatch_event",
                    job_id=f"{event_id}:{sub.consumer}{suffix}",
                    schema=schema,
                    event_id=event_id,
                    consumer=sub.consumer,
                ):
                    requeued += 1
    for shop_id, notification_id in await due_scheduled(ctx.database, ctx.now):
        if await rt.queue.enqueue(
            "notification_send",
            job_id=f"notification:{notification_id}:{int(ctx.now.timestamp()) // 300}",
            shop_id=str(shop_id),
            notification_id=str(notification_id),
        ):
            notifications += 1
    return JobResult(
        affected=requeued + notifications, details={"events": requeued, "notifications": notifications}
    )


WORKER_JOBS = (ScheduledJob("outbox_reconcile", outbox_reconcile, every_seconds=300),)
