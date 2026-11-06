"""sales_ai rejali ishlari (M06 §10, A10). Har shop alohida tranzaksiyada (RLS).

- `sales_ai_stuck_turns` (har 2 daq): 2 daqiqadan beri `RUNNING` (worker o'ldi) yoki 10 daqiqadan beri
  `QUEUED` (event yo'qolgan) navbat → `FAILED`; AI navbatidagi suhbat ikkala holatda ham operatorga
  (`PROVIDER_UNAVAILABLE`, F-11) — xaridor javobsiz qolmaydi.
- `sales_ai_retention` (har kecha): 90 kundan eski tool jurnali; 30 kundan eski kutilayotgan takliflar —
  eskirgan.
- `sales_ai_eval_stalled` (har 5 daq, 6c): 10 daqiqadan beri qadam qo'ymagan baholash yugurishi (event
  yo'qolgan yoki worker o'lgan) → `ERROR` (`STALLED`), shu paytgacha yozilgan natijalar bilan metrikalar.
- `sales_ai_demand_gaps_weekly` (dushanba 09:00, DEC-149): o'tgan haftada "so'rashdi, lekin yo'q" bo'lsa —
  ega va menejerga xabarnoma (faqat soni; hafta bo'yicha dedup).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select, update

from app.domains.sales_ai.common import emit
from app.domains.sales_ai.models.orm import AiToolExecution, AiTurn, EvalRun
from app.domains.sales_ai.providers import from_state
from app.domains.sales_ai.services.demand import demand_gaps
from app.platform.jobs.services.shops import open_shop_ids
from app.platform.notifications.services.notifications import NotificationService
from app.shared.clock import utcnow
from app.shared.events.registry import JobContext, JobResult, ScheduledJob
from app.shared.types.actor import ActorContext

STUCK_RUNNING = timedelta(minutes=2)
STUCK_QUEUED = timedelta(minutes=10)
TOOL_RETENTION = timedelta(days=90)
SUGGESTION_TTL = timedelta(days=30)
EVAL_STALLED = timedelta(minutes=10)
_notifications = NotificationService()


async def stuck_turns(ctx: JobContext) -> JobResult:
    services = from_state(ctx.services)
    affected = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            turns = (
                (
                    await db.execute(
                        select(AiTurn)
                        .where(
                            AiTurn.shop_id == shop_id,
                            ((AiTurn.status == "RUNNING") & (AiTurn.started_at < ctx.now - STUCK_RUNNING))
                            | ((AiTurn.status == "QUEUED") & (AiTurn.created_at < ctx.now - STUCK_QUEUED)),
                        )
                        .with_for_update(skip_locked=True)
                        .limit(100)
                    )
                )
                .scalars()
                .all()
            )
            for turn in turns:
                running = turn.status == "RUNNING"
                turn.status, turn.outcome, turn.finished_at = "FAILED", "ERROR", ctx.now
                turn.error_code = "WORKER_LOST" if running else "NOT_STARTED"
                if turn.mode in ("SUGGEST", "AUTO") and services.conversations is not None:
                    turn.handoff_reason = "PROVIDER_UNAVAILABLE"
                    await services.conversations.request_handoff(
                        db,
                        shop_id,
                        turn.conversation_id,
                        reason="PROVIDER_UNAVAILABLE",
                        speaker_version=turn.speaker_version,
                    )
                await emit(
                    db,
                    shop_id,
                    "sales_ai.turn.completed",
                    turn_id=turn.id,
                    conversation_id=turn.conversation_id,
                    outcome="ERROR",
                    mode=turn.mode,
                    handoff_reason=turn.handoff_reason,
                )
                affected += 1
    return JobResult(affected=affected)


async def retention(ctx: JobContext) -> JobResult:
    deleted = expired = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            result = await db.execute(
                delete(AiToolExecution).where(
                    AiToolExecution.shop_id == shop_id, AiToolExecution.created_at < ctx.now - TOOL_RETENTION
                )
            )
            deleted += int(getattr(result, "rowcount", 0) or 0)
            result = await db.execute(
                update(AiTurn)
                .where(
                    AiTurn.shop_id == shop_id,
                    AiTurn.suggestion_status == "PENDING",
                    AiTurn.created_at < ctx.now - SUGGESTION_TTL,
                )
                .values(suggestion_status="DISCARDED")
            )
            expired += int(getattr(result, "rowcount", 0) or 0)
    return JobResult(
        affected=deleted + expired, details={"tool_rows_deleted": deleted, "suggestions_expired": expired}
    )


async def eval_stalled(ctx: JobContext) -> JobResult:
    services = from_state(ctx.services)
    async with ctx.database.transaction() as db:
        runs = (
            (
                await db.execute(
                    select(EvalRun)
                    .where(
                        EvalRun.status.in_(("QUEUED", "RUNNING")),
                        func.coalesce(EvalRun.heartbeat_at, EvalRun.created_at) < ctx.now - EVAL_STALLED,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        for run in runs:
            run.error_code = "STALLED"
            await services.eval.runner.finish(db, run, "ERROR")
    return JobResult(affected=len(runs))


async def demand_gaps_weekly(ctx: JobContext) -> JobResult:
    notified = 0
    shops = await open_shop_ids(ctx.database)
    week = utcnow().strftime("%G-W%V")
    for shop_id in shops:
        async with ctx.database.transaction(shop_id) as db:
            gaps = await demand_gaps(db, shop_id, 7)
            if not gaps.items:
                continue
            await _notifications.notify_staff(
                db,
                shop_id=shop_id,
                actor=ActorContext.system(shop_id),
                template_key="staff.demand_gaps_weekly",
                aggregate_type="sales_ai.demand_gaps",
                aggregate_id=shop_id,
                aggregate_version=1,
                variables={"count": len(gaps.items)},
                roles=("OWNER", "MANAGER"),
                dedup_scope=f"demand-gaps:{week}",
            )
            notified += 1
    return JobResult(processed=len(shops), affected=notified)


SALES_AI_JOBS = [
    ScheduledJob("sales_ai_stuck_turns", stuck_turns, every_seconds=120),
    ScheduledJob("sales_ai_retention", retention, cron="50 3 * * *"),
    ScheduledJob("sales_ai_eval_stalled", eval_stalled, every_seconds=300),
    ScheduledJob("sales_ai_demand_gaps_weekly", demand_gaps_weekly, cron="0 9 * * 1"),
]
