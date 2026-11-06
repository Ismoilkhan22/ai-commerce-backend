"""Fon jarayoni: alohida pool, scheduler ishlar chegarasi va birinchi ishga tushish jitteri."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.config.settings import Settings
from app.shared.events.registry import JobResult, ScheduledJob
from app.workers import scheduler


def _job(every: int) -> ScheduledJob:
    async def handler(ctx: Any) -> JobResult:
        return JobResult(processed=0, affected=0)

    return ScheduledJob(name="x", handler=handler, every_seconds=every)


def test_worker_pool_is_separate_and_larger() -> None:
    settings = Settings()
    api, worker = settings.database_config(), settings.database_config(worker=True)
    assert (api.pool_size, api.max_overflow) == (settings.db_pool_size, settings.db_max_overflow)
    assert worker.pool_size == settings.worker_db_pool_size >= 20
    assert worker.pool_size > api.pool_size


def test_first_run_offset_is_bounded_by_interval_and_jitter() -> None:
    rng = random.Random(1)  # noqa: S311 — test, kriptografiya emas
    for _ in range(100):
        assert 0 <= scheduler.first_run_offset(_job(5), rng) <= 5
        assert 0 <= scheduler.first_run_offset(_job(3600), rng) <= scheduler.STARTUP_JITTER_S


async def test_run_job_gate_limits_concurrency(monkeypatch: Any) -> None:
    active = peak = 0

    async def fake(rt: Any, job: ScheduledJob) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setattr(scheduler, "_run_job", fake)
    gate = asyncio.Semaphore(scheduler.MAX_CONCURRENT_JOBS)
    await asyncio.gather(*(scheduler.run_job(None, _job(5), gate) for _ in range(20)))  # type: ignore[arg-type]
    assert peak == scheduler.MAX_CONCURRENT_JOBS
