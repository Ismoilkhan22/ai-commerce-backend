"""messaging schemasi (db/messaging.dbml, DEC-137): kanallar, xaridorlar, suhbatlar, xabarlar,
operatorga uzatish.

Shop faqat server tomonida aniqlanadi: webhook'da `account_ref` → `channel_accounts`, sayt chatida `slug`.
Xaridor telefoni va kanal tokeni — ustun darajasida shifrlangan (`EncryptedString`, 26 §4); webhook siri va
sayt chati tokeni — faqat SHA-256 xeshi. Xabar matni — at rest (disk), RLS va 12 oylik saqlash (2-qaror).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.encryption import EncryptedString
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

SCHEMA = "messaging"
CHANNELS = ("TELEGRAM", "INSTAGRAM", "WEB_CHAT")
CHANNEL_STATUSES = ("PENDING", "CONNECTED", "DEGRADED", "DISCONNECTED")
PROVIDER_EVENT_KINDS = ("MESSAGE", "EDITED", "CALLBACK", "DELIVERY", "COMMENT", "OTHER")
PROVIDER_EVENT_STATUSES = ("PROCESSED", "IGNORED", "FAILED")
CONVERSATION_STATUSES = (
    "NEW",
    "AI_ACTIVE",
    "WAITING_CUSTOMER",
    "HUMAN_NEEDED",
    "HUMAN_ACTIVE",
    "RESOLVED",
    "REOPENED",
)
SPEAKER_MODES = ("AI", "HUMAN", "PAUSED")
DIRECTIONS = ("IN", "OUT")
AUTHOR_TYPES = ("CUSTOMER", "AI", "STAFF", "SYSTEM")
MESSAGE_KINDS = ("TEXT", "IMAGE", "VOICE", "FILE", "CONTACT", "LOCATION", "STICKER", "UNSUPPORTED")
MESSAGE_ORIGINS = ("CUSTOMER", "AI_AUTO", "AI_APPROVED", "STAFF", "NOTIFICATION", "GREETING")
DELIVERY_STATUSES = ("RECEIVED", "QUEUED", "SENDING", "SENT", "FAILED", "UNKNOWN", "DISCARDED")
ATTACHMENT_STATUSES = ("PENDING", "STORED", "FAILED", "PURGED")
HANDOFF_REASONS = (
    "CUSTOMER_REQUEST",
    "PURCHASE_INTENT",
    "AI_LOW_CONFIDENCE",
    "COMPLAINT",
    "PAYMENT",
    "WARRANTY",
    "DISCOUNT",
    "AI_UNAVAILABLE",
    "AI_STALE",
    "VALIDATION_FAILED",
    "WINDOW_CLOSED",
    "STAFF_TAKEOVER",
    "OTHER",
)
HANDOFF_STATUSES = ("OPEN", "TAKEN", "CANCELLED")
REQUESTER_TYPES = ("AI", "STAFF", "SYSTEM", "CUSTOMER")


def _fk(columns: list[str], table: str, *, name: str | None = None, ondelete: str = "RESTRICT") -> Any:
    return ForeignKeyConstraint(
        columns,
        [f"{SCHEMA}.{table}.{c}" for c in ("shop_id", "id")],
        name=name,
        ondelete=ondelete,
    )


class ChannelAccount(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Ulangan kanal (FSM-03). Webhook kelganda shop shu jadvaldan topiladi (13 §3). Token — shifrlangan,
    API javobida hech qachon qaytmaydi. RLS: shop konteksti YOKI `app.channel_account_ref` (12-qaror)."""

    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("account_ref"),
        # Bitta bot bir vaqtda faqat bitta shopda; shopda har kanal turidan bitta faol akkaunt (7-qaror)
        Index(
            "uq_channel_accounts_active_external",
            "channel",
            "external_account_id",
            unique=True,
            postgresql_where=text("status <> 'DISCONNECTED' AND external_account_id IS NOT NULL"),
        ),
        Index(
            "uq_channel_accounts_active_channel",
            "shop_id",
            "channel",
            unique=True,
            postgresql_where=text("status <> 'DISCONNECTED'"),
        ),
        CheckConstraint(f"channel IN {CHANNELS}", name="channel"),
        CheckConstraint(f"status IN {CHANNEL_STATUSES}", name="status"),
        CheckConstraint("char_length(account_ref) >= 32", name="account_ref_length"),
        {"schema": SCHEMA},
    )

    channel: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    account_ref: Mapped[str] = mapped_column(Text)
    external_account_id: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    token_enc: Mapped[str | None] = mapped_column(EncryptedString)
    webhook_secret_hash: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    connected_by: Mapped[UUID | None]  # platform.memberships.id — faqat ega
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnect_reason: Mapped[str | None] = mapped_column(
        Text
    )  # OWNER | AUTH_REVOKED | REPLACED | SHOP_CLOSED


