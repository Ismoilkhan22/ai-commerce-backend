"""Realtime broker: xodim kanali (a'zolik bo'yicha), tartib raqami va bir martalik WS ticket'lar.

Kanal — har a'zolikka bitta (`cos:v1:rt:m:{membership_id}`): signal faqat ruxsati bor xodimga ketadi,
keng shop kanali yo'q (08 §6.3). Tartib raqami (`seq`) a'zolik bo'yicha Redis'da oshadi: klient bo'shliqni
ko'rsa ro'yxatlarni REST'dan qayta yuklaydi (DEC-139, 3-qaror) — pub/sub xabar yo'qotishi mumkin.

`RedisBroker` — ishlab chiqarish (db2), `MemoryBroker` — testlar va bitta jarayon (iplar orasida xavfsiz).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Protocol
from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)

PREFIX = "cos:v1:rt"
SEQ_TTL_SECONDS = 7 * 24 * 3600  # faol bo'lmagan xodim hisoblagichi o'z-o'zidan o'chadi


def channel_name(membership_id: UUID) -> str:
    return f"{PREFIX}:m:{membership_id}"


def _seq_key(membership_id: UUID) -> str:
    return f"{PREFIX}:seq:{membership_id}"


def _ticket_key(ticket_hash: str) -> str:
    return f"{PREFIX}:ticket:{ticket_hash}"


def _sockets_key(membership_id: UUID) -> str:
    return f"{PREFIX}:sockets:{membership_id}"


# Faol ulanishlar: ZSET (a'zo — ulanish ID'si, ball — oxirgi heartbeat). Eskirgan (jarayon o'lgan) yozuv
# hisobga olinmaydi, shuning uchun ulanish "osilib" qolmaydi. Atomik: limitdan oshsa qo'shilmaydi.
_CLAIM_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


class Subscription(Protocol):
    async def next(self, wait_s: float) -> dict[str, Any] | None:
        """Keyingi signal yoki `wait_s` soniyada hech narsa bo'lmasa None."""
        ...

    async def close(self) -> None: ...


class RealtimeBroker(Protocol):
    async def publish(self, membership_id: UUID, message: dict[str, Any]) -> int:
        """Signalni yuboradi va unga berilgan tartib raqamini qaytaradi (0 — Redis ishlamadi)."""
        ...

    async def current_seq(self, membership_id: UUID) -> int: ...

    async def subscribe(self, membership_id: UUID) -> Subscription: ...

    async def put_ticket(self, ticket_hash: str, data: dict[str, str], ttl_seconds: int) -> None: ...

    async def take_ticket(self, ticket_hash: str) -> dict[str, str] | None:
        """Bir martalik: olinadi va o'chiriladi (GETDEL)."""
        ...

    async def claim_socket(
        self, membership_id: UUID, conn_id: str, *, now: float, stale_after: float, limit: int
    ) -> bool:
        """Ulanish joyi: xodimda `limit` dan kam faol ulanish bo'lsa — True (QA 5a F11)."""
        ...

    async def touch_socket(self, membership_id: UUID, conn_id: str, *, now: float) -> None: ...

    async def release_socket(self, membership_id: UUID, conn_id: str) -> None: ...


# ------------------------------------------------------------------------------------------- Redis
class _RedisSubscription:
    def __init__(self, pubsub: PubSub) -> None:
        self.pubsub = pubsub

    async def next(self, wait_s: float) -> dict[str, Any] | None:
        message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=wait_s)
        if message is None or message.get("type") != "message":
            return None
        data = message["data"]
        result: dict[str, Any] = json.loads(data.decode() if isinstance(data, bytes) else data)
        return result

    async def close(self) -> None:
        try:
            await self.pubsub.unsubscribe()
            await self.pubsub.aclose()  # type: ignore[no-untyped-call]
        except RedisError as exc:
            logger.warning("realtime.unsubscribe_failed", error=type(exc).__name__)


