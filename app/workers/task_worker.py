"""task_worker (arq, 06 §4): tinglovchilarni bajaradi va xodim xabarini platforma botiga yuboradi.

    arq app.workers.task_worker.WorkerSettings

Vazifa payload'ida faqat ID'lar — matn va PII yo'q (06 §4.3). Retry: `dispatch_event` 8 marta
(2 s → ~4 daq + jitter), oxiri — dead-letter; `notification_send` 5 marta (FSM-12), oxiri — FAILED.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq import Retry, create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.worker import func

from app.config.settings import Settings, get_settings
from app.platform.notifications.providers import from_state
from app.shared.events.registry import RetryLater
from app.workers.dispatch import MAX_ATTEMPTS, backoff_seconds, deliver
from app.workers.queue import ArqQueue
from app.workers.runtime import WorkerRuntime, build_runtime

NOTIFICATION_MAX_TRIES = 6  # yetkazish 5 urinishdan keyin o'zi FAILED qiladi; arq'da bitta zaxira


def redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings.from_dsn(settings.arq_redis_url)


async def arq_queue(settings: Settings) -> tuple[ArqQueue, ArqRedis]:
    pool = await create_pool(redis_settings(settings))
    return ArqQueue(pool), pool


async def dispatch_event(ctx: dict[str, Any], *, schema: str, event_id: str, consumer: str) -> str:
    rt: WorkerRuntime = ctx["rt"]
    attempt = int(ctx.get("job_try", 1))
    try:
        return await deliver(rt, schema, UUID(event_id), consumer, attempt)
    except RetryLater as exc:
        raise Retry(defer=exc.defer_seconds) from exc
    except Exception as exc:
        raise Retry(defer=backoff_seconds(attempt)) from exc


async def notification_send(ctx: dict[str, Any], *, shop_id: str, notification_id: str) -> str:
    """Rekonsilyatsiya yo'li: tinch soati tugagan yoki navbati yo'qolgan xabar."""
    rt: WorkerRuntime = ctx["rt"]
    try:
        return await from_state(rt.services).delivery.deliver(
            rt.database, UUID(shop_id), UUID(notification_id)
        )
    except RetryLater as exc:
        raise Retry(defer=exc.defer_seconds) from exc


async def startup(ctx: dict[str, Any]) -> None:
    if "rt" in ctx:  # app.workers.dev o'zi beradi
        return
    settings = get_settings()
    from app.config.logging import configure_logging

    configure_logging(settings.log_level, json=settings.app_env != "local")
    ctx["rt"] = build_runtime(settings, ArqQueue(ctx["redis"]))


async def shutdown(ctx: dict[str, Any]) -> None:
    rt: WorkerRuntime | None = ctx.get("rt")
    if rt is not None and not ctx.get("rt_external"):
        await rt.close()


FUNCTIONS = [
    func(dispatch_event, max_tries=MAX_ATTEMPTS, timeout=30),
    func(notification_send, max_tries=NOTIFICATION_MAX_TRIES, timeout=15),
]


class WorkerSettings:
    functions = FUNCTIONS
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(get_settings())
    max_jobs = 20
    keep_result = 60  # takror himoyasi navbatda turgan vazifa uchun; natija kerak emas
