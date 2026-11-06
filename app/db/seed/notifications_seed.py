"""Lokal demo: xodim vazifalari va xabarnomalari (5a).

Alohida "soxta" qatorlar yozilmaydi — haqiqiy rejali ishlar bir marta ishga tushiriladi: savdo demosidagi
24 soat tasdiqlanmagan va 72 soat olib ketilmagan buyurtmalar, KompyuterPro'ning eskirgan kursi vazifa va
xabarnomaga aylanadi. Ishlar `dedup_key` bilan — qayta seed yangi qator yaratmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.workers.queue import RecordingQueue
from app.workers.runtime import build_runtime
from app.workers.scheduler import run_job

SEED_JOBS = ("order_confirm_reminder", "reservation_review", "exchange_rate_staleness", "stock_reconcile")


@dataclass
class NotificationsSeedReport:
    tasks: int = 0


async def run_notifications_seed(settings: Settings) -> NotificationsSeedReport:
    report = NotificationsSeedReport()
    rt = build_runtime(settings, RecordingQueue())
    try:
        jobs = {job.name: job for job in rt.jobs}
        for name in SEED_JOBS:
            result = await run_job(rt, jobs[name])
            if result is not None and name != "stock_reconcile":
                report.tasks += result.affected
    finally:
        await rt.close()
    return report
