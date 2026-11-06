"""So'rovlar sonini cheklash (10 §5.2): login 10/daq IP+login bo'yicha va h.k.

Redis (ishlab chiqarish) yoki xotira (testlar, lokal) — bitta interfeys. Qat'iy oyna (fixed window):
sodda va yetarli; limit oshsa 429 RATE_LIMITED + Retry-After.
"""

from __future__ import annotations

import time
from typing import Protocol

from redis.asyncio import Redis

from app.shared.errors.base import RateLimitedError


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> int:
        """Hisoblagichni oshiradi; limit oshgan bo'lsa — kutish soniyalari, aks holda 0."""
        ...


class RedisRateLimiter:
    """`scale` — limitlar ko'paytmasi (faqat local/test, `RATE_LIMIT_SCALE`)."""

    def __init__(self, redis: Redis, scale: int = 1) -> None:
        self.redis = redis
        self._scale = scale

    async def hit(self, key: str, limit: int, window_seconds: int) -> int:
        window = int(time.time() // window_seconds)
        redis_key = f"cos:v1:ratelimit:{key}:{window}"
        count = await self.redis.incr(redis_key)
        if count == 1:
            await self.redis.expire(redis_key, window_seconds)
        if count > limit * self._scale:
            return window_seconds - int(time.time() % window_seconds)
        return 0


class MemoryRateLimiter:
    """Bitta jarayon uchun. Faqat testlar va lokal ishlab chiqish. `scale` — `RedisRateLimiter` dagidek."""

    def __init__(self, scale: int = 1) -> None:
        self._counts: dict[str, int] = {}
        self._scale = scale

    async def hit(self, key: str, limit: int, window_seconds: int) -> int:
        window = int(time.time() // window_seconds)
        bucket = f"{key}:{window}"
        self._counts[bucket] = self._counts.get(bucket, 0) + 1
        if self._counts[bucket] > limit * self._scale:
            return window_seconds - int(time.time() % window_seconds)
        return 0


async def enforce(limiter: RateLimiter, key: str, limit: int, window_seconds: int = 60) -> None:
    retry_after = await limiter.hit(key, limit, window_seconds)
    if retry_after:
        raise RateLimitedError("Too many requests", retry_after_seconds=retry_after)
