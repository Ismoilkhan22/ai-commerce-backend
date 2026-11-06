"""Fon jarayonlari holati: baza, servislar (API bilan bir xil), tinglovchilar va rejali ishlar ro'yxati.

Composition root: domenlar va platform modullarini manifest'lar orqali yig'adi (02 §2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from starlette.datastructures import State

from app.config.settings import Settings
from app.shared.cache import Cache, MemoryCache, RedisCache
from app.shared.db.encryption import configure_pii
from app.shared.db.session import Database
from app.shared.events.registry import ScheduledJob, SubscriberRegistry
from app.shared.idempotency.helpers import configure_request_hash_key
from app.shared.realtime import MemoryBroker, RealtimeBroker, RedisBroker
from app.shared.types.manifest import DomainManifest
from app.workers.queue import TaskQueue


@dataclass
class WorkerRuntime:
    settings: Settings
    database: Database
    services: Any  # app.state bilan bir xil: catalog, commerce, storefront, notifications, cache, realtime
    registry: SubscriberRegistry
    jobs: Sequence[ScheduledJob]
    queue: TaskQueue
    _closers: list[Any] = field(default_factory=list)

    async def close(self) -> None:
        for closer in self._closers:
            await closer()
        await self.database.dispose()


def collect(manifests: Sequence[DomainManifest]) -> tuple[SubscriberRegistry, list[ScheduledJob]]:
    from app.workers.reconcile import WORKER_JOBS

    registry = SubscriberRegistry([s for m in manifests for s in m.event_subscribers])
    jobs = [j for m in manifests for j in m.scheduled_jobs] + list(WORKER_JOBS)
    return registry, jobs


def build_runtime(
    settings: Settings,
    queue: TaskQueue,
    *,
    manifests: Sequence[DomainManifest] | None = None,
    services: Any = None,
    database: Database | None = None,
) -> WorkerRuntime:
    """`services` berilsa (testlar: TestClient ilovasining app.state'i) — o'shalar ishlatiladi; aks holda
    API bilan bir xil yig'iladi (Redis kesh va realtime — sozlama bo'yicha)."""
    from app.main import discover_manifests, wire_services

    manifests = discover_manifests() if manifests is None else manifests
    configure_pii(settings.pii_keyring())
    configure_request_hash_key(settings.idempotency_hash_key.get_secret_value().encode())
    closers: list[Any] = []
    if services is None:
        services = State()
        cache: Cache
        realtime: RealtimeBroker
        if settings.rate_limit_backend == "redis":
            cache_redis = Redis.from_url(settings.redis_url)
            rt_redis = Redis.from_url(settings.realtime_redis_url)
            cache, realtime = RedisCache(cache_redis), RedisBroker(rt_redis)
            closers += [cache_redis.aclose, rt_redis.aclose]
        else:
            cache, realtime = MemoryCache(), MemoryBroker()
        wire_services(services, settings, manifests, cache, realtime)
    registry, jobs = collect(manifests)
    runtime = WorkerRuntime(
        settings=settings,
        database=database or Database(settings.database_config()),
        services=services,
        registry=registry,
        jobs=jobs,
        queue=queue,
        _closers=closers,
    )
    services.worker_runtime = (
        runtime  # rekonsilyatsiya ishi tinglovchilar ro'yxati va navbatni shu yerdan oladi
    )
    return runtime
