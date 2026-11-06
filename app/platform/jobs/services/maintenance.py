"""Platforma tozalash ishlari (06 §5.2, db/jobs.md §5): TD-01 partitsiyalar, TD-02 takroriy so'rov kalitlari,
outbox va jurnallar.

Har ish bo'laklab (1000 tadan) va holat bo'yicha ishlaydi: o'tkazib yuborilgan ishga tushish keyingisida
yetib olinadi, ikki marta ishlasa ham natija bir xil.
"""

from __future__ import annotations

from sqlalchemy import text

from app.shared.events.models import OUTBOX_SCHEMAS, RECEIPT_SCHEMAS
from app.shared.events.registry import JobContext, JobResult

BATCH = 1000
PARTITION_MONTHS_AHEAD = 12  # TD-01: kamida 12 oy oldinga
OUTBOX_PUBLISHED_DAYS = 14  # DEC-138, 2-qaror
RECEIPTS_DAYS = 7  # 07 §5.3
JOB_RUNS_DAYS = 30  # db/jobs.md §4


async def _purge(ctx: JobContext, statement: str, **params: object) -> int:
    """`statement` bitta bo'lakni o'chiradi (LIMIT :batch); bo'lak to'liq bo'lsa — yana."""
    total = 0
    while True:
        async with ctx.database.transaction() as db:
            result = await db.execute(text(statement), {"batch": BATCH, **params})
        deleted = int(getattr(result, "rowcount", 0) or 0)
        total += deleted
        if deleted < BATCH:
            return total


async def idempotency_cleanup(ctx: JobContext) -> JobResult:
    """TD-02: muddati o'tgan `platform.idempotency_keys` (24 soat, 07 §5.3)."""
    deleted = await _purge(
        ctx,
        "DELETE FROM platform.idempotency_keys WHERE (shop_id, operation, key) IN ("
        " SELECT shop_id, operation, key FROM platform.idempotency_keys"
        " WHERE expires_at < :now LIMIT :batch)",
        now=ctx.now,
    )
    return JobResult(affected=deleted)


async def partition_create(ctx: JobContext) -> JobResult:
    """TD-01: `transition_log` va `audit_entries` uchun joriy + 12 oy partitsiyasi.

    Ilova rolida DDL huquqi yo'q — `app_migrator` egaligidagi `platform.ensure_monthly_partitions`
    (SECURITY DEFINER, DEC-138 3-qaror) orqali.
    """
    async with ctx.database.transaction() as db:
        created = int(
            await db.scalar(
                text("SELECT platform.ensure_monthly_partitions(:months)"), {"months": PARTITION_MONTHS_AHEAD}
            )
            or 0
        )
    return JobResult(affected=created, details={"months_ahead": PARTITION_MONTHS_AHEAD})


async def outbox_cleanup(ctx: JobContext) -> JobResult:
    """Yuborilgan event'lar 14 kun, `consumer_receipts` 7 kun, ish jurnali 30 kun saqlanadi.

    Hal qilinmagan dead-letter'li event o'chirilmaydi: `OPEN` — admin hali qaror qilmagan; `REPLAYED` — oxirgi
    1 kun ichida (qayta yuborish bajarilayotgan bo'lishi mumkin). Aks holda replay imkonsiz (QA 5a F1).
    """
    details: dict[str, int] = {}
    for schema in OUTBOX_SCHEMAS:
        details[f"{schema}.outbox"] = await _purge(
            ctx,
            f"DELETE FROM {schema}.outbox_events WHERE event_id IN ("  # noqa: S608 — schema ro'yxatdan
            f" SELECT e.event_id FROM {schema}.outbox_events e WHERE e.status = 'PUBLISHED'"
            " AND e.published_at < :now - make_interval(days => :days)"
            " AND NOT EXISTS (SELECT 1 FROM platform.dead_letters d WHERE d.event_id = e.event_id"
            "   AND (d.status = 'OPEN'"
            "        OR (d.status = 'REPLAYED' AND d.resolved_at > :now - interval '1 day')))"
            " LIMIT :batch)",
            now=ctx.now,
            days=OUTBOX_PUBLISHED_DAYS,
        )
    for schema in RECEIPT_SCHEMAS:
        details[f"{schema}.receipts"] = await _purge(
            ctx,
            f"DELETE FROM {schema}.consumer_receipts WHERE (consumer, event_id) IN ("  # noqa: S608
            f" SELECT consumer, event_id FROM {schema}.consumer_receipts"
            " WHERE applied_at < :now - make_interval(days => :days) LIMIT :batch)",
            now=ctx.now,
            days=RECEIPTS_DAYS,
        )
    details["job_runs"] = await _purge(
        ctx,
        "DELETE FROM platform.job_runs WHERE id IN (SELECT id FROM platform.job_runs"
        " WHERE started_at < :now - make_interval(days => :days) LIMIT :batch)",
        now=ctx.now,
        days=JOB_RUNS_DAYS,
    )
    return JobResult(affected=sum(details.values()), details=details)
