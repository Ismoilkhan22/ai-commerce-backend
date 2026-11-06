"""Kanal adapterlari umumiy kontrakti (13 §1–2): kiruvchi xabar bir xil ko'rinishga keltiriladi, chiquvchi
yuborish natijasi — yagona xato taksonomiyasi bilan.

Inbox, AI va operator kanal farqini bilmaydi: Telegram, Instagram va sayt chati hammasi `InboundMessage`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class InboundAttachment:
    kind: str  # IMAGE | VOICE | FILE | STICKER
    provider_file_ref: str | None
    mime: str | None = None
    size_bytes: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class InboundMessage:
    """Normallashtirilgan kiruvchi hodisa. `provider_event_id` — dedup kaliti (TC-010)."""

    provider_event_id: str
    event_kind: str  # MESSAGE | EDITED | CALLBACK | OTHER
    external_user_id: str
    occurred_at: datetime
    kind: str = "TEXT"  # message_kind
    body: str | None = None
    display_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    contact_phone: str | None = None  # "Raqamni yuborish" — matnga yozilmaydi, identity'ga shifrlangan
    intent_hint: str | None = None  # PURCHASE_INTENT | OPERATOR_REQUEST
    provider_message_id: str | None = None
    attachments: tuple[InboundAttachment, ...] = field(default_factory=tuple)
    ignore_reason: str | None = None  # guruh chati, bot xabari — saqlanmaydi (IGNORED)


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str | None
    parts: int = 1


class ChannelSendError(Exception):
    """Yuborish xatosi (13 §2): `retryable` — 429/5xx/tarmoq; `unknown` — yuborildimi noma'lum (timeout
    javobdan keyin), qayta yuborilmaydi (06 §4.2); qolgani — yakuniy (403 bloklangan, 400)."""

    def __init__(
        self, code: str, *, retryable: bool = False, unknown: bool = False, retry_after: int | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.unknown = unknown
        self.retry_after = retry_after


class ChannelConnectError(Exception):
    """Ulashda xato: token noto'g'ri, webhook o'rnatilmadi, Meta ruxsati yo'q. Matnsiz kod."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