class ProviderEvent(IdMixin, ShopScopedMixin, Base):
    """Webhook takroridan himoya (TC-010). Xom payload SAQLANMAYDI (5-qaror) — 30 kun."""

    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "channel_account_id", "provider_event_id", name="uq_provider_events_dedup"
        ),
        Index("ix_provider_events_received_at", "received_at"),
        _fk(["shop_id", "channel_account_id"], "channel_accounts"),
        ForeignKeyConstraint(
            ["shop_id", "message_id"],
            [f"{SCHEMA}.messages.shop_id", f"{SCHEMA}.messages.id"],
            name="fk_provider_events_message",
        ),
        CheckConstraint(f"kind IN {PROVIDER_EVENT_KINDS}", name="kind"),
        CheckConstraint(f"status IN {PROVIDER_EVENT_STATUSES}", name="status"),
        {"schema": SCHEMA},
    )

    channel_account_id: Mapped[UUID]
    provider_event_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    message_id: Mapped[UUID | None]
    error_code: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerIdentity(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Xaridorning kanaldagi shaxsi. Shoplararo hech qachon birlashtirilmaydi (BL-042)."""

    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "channel", "external_user_id"),
        Index("ix_customer_identities_shop_id_phone_hmac", "shop_id", "phone_hmac"),
        CheckConstraint(f"channel IN {CHANNELS}", name="channel"),
        CheckConstraint("locale IS NULL OR locale IN ('uz', 'ru', 'en')", name="locale"),
        {"schema": SCHEMA},
    )

    channel: Mapped[str] = mapped_column(Text)
    external_user_id: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(Text)
    phone_enc: Mapped[str | None] = mapped_column(EncryptedString)
    phone_hmac: Mapped[str | None] = mapped_column(Text)
    contact_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notice_version: Mapped[str | None] = mapped_column(Text)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Xaridor bilan yozishma (FSM-04). Hozir kim javob beradi — `speaker_mode` + `speaker_version` (12 §8).
    Bir xaridor — bitta suhbat; yopilgani qayta ochiladi (3-qaror)."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "customer_identity_id"),
        Index("ix_conversations_inbox", "shop_id", "last_message_at", "id"),
        Index("ix_conversations_status", "shop_id", "status", "last_message_at"),
        Index("ix_conversations_assignee", "shop_id", "assignee_membership_id", "status"),
        Index("ix_conversations_waiting", "waiting_since", postgresql_where=text("status = 'HUMAN_NEEDED'")),
        _fk(
            ["shop_id", "customer_identity_id"],
            "customer_identities",
            name="fk_conversations_customer_identity",
        ),
        _fk(["shop_id", "channel_account_id"], "channel_accounts"),
        CheckConstraint(f"channel IN {CHANNELS}", name="channel"),
        CheckConstraint(f"status IN {CONVERSATION_STATUSES}", name="status"),
        CheckConstraint(f"speaker_mode IN {SPEAKER_MODES}", name="speaker_mode"),
        CheckConstraint("speaker_version > 0", name="speaker_version_positive"),
        CheckConstraint("staff_last_read_seq <= message_seq", name="read_seq"),
        {"schema": SCHEMA},
    )

    customer_identity_id: Mapped[UUID]
    channel_account_id: Mapped[UUID]
    channel: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="NEW")
    speaker_mode: Mapped[str] = mapped_column(Text, server_default="AI")
    speaker_version: Mapped[int] = mapped_column(BigInteger, server_default="1")
    assignee_membership_id: Mapped[UUID | None]  # platform.memberships.id
    locale: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    message_seq: Mapped[int] = mapped_column(BigInteger, server_default="0")
    staff_last_read_seq: Mapped[int] = mapped_column(BigInteger, server_default="0")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_staff_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_order_id: Mapped[UUID | None]  # commerce.orders.id — FK'siz
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None]


class Message(IdMixin, ShopScopedMixin, Base):
    """Kiruvchi va chiquvchi xabar bitta jadvalda (1-qaror). Chiquvchi avval QUEUED + outbox → `channel_send`;
    xato yo'qolmaydi: FAILED/UNKNOWN inbox'da ko'rinadi (TC-011)."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "conversation_id", "seq"),
        Index(
            "uq_messages_intent",
            "shop_id",
            "intent_key",
            unique=True,
            postgresql_where=text("intent_key IS NOT NULL"),
        ),
        # Bir suhbatda bir vaqtda bitta navbatdagi AI xabari (12 §8, fencing)
        Index(
            "uq_messages_ai_pending",
            "shop_id",
            "conversation_id",
            "speaker_version",
            unique=True,
            postgresql_where=text("origin = 'AI_AUTO' AND delivery_status IN ('QUEUED', 'SENDING')"),
        ),
        Index(
            "ix_messages_pending",
            "delivery_status",
            "created_at",
            postgresql_where=text("delivery_status IN ('QUEUED', 'SENDING')"),
        ),
        Index(
            "ix_messages_provider",
            "shop_id",
            "conversation_id",
            "provider_message_id",
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
        Index("ix_messages_shop_id_created_at", "shop_id", "created_at"),
        _fk(["shop_id", "conversation_id"], "conversations"),
        ForeignKeyConstraint(
            ["shop_id", "reply_to_message_id"],
            [f"{SCHEMA}.messages.shop_id", f"{SCHEMA}.messages.id"],
            name="fk_messages_reply_to",
        ),
        CheckConstraint(f"direction IN {DIRECTIONS}", name="direction"),
        CheckConstraint(f"author_type IN {AUTHOR_TYPES}", name="author_type"),
        CheckConstraint(f"origin IN {MESSAGE_ORIGINS}", name="origin"),
        CheckConstraint(f"kind IN {MESSAGE_KINDS}", name="kind"),
        CheckConstraint(f"delivery_status IN {DELIVERY_STATUSES}", name="delivery_status"),
        CheckConstraint("seq > 0", name="seq_positive"),
        CheckConstraint("parts > 0", name="parts_positive"),
        CheckConstraint("parts_sent >= 0", name="parts_sent_nonnegative"),
        CheckConstraint("(direction = 'IN') = (delivery_status = 'RECEIVED')", name="received_only_inbound"),
        {"schema": SCHEMA},
    )

    conversation_id: Mapped[UUID]
    seq: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(Text)
    author_type: Mapped[str] = mapped_column(Text)
    author_membership_id: Mapped[UUID | None]
    origin: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, server_default="TEXT")
    body: Mapped[str | None] = mapped_column(Text)
    intent_hint: Mapped[str | None] = mapped_column(Text)
    reply_to_message_id: Mapped[UUID | None]
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    parts: Mapped[int] = mapped_column(Integer, server_default="1")
    # Bo'laklab yuborishda nechta bo'lak ketgani — qayta urinish o'sha joydan davom etadi (QA 5b L8)
    parts_sent: Mapped[int] = mapped_column(Integer, server_default="0")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    speaker_version: Mapped[int | None] = mapped_column(BigInteger)
    intent_key: Mapped[str | None] = mapped_column(Text)
    ai_reply_id: Mapped[UUID | None]  # sales_ai.ai_turns.id (6-modul)
    notification_id: Mapped[UUID | None]  # platform.notifications.id
    delivery_status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    # SENDING ga o'tgan vaqt: "osilib qolgan" yuborish shundan hisoblanadi, created_at dan emas (QA 5b M5)
    sending_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attachment(IdMixin, ShopScopedMixin, Base):
    """Rasm, ovoz, fayl. Webhook ichida yuklab olinmaydi — fon vazifasi (13 §3). Fayl — yopiq
    (`CHAT_ATTACHMENT`, imzoli havola)."""

    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_attachments_shop_id_message_id", "shop_id", "message_id"),
        Index("ix_attachments_pending", "status", "created_at", postgresql_where=text("status = 'PENDING'")),
        _fk(["shop_id", "message_id"], "messages", ondelete="CASCADE"),
        CheckConstraint(f"kind IN {MESSAGE_KINDS}", name="kind"),
        CheckConstraint(f"status IN {ATTACHMENT_STATUSES}", name="status"),
        {"schema": SCHEMA},
    )

    message_id: Mapped[UUID]
    file_id: Mapped[UUID | None]  # platform.stored_files.id
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    provider_file_ref: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Handoff(IdMixin, ShopScopedMixin, Base):
    """Operatorni chaqirish tarixi va navbati. Ochiq handoff = `platform.staff_tasks` dagi HANDOFF
    vazifasi."""

    __tablename__ = "handoffs"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index(
            "uq_handoffs_open",
            "shop_id",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
        Index("ix_handoffs_shop_id_conversation_id_created_at", "shop_id", "conversation_id", "created_at"),
        _fk(["shop_id", "conversation_id"], "conversations"),
        CheckConstraint(f"reason IN {HANDOFF_REASONS}", name="reason"),
        CheckConstraint(f"requested_by_type IN {REQUESTER_TYPES}", name="requested_by_type"),
        CheckConstraint(f"status IN {HANDOFF_STATUSES}", name="status"),
        {"schema": SCHEMA},
    )

    conversation_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    requested_by_type: Mapped[str] = mapped_column(Text)
    requested_by_membership_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="OPEN")
    speaker_version_at_request: Mapped[int] = mapped_column(BigInteger)
    taken_by: Mapped[UUID | None]
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # eslatma bir marta
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationNote(IdMixin, ShopScopedMixin, Base):
    """Operatorlar uchun ichki izoh (M10, 4-band). Faqat qo'shiladi; xaridorga ko'rinmaydi."""

    __tablename__ = "conversation_notes"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_conversation_notes_created", "shop_id", "conversation_id", "created_at"),
        _fk(["shop_id", "conversation_id"], "conversations"),
        {"schema": SCHEMA},
    )

    conversation_id: Mapped[UUID]
    author_membership_id: Mapped[UUID]
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebchatSession(IdMixin, ShopScopedMixin, Base):
    """Sayt chatining anonim sessiyasi (13 §8). Token o'zi saqlanmaydi — SHA-256 xeshi; 30 kun, har
    faollikda suriladi. Boshqa shop slug'i bilan — 404 (TC-CH-06)."""

    __tablename__ = "webchat_sessions"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("token_hash"),
        Index("ix_webchat_sessions_identity", "shop_id", "customer_identity_id"),
        Index("ix_webchat_sessions_expires_at", "expires_at"),
        _fk(
            ["shop_id", "channel_account_id"], "channel_accounts", name="fk_webchat_sessions_channel_account"
        ),
        _fk(
            ["shop_id", "customer_identity_id"],
            "customer_identities",
            name="fk_webchat_sessions_customer_identity",
        ),
        {"schema": SCHEMA},
    )

    channel_account_id: Mapped[UUID]
    customer_identity_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