class RedisBroker:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, membership_id: UUID, message: dict[str, Any]) -> int:
        try:
            seq = int(await self.redis.incr(_seq_key(membership_id)))
            await self.redis.expire(_seq_key(membership_id), SEQ_TTL_SECONDS)
            await self.redis.publish(channel_name(membership_id), json.dumps({**message, "seq": seq}))
        except RedisError as exc:
            # Signal yo'qolsa ham ma'lumot yo'qolmaydi: klient qayta ulanganda REST'dan yuklaydi
            logger.warning("realtime.publish_failed", error=type(exc).__name__)
            return 0
        return seq

    async def current_seq(self, membership_id: UUID) -> int:
        try:
            return int(await self.redis.get(_seq_key(membership_id)) or 0)
        except RedisError:
            return 0

    async def subscribe(self, membership_id: UUID) -> Subscription:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel_name(membership_id))
        return _RedisSubscription(pubsub)

    async def put_ticket(self, ticket_hash: str, data: dict[str, str], ttl_seconds: int) -> None:
        await self.redis.set(_ticket_key(ticket_hash), json.dumps(data), ex=ttl_seconds)

    async def take_ticket(self, ticket_hash: str) -> dict[str, str] | None:
        raw = await self.redis.getdel(_ticket_key(ticket_hash))
        if raw is None:
            return None
        result: dict[str, str] = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return result

    async def claim_socket(
        self, membership_id: UUID, conn_id: str, *, now: float, stale_after: float, limit: int
    ) -> bool:
        claimed = await self.redis.eval(  # type: ignore[misc]
            _CLAIM_SCRIPT,
            1,
            _sockets_key(membership_id),
            str(now - stale_after),
            str(now),
            str(limit),
            conn_id,
            str(int(stale_after) + 60),
        )
        return bool(claimed)

    async def touch_socket(self, membership_id: UUID, conn_id: str, *, now: float) -> None:
        try:
            await self.redis.zadd(_sockets_key(membership_id), {conn_id: now}, xx=True)
        except RedisError as exc:
            logger.warning("realtime.touch_failed", error=type(exc).__name__)

    async def release_socket(self, membership_id: UUID, conn_id: str) -> None:
        try:
            await self.redis.zrem(_sockets_key(membership_id), conn_id)
        except RedisError as exc:
            logger.warning("realtime.release_failed", error=type(exc).__name__)


# ------------------------------------------------------------------------------------------ xotira
class _MemorySubscription:
    def __init__(self, broker: MemoryBroker, membership_id: UUID) -> None:
        self.broker = broker
        self.membership_id = membership_id
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def deliver(self, message: dict[str, Any]) -> None:
        # publish boshqa ipdan (test, worker) chaqirilishi mumkin — navbatga o'z loop'i orqali
        self.loop.call_soon_threadsafe(self.queue.put_nowait, message)

    async def next(self, wait_s: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self.queue.get(), wait_s)
        except TimeoutError:
            return None

    async def close(self) -> None:
        self.broker._unsubscribe(self)


class MemoryBroker:
    """Bitta jarayon uchun (testlar, Redis'siz lokal ishga tushirish)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq: dict[UUID, int] = {}
        self._subs: dict[UUID, list[_MemorySubscription]] = {}
        self._tickets: dict[str, tuple[dict[str, str], float]] = {}
        self._sockets: dict[UUID, dict[str, float]] = {}

    async def publish(self, membership_id: UUID, message: dict[str, Any]) -> int:
        with self._lock:
            seq = self._seq.get(membership_id, 0) + 1
            self._seq[membership_id] = seq
            targets = list(self._subs.get(membership_id, ()))
        for sub in targets:
            sub.deliver({**message, "seq": seq})
        return seq

    async def current_seq(self, membership_id: UUID) -> int:
        with self._lock:
            return self._seq.get(membership_id, 0)

    async def subscribe(self, membership_id: UUID) -> Subscription:
        sub = _MemorySubscription(self, membership_id)
        with self._lock:
            self._subs.setdefault(membership_id, []).append(sub)
        return sub

    def _unsubscribe(self, sub: _MemorySubscription) -> None:
        with self._lock:
            subs = self._subs.get(sub.membership_id, [])
            if sub in subs:
                subs.remove(sub)

    async def put_ticket(self, ticket_hash: str, data: dict[str, str], ttl_seconds: int) -> None:
        with self._lock:
            self._tickets[ticket_hash] = (data, time.monotonic() + ttl_seconds)

    async def take_ticket(self, ticket_hash: str) -> dict[str, str] | None:
        with self._lock:
            item = self._tickets.pop(ticket_hash, None)
        if item is None or item[1] <= time.monotonic():
            return None
        return item[0]

    async def claim_socket(
        self, membership_id: UUID, conn_id: str, *, now: float, stale_after: float, limit: int
    ) -> bool:
        with self._lock:
            live = {c: t for c, t in self._sockets.get(membership_id, {}).items() if t > now - stale_after}
            if len(live) >= limit:
                self._sockets[membership_id] = live
                return False
            live[conn_id] = now
            self._sockets[membership_id] = live
            return True

    async def touch_socket(self, membership_id: UUID, conn_id: str, *, now: float) -> None:
        with self._lock:
            sockets = self._sockets.get(membership_id, {})
            if conn_id in sockets:
                sockets[conn_id] = now

    async def release_socket(self, membership_id: UUID, conn_id: str) -> None:
        with self._lock:
            self._sockets.get(membership_id, {}).pop(conn_id, None)
