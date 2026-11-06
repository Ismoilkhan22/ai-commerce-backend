"""Kesh backend'lari: matn qiymat + TTL, versiya hisoblagichi (INCR) — ro'yxat kalitlarini birdan eskirtirish
uchun (08 §4.3). Kesh — faqat tezlik: u ishlamasa ham javob DB'dan to'g'ri chiqadi (xato yutiladi, logga).
"""

from __future__ import annotations

import time
from typing import Protocol

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, *keys: str) -> None: ...

    async def incr(self, key: str) -> int:
        """Hisoblagichni oshiradi va yangi qiymatni qaytaradi (yo'q bo'lsa — 1)."""
        ...


class RedisCache:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def get(self, key: str) -> str | None:
        try:
            value = await self.redis.get(key)
        except RedisError as exc:
            logger.warning("cache.unavailable", op="get", error=type(exc).__name__)
            return None
        return value.decode() if isinstance(value, bytes) else value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self.redis.set(key, value, ex=ttl_seconds)
        except RedisError as exc:
            logger.warning("cache.unavailable", op="set", error=type(exc).__name__)

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        try:
            await self.redis.delete(*keys)
        except RedisError as exc:
            logger.warning("cache.unavailable", op="delete", error=type(exc).__name__)

    async def incr(self, key: str) -> int:
        try:
            return int(await self.redis.incr(key))
        except RedisError as exc:
            # Hisoblagich oshmasa eski ro'yxat TTL (60 s) bilan baribir eskiradi
            logger.warning("cache.unavailable", op="incr", error=type(exc).__name__)
            return 0


class MemoryCache:
    """Bitta jarayon uchun. Faqat testlar va lokal ishlab chiqish."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, float | None]] = {}

    def _alive(self, key: str) -> str | None:
        item = self._items.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= time.monotonic():
            del self._items[key]
            return None
        return value

    async def get(self, key: str) -> str | None:
        return self._alive(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._items[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._items.pop(key, None)

    async def incr(self, key: str) -> int:
        current = int(self._alive(key) or 0) + 1
        self._items[key] = (str(current), None)
        return current
