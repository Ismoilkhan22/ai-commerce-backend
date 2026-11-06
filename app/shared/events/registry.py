"""Event tinglovchilari va rejali ishlar e'loni (05 §6, 06 §5).

Domen `DomainManifest.event_subscribers` / `scheduled_jobs` da e'lon qiladi; `app.workers` ularni
yig'adi va ishga tushiradi.

    @subscriber("storefront.cache_invalidate", "catalog.price.changed", schema="storefront", inline=True)
    async def on_catalog_changed(ctx: EventContext) -> None: ...

**Tranzaksiyali** tinglovchi (standart): `ctx.db` — event shopi konteksti bilan ochilgan tranzaksiya;
`<schema>.consumer_receipts` belgisi va tinglovchi o'zgarishi bitta COMMIT'da (TC-022). Tashqi chaqiruv YO'Q.

**Tranzaksiyasiz** (`transactional=False`): tashqi effekt (Telegram) yoki ko'p shopli ish. `ctx.db` yo'q —
tinglovchi `ctx.database` bilan o'zi tranzaksiya ochadi va idempotentlikni o'z holati bilan ta'minlaydi.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db.session import Database
from app.shared.events.envelope import EventEnvelope


@dataclass(frozen=True)
class EventContext:
    envelope: EventEnvelope
    database: Database
    services: Any  # ilova servislari (app.state) — tinglovchi o'z modulining provider'idan oladi
    db: AsyncSession | None = None  # faqat tranzaksiyali tinglovchida

    @property
    def session(self) -> AsyncSession:
        assert self.db is not None, "tranzaksiyasiz tinglovchida ctx.db yo'q"
        return self.db


Handler = Callable[[EventContext], Awaitable[None]]


class RetryLater(Exception):
    """Vaqtinchalik muammo (tashqi xizmat 5xx/429): ish `defer_seconds` dan keyin qayta bajariladi."""

    def __init__(self, defer_seconds: int) -> None:
        super().__init__(f"retry in {defer_seconds}s")
        self.defer_seconds = defer_seconds


@dataclass(frozen=True)
class Subscriber:
    """`consumer` — o'zgarmas nom: o'zgartirilsa takrordan himoya (consumer_receipts) buziladi."""

    consumer: str
    event_types: frozenset[str]  # aniq tur yoki "commerce.order.*"
    schema: str  # consumer_receipts qaysi schemada (tinglovchining o'z schemasi)
    handler: Handler
    inline: bool = False  # outbox_worker arq'siz, alohida tranzaksiyada chaqiradi (05 §5.1)
    transactional: bool = True

    def matches(self, event_type: str) -> bool:
        for pattern in self.event_types:
            if pattern == event_type or (pattern.endswith(".*") and event_type.startswith(pattern[:-1])):
                return True
        return False


def subscriber(
    consumer: str,
    *event_types: str,
    schema: str,
    inline: bool = False,
    transactional: bool = True,
) -> Callable[[Handler], Subscriber]:
    def wrap(handler: Handler) -> Subscriber:
        return Subscriber(
            consumer=consumer,
            event_types=frozenset(event_types),
            schema=schema,
            handler=handler,
            inline=inline,
            transactional=transactional,
        )

    return wrap


class SubscriberRegistry:
    def __init__(self, subscribers: Sequence[Subscriber]) -> None:
        names = [s.consumer for s in subscribers]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"tinglovchi nomi takrorlangan: {sorted(duplicates)}")
        self.subscribers = tuple(subscribers)
        self._by_name = {s.consumer: s for s in subscribers}

    def for_event(self, event_type: str) -> list[Subscriber]:
        return [s for s in self.subscribers if s.matches(event_type)]

    def get(self, consumer: str) -> Subscriber | None:
        return self._by_name.get(consumer)


# ----------------------------------------------------------------------------------- rejali ishlar
@dataclass(frozen=True)
class JobResult:
    processed: int = 0  # nechta obyekt ko'rildi
    affected: int = 0  # nechta vazifa yaratildi / qator o'chirildi
    details: dict[str, Any] = field(default_factory=dict)  # faqat sonlar va kodlar — PII yo'q


@dataclass(frozen=True)
class JobContext:
    database: Database
    services: Any
    now: datetime


@dataclass(frozen=True)
class ScheduledJob:
    """Jadval: `every_seconds` YOKI `cron` ("30 3 * * *", Asia/Tashkent). Ish holat bo'yicha tanlaydi —
    o'tkazib yuborilgan ishga tushish keyingisida yetib olinadi (06 §6)."""

    name: str
    handler: Callable[[JobContext], Awaitable[JobResult]]
    every_seconds: int | None = None
    cron: str | None = None

    def __post_init__(self) -> None:
        if (self.every_seconds is None) == (self.cron is None):
            raise ValueError(f"{self.name}: every_seconds yoki cron — bittasi")
