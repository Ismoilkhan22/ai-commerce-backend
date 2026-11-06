"""messaging API kontraktlari: shop paneli (inbox, kanallar) va sayt chati (anonim mehmon)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from app.shared.text import CleanText

Channel = Literal["TELEGRAM", "INSTAGRAM", "WEB_CHAT"]
ChannelStatus = Literal["PENDING", "CONNECTED", "DEGRADED", "DISCONNECTED"]
ConversationStatus = Literal[
    "NEW", "AI_ACTIVE", "WAITING_CUSTOMER", "HUMAN_NEEDED", "HUMAN_ACTIVE", "RESOLVED", "REOPENED"
]
SpeakerMode = Literal["AI", "HUMAN", "PAUSED"]
DeliveryStatus = Literal["RECEIVED", "QUEUED", "SENDING", "SENT", "FAILED", "UNKNOWN", "DISCARDED"]
MessageKind = Literal["TEXT", "IMAGE", "VOICE", "FILE", "CONTACT", "LOCATION", "STICKER", "UNSUPPORTED"]
ConversationAction = Literal[
    "TAKE", "REPLY", "ASSIGN", "RESOLVE", "REOPEN", "CREATE_ORDER", "NOTE", "RESUME_AI"
]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
TELEGRAM_TOKEN = r"^[0-9]{5,15}:[A-Za-z0-9_-]{30,64}$"  # noqa: S105 — format (regex), sir emas


# ------------------------------------------------------------------ kanallar
class ChannelAccountOut(BaseModel):
    """Token va webhook siri hech qachon qaytmaydi."""

    id: UUID
    channel: Channel
    status: ChannelStatus
    display_name: str | None
    external_account_id: str | None
    mode: Literal["webhook", "polling"] | None  # Telegram: lokalda polling, prod'da webhook
    is_fake: bool  # dev seed'dagi soxta akkaunt — yuborish faqat soxta klientga
    last_webhook_at: datetime | None
    last_error_code: str | None
    connected_at: datetime | None
    disconnected_at: datetime | None
    disconnect_reason: str | None
    version: int


class ChannelList(BaseModel):
    items: list[ChannelAccountOut]
    telegram_mode: Literal["webhook", "polling"]
    instagram_available: bool  # DEC-116a flag


class TelegramConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(pattern=TELEGRAM_TOKEN, max_length=100, description="@BotFather bergan token")


class InstagramConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=20, max_length=500)


# ------------------------------------------------------------------ suhbatlar
class CustomerOut(BaseModel):
    id: UUID
    channel: Channel
    display_name: str | None
    username: str | None
    locale: str | None
    phone: str | None  # to'liq — faqat suhbat kartochkasida
    phone_masked: str | None
    blocked: bool
    contact_consent_at: datetime | None


class LastMessage(BaseModel):
    direction: Literal["IN", "OUT"]
    author_type: str  # CUSTOMER | STAFF | AI | SYSTEM — SYSTEM xabarga "siz:" qo'yilmaydi (QA 5b L7)
    kind: MessageKind
    preview: str | None  # 120 belgigacha
    at: datetime


class ConversationItem(BaseModel):
    id: UUID
    channel: Channel
    status: ConversationStatus
    speaker_mode: SpeakerMode
    assignee_membership_id: UUID | None
    assignee_name: str | None = None  # mas'ul xodim ismi (QA 5b L6)
    customer_name: str | None
    customer_username: str | None
    last_message: LastMessage | None
    last_message_at: datetime | None
    unread_count: int
    tags: list[str]
    waiting_since: datetime | None
    last_order_id: UUID | None
    version: int


class ConversationList(BaseModel):
    items: list[ConversationItem]
    next_cursor: str | None
    has_more: bool


class ConversationCounts(BaseModel):
    open: int  # yopilmaganlar (ko'rinadiganlar)
    mine: int
    unassigned: int
    human_needed: int
    unread: int


class HandoffOut(BaseModel):
    id: UUID
    reason: str
    requested_by_type: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: UUID
    channel: Channel
    channel_account_id: UUID
    channel_available: bool  # yozib bo'ladimi (kanal ulangan, xaridor bloklamagan)
    status: ConversationStatus
    speaker_mode: SpeakerMode
    speaker_version: int
    assignee_membership_id: UUID | None
    assignee_name: str | None = None  # mas'ul xodim ismi (QA 5b L6)
    locale: str | None
    tags: list[str]
    customer: CustomerOut
    message_seq: int
    staff_last_read_seq: int
    unread_count: int
    last_message_at: datetime | None
    waiting_since: datetime | None
    first_staff_reply_at: datetime | None
    resolved_at: datetime | None
    last_order_id: UUID | None
    open_handoff: HandoffOut | None
    allowed_actions: list[ConversationAction]
    version: int


class AttachmentOut(BaseModel):
    id: UUID
    kind: MessageKind
    status: Literal["PENDING", "STORED", "FAILED", "PURGED"]
    mime: str | None
    size_bytes: int | None
    url: str | None  # yopiq fayl — 5 daqiqalik imzoli havola
    url_expires_at: datetime | None
    error_code: str | None


class MessageOut(BaseModel):
    id: UUID
    seq: int
    direction: Literal["IN", "OUT"]
    author_type: Literal["CUSTOMER", "AI", "STAFF", "SYSTEM"]
    author_membership_id: UUID | None
    origin: str
    kind: MessageKind
    body: str | None
    intent_hint: str | None
    delivery_status: DeliveryStatus
    last_error_code: str | None
    attempts: int
    occurred_at: datetime
    sent_at: datetime | None
    edited_at: datetime | None
    attachments: list[AttachmentOut]


class MessageList(BaseModel):
    items: list[MessageOut]  # seq bo'yicha o'sish tartibida
    has_more_before: bool


class ReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CleanText | None = Field(default=None, min_length=1, max_length=4000)
    attachment_file_id: UUID | None = None  # CHAT_ATTACHMENT (avval POST /shop/files)

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.body is None and self.attachment_file_id is None:
            raise ValueError("body or attachment_file_id is required")
        return self


class ConversationAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID


class TagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[Tag] = Field(max_length=10)


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CleanText = Field(min_length=1, max_length=2000)


class NoteOut(BaseModel):
    id: UUID
    author_membership_id: UUID
    body: str
    created_at: datetime


class NoteList(BaseModel):
    items: list[NoteOut]


class ConversationOrderIn(BaseModel):
    """Suhbatdan buyurtma qoralamasi: xaridor ismi, telefoni va tili suhbatdan olinadi."""

    model_config = ConfigDict(extra="forbid")

    branch_id: UUID | None = None
    fulfillment_method: Literal["PICKUP", "DELIVERY"] = "PICKUP"


class LinkOrderIn(BaseModel):
    """Boshqa suhbatga bog'langan buyurtma — `relink: true` + `expected_version` (buyurtma versiyasi) bilan
    ko'chiriladi, aks holda 409 `ORDER_LINKED_ELSEWHERE` (QA 5b M3)."""

    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    relink: bool = False
    expected_version: int | None = Field(default=None, ge=1)


