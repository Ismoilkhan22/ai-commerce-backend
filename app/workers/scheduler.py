"""scheduler (06 §5): bitta leader (PostgreSQL advisory lock), APScheduler, har ish `job:<nom>` qulfi bilan.

APScheduler tanlandi (arq cron emas): leader va jadval Redis'ga bog'liq emas — Redis o'chsa ham eslatma
vazifalari bazada yaratiladi; arq cron esa task_worker ichida va Redis bilan ishlaydi (06 §2).

Qulf ulanishi AUTOCOMMIT'da: ochiq tranzaksiya `idle_in_transaction_session_timeout` (10 s) bilan uzilardi.
Leader ulanishi uzilsa PostgreSQL qulfni o'zi bo'shatadi — boshqa nusxa 10 s ichida leader bo'ladi.

    python -m app.workers.scheduler
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.platform.jobs.models.orm import JobRun
from app.shared.clock import utcnow
from app.shared.db.ids import uuid7
from app.shared.events.registry import JobContext, JobResult, ScheduledJob
from app.workers.dispatch import error_code
from app.workers.runtime import WorkerRuntime

logger = structlog.get_logger(__name__)

TIMEZONE = ZoneInfo("Asia/Tashkent")
LEADER_LOCK = "scheduler_leader"
LEADER_RETRY_S = 10
KEEPALIVE_S = 30


async def _try_lock(conn: AsyncConnection, name: str) -> bool:
    return bool(await conn.scalar(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": name}))


async def _unlock(conn: AsyncConnection, name: str) -> None:
    await conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": name})


async def _record(rt: WorkerRuntime, values: dict[str, Any], run_id: Any = None) -> Any:
    async with rt.database.transaction() as db:
        if run_id is None:
            run_id = uuid7()
            await db.execute(insert(JobRun).values(id=run_id, **values))
        else:
            await db.execute(update(JobRun).where(JobRun.id == run_id).values(**values))
    return run_id


async def run_job(rt: WorkerRuntime, job: ScheduledJob) -> JobResult | None:
    """Ishni bir marta bajaradi va `platform.job_runs` ga yozadi. Boshqa nusxa ishlatayotgan bo'lsa —
    SKIPPED."""
    lock = f"job:{job.name}"
    started = utcnow()
    async with rt.database.write_engine.connect() as raw:
        conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
        if not await _try_lock(conn, lock):
            await _record(
                rt, {"job_name": job.name, "status": "SKIPPED", "started_at": started, "finished_at": started}
            )
            return None
        try:
            run_id = await _record(rt, {"job_name": job.name, "status": "RUNNING", "started_at": started})
            try:
                result = await job.handler(JobContext(rt.database, rt.services, started))
            except Exception as exc:
                await _record(
                    rt, {"status": "FAILED", "finished_at": utcnow(), "error": error_code(exc)}, run_id
                )
                logger.exception("scheduler.job_failed", job=job.name)
                return None
            await _record(
                rt,
                {
                    "status": "OK",
                    "finished_at": utcnow(),
                    "processed": result.processed,
                    "affected": result.affected,
                    "details": result.details,
                },
                run_id,
            )
            return result
        finally:
            await _unlock(conn, lock)


def _trigger(job: ScheduledJob) -> IntervalTrigger | CronTrigger:
    if job.every_seconds is not None:
        return IntervalTrigger(seconds=job.every_seconds, timezone=TIMEZONE)
    assert job.cron is not None
    return CronTrigger.from_crontab(job.cron, timezone=TIMEZONE)


def build_scheduler(rt: WorkerRuntime) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    for job in rt.jobs:
        scheduler.add_job(
            run_job,
            _trigger(job),
            args=[rt, job],
            id=job.name,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
            # Oraliqli ishlar ishga tushishi bilan bir marta (holat bo'yicha — o'tkazib yuborilganlar
            # yetib olinadi)
            next_run_time=datetime.now(TIMEZONE) if job.every_seconds is not None else None,
        )
    return scheduler


async def run_scheduler(rt: WorkerRuntime) -> None:
    async with rt.database.write_engine.connect() as raw:
        conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
        while not await _try_lock(conn, LEADER_LOCK):  # noqa: ASYNC110 — qulf bazada, Event bilan emas
            await asyncio.sleep(LEADER_RETRY_S)  # boshqa nusxa leader
        logger.info("scheduler.leader", jobs=[j.name for j in rt.jobs])
        scheduler = build_scheduler(rt)
        scheduler.start()
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_S)
                await conn.execute(text("SELECT 1"))  # ulanish uzilsa — xato, jarayon qayta ishga tushadi
        finally:
            scheduler.shutdown(wait=False)


async def _main() -> None:
    from app.config.logging import configure_logging
    from app.config.settings import get_settings
    from app.workers.runtime import build_runtime
    from app.workers.task_worker import arq_queue

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "local")
    queue, pool = await arq_queue(settings)
    rt = build_runtime(settings, queue)
    try:
        await run_scheduler(rt)
    finally:
        await rt.close()
        await pool.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
