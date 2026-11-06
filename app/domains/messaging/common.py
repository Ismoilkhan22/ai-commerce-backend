"""messaging umumiy yordamchilari: sozlama, event yozish, operator doirasi, ish vaqti, telefon."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.instagram import FakeInstagramClient, HttpInstagramClient, InstagramClient
from app.domains.messaging.channels.telegram import FakeTelegramClient, HttpTelegramClient, TelegramClient
from app.domains.messaging.models.orm import Conversation
from app.shared.errors.base import ForbiddenError, NotFoundError, ValidationError
from app.shared.events.outbox import write_outbox
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

SCHEMA = "messaging"
CONVERSATION = "messaging.conversation"
MESSAGE = "messaging.message"
CHANNEL = "messaging.channel"
SUPERVISOR_ROLES = frozenset({"OWNER", "MANAGER"})
CHANNEL_LABELS = {"TELEGRAM": "Telegram", "INSTAGRAM": "Instagram", "WEB_CHAT": "Sayt chati"}
SENDABLE_CHANNEL_STATUSES = frozenset({"CONNECTED", "DEGRADED"})
MAX_SEND_ATTEMPTS = 5  # 13 §4: 5 urinishdan keyin FAILED (TC-011)


@dataclass(frozen=True)
class MessagingConfig:
    webhook_base_url: str  # https://api.platforma.uz — Telegram webhook manzili shundan
    telegram_mode: str  # "webhook" (prod) | "polling" (lokal, ochiq manzil yo'q)
    instagram_enabled: bool = False  # DEC-116a: channel.instagram_dm flag
    instagram_app_secret: str | None = None
    instagram_verify_token: str | None = None
    storefront_public_url: str = ""  # "https://{slug}.platforma.uz" — izohga javobdagi mahsulot havolasi
    # Faqat local/test: `TEST_TELEGRAM_TOKEN` ko'rinishidagi token — soxta bot (tarmoqsiz), e2e va demo uchun
    telegram_test_tokens: bool = False


# Test bot tokeni (faqat APP_ENV=local|test): 9 raqam, so'ng "TEST" va kamida 26 belgi. Format haqiqiy token
# shakliga mos (frontend tekshiruvi o'tadi), lekin `getMe` chaqirilmaydi — akkaunt `settings.fake` bilan.
TEST_TELEGRAM_TOKEN = re.compile(r"^(?P<bot>[0-9]{9}):TEST[A-Za-z0-9_-]{26,60}$")


@dataclass
class ChannelAdapters:
    """Tashqi kanal klientlari. Testlar soxtasini qo'yadi: `app.state.messaging.adapters.telegram = Fake…`."""

    telegram: TelegramClient = field(default_factory=HttpTelegramClient)
    instagram: InstagramClient = field(default_factory=HttpInstagramClient)


def fake_adapters() -> ChannelAdapters:
    return ChannelAdapters(telegram=FakeTelegramClient(), instagram=FakeInstagramClient())


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def channel_label(channel: str) -> str:
    return CHANNEL_LABELS.get(channel, channel)


def is_supervisor(actor: ActorContext) -> bool:
    return bool(actor.roles & SUPERVISOR_ROLES)


def ensure_scope(actor: ActorContext, conversation: Conversation) -> None:
    """Operator (SALES) — faqat o'ziga biriktirilgan va biriktirilmagan navbat (10 §6.8 own): o'qish ham,
    yozish ham. Ega va menejer — hammasi."""
    if is_supervisor(actor):
        return
    if conversation.assignee_membership_id not in (None, actor.membership_id):
        raise ForbiddenError("Conversation is assigned to another operator", reason="other_operator")


def not_found() -> NotFoundError:
    return NotFoundError("Conversation not found")


def customer_phone(raw: str | None) -> str | None:
    """Kanal bergan raqam: O'zbekiston raqami — kanonik (+998…); boshqa davlat — +raqamlar (7–15 ta)."""
    if not raw:
        return None
    try:
        return normalize_phone(raw)
    except ValidationError:  # chet el raqami: O'zbekiston formatiga tushmaydi
        digits = re.sub(r"[^0-9]", "", raw)
        return f"+{digits}" if 7 <= len(digits) <= 15 else None


def mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) < 7:
        return None
    return f"{phone[:6]} *** ** {phone[-2:]}"


async def emit(
    db: AsyncSession,
    actor: ActorContext,
    *,
    event_type: str,
    shop_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    payload: dict[str, Any],
) -> None:
    """messaging event'i (05 §8.3) — biznes o'zgarishi bilan bitta tranzaksiyada. Matn va telefon YO'Q."""
    await db.flush()
    await write_outbox(
        db,
        schema=SCHEMA,
        event_type=event_type,
        actor=actor,
        shop_id=shop_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        payload=payload,
    )


def conversation_payload(conversation: Conversation, **extra: Any) -> dict[str, Any]:
    return {
        "conversation_id": conversation.id,
        "channel": conversation.channel,
        "status": conversation.status,
        "speaker_mode": conversation.speaker_mode,
        "speaker_version": conversation.speaker_version,
        "assignee_membership_id": conversation.assignee_membership_id,
        **extra,
    }


# ------------------------------------------------------------------ ish vaqti (shop_policies.inbox_hours)
def _clock(value: Any) -> time | None:
    if not isinstance(value, str) or not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", value):
        return None
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def within_inbox_hours(inbox_hours: dict[str, Any] | None, timezone: str, now: datetime) -> bool:
    """`{"days": [1..7], "start": "09:00", "end": "19:00"}` (shop vaqt mintaqasida). Bo'sh yoki buzilgan —
    doim ish vaqti (eslatma kechikmaydi). `end < start` — tungi smena (start..24:00 va 00:00..end)."""
    if not inbox_hours:
        return True
    start, end = _clock(inbox_hours.get("start")), _clock(inbox_hours.get("end"))
    days = inbox_hours.get("days")
    if start is None or end is None or start == end or not isinstance(days, list) or not days:
        return True  # buzilgan yoki bo'sh oraliq (eski yozuv) — "doim yopiq" emas, doim ish vaqti
    try:
        local = now.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        local = now.astimezone(ZoneInfo("Asia/Tashkent"))
    current = local.time().replace(second=0, microsecond=0)
    if start <= end:
        return local.isoweekday() in days and start <= current < end
    if current >= start:
        return local.isoweekday() in days
    previous_day = 7 if local.isoweekday() == 1 else local.isoweekday() - 1
    return previous_day in days and current < end


def hours_label(inbox_hours: dict[str, Any] | None) -> str:
    if not inbox_hours:
        return ""
    return f"{inbox_hours.get('start', '')}–{inbox_hours.get('end', '')}"
