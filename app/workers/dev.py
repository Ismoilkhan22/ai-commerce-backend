"""Lokal ishlab chiqish: uchala fon jarayoni bitta jarayonda (outbox_worker + task_worker + scheduler);
`TELEGRAM_MODE=polling` (lokalda standart) bo'lsa — shop botlari uchun Telegram polling ham (5b).

    make worker      # = python -m app.workers.dev

Production'da uchalasi alohida konteyner (22 §5): `outbox-worker`, `task-worker`, `scheduler`.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog
from arq.worker import Worker

from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.workers import outbox_worker, scheduler, task_worker, telegram_polling
from app.workers.runtime import build_runtime

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "local")
    queue, pool = await task_worker.arq_queue(settings)
    rt = build_runtime(settings, queue)
    worker = Worker(
        functions=task_worker.FUNCTIONS,
        redis_settings=task_worker.redis_settings(settings),
        ctx={"rt": rt, "rt_external": True},
        on_startup=task_worker.startup,
        on_shutdown=task_worker.shutdown,
        max_jobs=task_worker.WorkerSettings.max_jobs,
        keep_result=task_worker.WorkerSettings.keep_result,
        handle_signals=False,
    )
    tasks = [
        asyncio.create_task(outbox_worker.run_forever(rt), name="outbox"),
        asyncio.create_task(scheduler.run_scheduler(rt), name="scheduler"),
        asyncio.create_task(worker.async_run(), name="task_worker"),
    ]
    if settings.effective_telegram_mode == "polling":
        tasks.append(asyncio.create_task(telegram_polling.run_forever(rt), name="telegram_polling"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logger.info("workers.dev_started")
    try:
        done, _ = await asyncio.wait(
            [*tasks, asyncio.create_task(stop.wait())], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            if (
                task.get_name() in {"outbox", "scheduler", "task_worker", "telegram_polling"}
                and task.exception()
            ):
                logger.error("workers.task_died", task=task.get_name(), error=type(task.exception()).__name__)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await worker.close()
        await rt.close()
        await pool.aclose()
        logger.info("workers.dev_stopped")


if __name__ == "__main__":
    asyncio.run(main())
