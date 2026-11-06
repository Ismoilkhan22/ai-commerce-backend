"""Platforma paneli: dead-letter'lar (05 §7) va rejali ishlar sog'ligi (06 §8, db/jobs.md §4).

Qayta yuborish: event hali bor bo'lsa — tinglovchi DARHOL navbatga qo'yiladi va yozuv `REPLAYED` bo'ladi;
navbat ishlamasa, `outbox_reconcile` uni (yoshidan qat'i nazar) qayta qo'yadi. Event tozalab yuborilgan
bo'lsa — 409, soxta "REPLAYED" yo'q (QA 5a F1). Bajarilgan qism takrorlanmaydi (consumer_receipts).
Shop xodimlariga ko'rinmaydi.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text

from app.platform.audit.services.audit_service import AuditService
from app.platform.jobs.models.orm import DeadLetter, JobRun
from app.platform.jobs.schemas import (
    DeadLetterList,
    DeadLetterOut,
    DeadLetterResolveIn,
    DeadLetterStatus,
    JobHealth,
    JobHealthList,
)
from app.platform.jobs.services.queue import task_queue
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.shared.clock import utcnow
from app.shared.errors.base import InvalidTransitionError, NotFoundError
from app.shared.events.models import OUTBOX_SCHEMAS

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["platform"])

CanView = Annotated[RequestContext, Depends(require_platform_permission("platform.dead_letter.view"))]
CanReplay = Annotated[RequestContext, Depends(require_platform_permission("platform.dead_letter.replay"))]
_audit = AuditService()


def _out(row: DeadLetter) -> DeadLetterOut:
    return DeadLetterOut.model_validate(row, from_attributes=True)


@router.get("/dead-letters", response_model=DeadLetterList)
async def list_dead_letters(
    ctx: CanView,
    status: Annotated[DeadLetterStatus | None, Query()] = "OPEN",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DeadLetterList:
    query = select(DeadLetter).order_by(DeadLetter.last_failed_at.desc()).limit(limit)
    if status is not None:
        query = query.where(DeadLetter.status == status)
    rows = (await ctx.db.execute(query)).scalars().all()
    open_count = int(
        await ctx.db.scalar(select(func.count()).select_from(DeadLetter).where(DeadLetter.status == "OPEN"))
        or 0
    )
    return DeadLetterList(items=[_out(r) for r in rows], open_count=open_count)


async def _open_letter(ctx: RequestContext, letter_id: UUID, command: str) -> DeadLetter:
    row = (
        await ctx.db.execute(select(DeadLetter).where(DeadLetter.id == letter_id).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Dead letter not found")
    if row.status != "OPEN":
        raise InvalidTransitionError(
            "Dead letter is not open", entity="platform.dead_letter", **{"from": row.status}, command=command
        )
    return row


async def _resolve(
    ctx: RequestContext, row: DeadLetter, status: str, note: str, **audit: object
) -> DeadLetterOut:
    row.status, row.resolved_by, row.resolved_at = status, ctx.actor.actor_id, utcnow()
    row.resolution_note = note
    await ctx.db.flush()
    await _audit.record(
        ctx.db,
        action=f"platform.dead_letter.{status.lower()}",
        entity_type="platform.dead_letter",
        entity_id=row.id,
        actor=ctx.actor,
        reason=note,
        diff={"consumer": row.consumer, "event_type": row.event_type, **audit},
    )
    return _out(row)


async def _event_exists(ctx: RequestContext, schema: str, event_id: UUID) -> bool:
    if schema not in OUTBOX_SCHEMAS:
        return False
    found = await ctx.db.scalar(
        text(f"SELECT 1 FROM {schema}.outbox_events WHERE event_id = :id"),  # noqa: S608 — ro'yxatdan
        {"id": event_id},
    )
    return found is not None


@router.post("/dead-letters/{letter_id}/replay", response_model=DeadLetterOut)
async def replay_dead_letter(
    letter_id: UUID, body: DeadLetterResolveIn, request: Request, ctx: CanReplay
) -> DeadLetterOut:
    row = await _open_letter(ctx, letter_id, "REPLAYED")
    if not await _event_exists(ctx, row.source_schema, row.event_id):
        # Event saqlash muddati (14 kun) o'tib tozalangan: qayta yuborib bo'lmaydi, faqat e'tiborsiz qoldirish
        raise InvalidTransitionError(
            "Event no longer exists",
            entity="platform.dead_letter",
            **{"from": row.status},
            command="REPLAYED",
            reason="event_purged",
        )
    out = await _resolve(ctx, row, "REPLAYED", body.note)
    replayed_at = row.resolved_at.isoformat() if row.resolved_at else ""
    try:
        queue = await task_queue(request.app.state)
        enqueued = await queue.enqueue(
            "dispatch_event",
            job_id=f"{row.event_id}:{row.consumer}:replay:{replayed_at}",
            schema=row.source_schema,
            event_id=str(row.event_id),
            consumer=row.consumer,
        )
    except Exception as exc:  # navbat ishlamasa — outbox_reconcile qayta qo'yadi (yoshidan qat'i nazar)
        logger.warning("dead_letter.replay_enqueue_failed", error=type(exc).__name__)
        enqueued = False
    logger.info("dead_letter.replayed", consumer=row.consumer, enqueued=enqueued)
    return out


@router.post("/dead-letters/{letter_id}/ignore", response_model=DeadLetterOut)
async def ignore_dead_letter(letter_id: UUID, body: DeadLetterResolveIn, ctx: CanReplay) -> DeadLetterOut:
    return await _resolve(ctx, await _open_letter(ctx, letter_id, "IGNORED"), "IGNORED", body.note)


def interval_of(every_seconds: int | None, cron: str | None) -> int | None:
    """Cron uchun taxminiy oraliq: oy kuni berilgan — oylik, soat berilgan — kunlik, aks holda soatlik."""
    if every_seconds is not None:
        return every_seconds
    if not cron:
        return None
    minute, hour, day = [*cron.split(), "*", "*", "*"][:3]
    if day != "*":
        return 31 * 86400
    if hour != "*":
        return 86400
    if minute.startswith("*/"):
        return int(minute[2:]) * 60
    return 3600


@router.get("/jobs", response_model=JobHealthList)
async def job_health(request: Request, ctx: CanView) -> JobHealthList:
    """Har ro'yxatdagi ishning jadvali, oxirgi ishga tushishi va muvaffaqiyati (Grafana kelgunga qadar).
    Hech ishlamagan ish ham ko'rinadi — "3 × oraliq" ogohlantirishi uni ham ushlaydi (QA 5a I2)."""
    latest = (
        select(JobRun.job_name, func.max(JobRun.started_at).label("started_at"))
        .group_by(JobRun.job_name)
        .subquery()
    )
    last_ok = (
        select(JobRun.job_name, func.max(JobRun.started_at).label("ok_at"))
        .where(JobRun.status == "OK")
        .group_by(JobRun.job_name)
        .subquery()
    )
    rows = await ctx.db.execute(
        select(JobRun, last_ok.c.ok_at)
        .join(latest, (latest.c.job_name == JobRun.job_name) & (latest.c.started_at == JobRun.started_at))
        .outerjoin(last_ok, last_ok.c.job_name == JobRun.job_name)
        .order_by(JobRun.job_name)
    )
    runs = {run.job_name: (run, ok_at) for run, ok_at in rows}
    since = await ctx.db.scalar(select(func.min(JobRun.started_at)))  # scheduler qachondan beri ishlaydi
    now = utcnow()
    registered: list[tuple[str, int | None, str | None]] = getattr(request.app.state, "scheduled_jobs", [])
    names = [name for name, _, _ in registered] + sorted(set(runs) - {n for n, _, _ in registered})
    schedules = {name: (every, cron) for name, every, cron in registered}
    items: list[JobHealth] = []
    for name in sorted(names):
        every, cron = schedules.get(name, (None, None))
        interval = interval_of(every, cron)
        run, ok_at = runs.get(name, (None, None))
        reference = ok_at or since  # hech muvaffaqiyatli ishlamagan — scheduler ishga tushgandan beri
        overdue = bool(interval and reference and (now - reference).total_seconds() > 3 * interval)
        items.append(
            JobHealth(
                job_name=name,
                schedule=f"every {every}s" if every else cron,
                interval_seconds=interval,
                overdue=overdue,
                alert=bool(run and (run.details or {}).get("alert")),
                last_status=run.status if run else None,
                last_started_at=run.started_at if run else None,
                last_ok_at=ok_at,
                last_error=run.error if run else None,
                last_details=run.details if run else {},
            )
        )
    return JobHealthList(items=items)