class OrderRefOut(BaseModel):
    id: UUID
    number: int
    status: str


class OrderRefList(BaseModel):
    items: list[OrderRefOut]


# ------------------------------------------------------------------ sayt chati (anonim)
ChatState = Literal["WAITING_OPERATOR", "OPERATOR", "CLOSED"]


class ChatSessionOut(BaseModel):
    token: str  # sayt serveri httpOnly cookie'ga yozadi va `X-Chat-Session` bilan uzatadi (4-qaror)
    expires_at: datetime
    poll_interval_seconds: int


class ChatMessageOut(BaseModel):
    seq: int
    direction: Literal["IN", "OUT"]
    author: Literal["customer", "operator", "system"]
    kind: MessageKind
    body: str | None
    image_url: str | None = None  # IMAGE — qisqa muddatli imzoli havola (QA 5b M2)
    image_url_expires_at: datetime | None = None
    occurred_at: datetime


class ChatMessagesOut(BaseModel):
    items: list[ChatMessageOut]
    state: ChatState
    last_seq: int
    poll_interval_seconds: int


class ChatSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(
        pattern=r"^[A-Za-z0-9_-]{8,64}$", description="Brauzer yaratadi — takror himoyasi"
    )
    body: CleanText = Field(min_length=1, max_length=2000)


class ChatSendOut(BaseModel):
    seq: int
    duplicate: bool


class ChatContactIn(BaseModel):
    """Mehmon ismi va telefoni (ixtiyoriy) — rozilik bilan (BL-036). Telefon shifrlangan saqlanadi."""

    model_config = ConfigDict(extra="forbid")

    name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    consent: Literal[True]

    @model_validator(mode="after")
    def _some_contact(self) -> Self:
        if not self.name and not (self.phone or "").strip():  # rozilik — nimagadir (QA 5b L5)
            raise PydanticCustomError("contact_required", "Name or phone is required")
        return self
