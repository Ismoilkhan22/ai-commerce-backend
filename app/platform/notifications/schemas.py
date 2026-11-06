"""Shop paneli: bildirishnomalar markazi, vazifalar, xodim sozlamasi, platforma botiga ulanish."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.platform.notifications.templates import TEMPLATES
from app.shared.text import CleanText

# O'chirib qo'yish mumkin bo'lgan xabar turlari: shablon kalitlari, HIGH'dan tashqari (HIGH doim yetadi)
MUTABLE_TYPES = frozenset(key for key, template in TEMPLATES.items() if template.priority != "HIGH")

NotificationStatus = Literal["PENDING", "SCHEDULED", "SENT", "FAILED", "SUPPRESSED"]
Priority = Literal["HIGH", "NORMAL", "LOW"]
TaskStatus = Literal["OPEN", "DONE", "RESOLVED", "CANCELLED"]
# Ekranda qayerga o'tish: frontend `route` + `id` dan shop paneli manzilini quradi
LinkRoute = Literal[
    "order",
    "adjustment",
    "stock",
    "exchange_rates",
    "notification_settings",
    "conversation",
    "channels",
    "lead",
    "quote",
    "support_case",  # 7b: kafolat murojaati
    "demand_gaps",  # DEC-149: "So'rashdi, lekin bizda yo'q" hisoboti
]


class NotificationOut(BaseModel):
    id: UUID
    template_key: str
    priority: Priority
    title: str | None
    body: str | None
    aggregate_type: str
    aggregate_id: UUID
    link: TaskLink | None
    created_at: datetime
    read_at: datetime | None
    delivery_status: NotificationStatus  # platforma botiga yetkazish (FSM-12)


class NotificationList(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None
    has_more: bool
    unread_count: int


class UnreadCount(BaseModel):
    unread_count: int


class TaskLink(BaseModel):
    route: LinkRoute
    id: UUID | None = None


class TaskOut(BaseModel):
    id: UUID
    type: str
    status: TaskStatus
    priority: Priority
    subject_type: str
    subject_id: UUID
    branch_id: UUID | None
    assignee_membership_id: UUID | None
    assignee_role: str | None
    params: dict[str, Any]
    link: TaskLink | None
    due_at: datetime | None
    created_at: datetime
    resolved_at: datetime | None
    version: int


class TaskList(BaseModel):
    items: list[TaskOut]
    next_cursor: str | None
    has_more: bool
    open_count: int


class TaskAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID


class NotificationSettingsOut(BaseModel):
    quiet_from: time | None
    quiet_to: time | None
    telegram_enabled: bool
    muted_types: list[str]
    telegram_linked: bool
    version: int  # 0 — hali saqlanmagan (standart qiymatlar)


class NotificationSettingsIn(BaseModel):
    """Noma'lum maydon — 422 (QA 5a F9): xato yozilgan `quiet_form` jim e'tiborsiz qolib, tinch soatni
    o'chirib yubormasin."""

    model_config = ConfigDict(extra="forbid")

    quiet_from: time | None = None  # shop vaqti, offset'siz
    quiet_to: time | None = None
    telegram_enabled: bool = True
    muted_types: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("quiet_from", "quiet_to")
    @classmethod
    def _no_offset(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:  # offset jim tashlab yuborilardi
            raise PydanticCustomError("time_offset", "Time must be shop-local, without UTC offset")
        return value

    @field_validator("quiet_to")
    @classmethod
    def _not_same(cls, value: time | None, info: ValidationInfo) -> time | None:
        if value is not None and value == info.data.get("quiet_from"):  # aks holda 24 soat tinch
            raise PydanticCustomError("quiet_same", "quiet_to must differ from quiet_from")
        return value

    @field_validator("muted_types")
    @classmethod
    def _known_types(cls, value: list[str]) -> list[str]:
        for item in value:
            if item not in MUTABLE_TYPES:
                raise PydanticCustomError(
                    "literal_error", "Unknown or not mutable type {type}", {"type": item[:64]}
                )
        return value

    @model_validator(mode="after")
    def _quiet_pair(self) -> Self:
        if (self.quiet_from is None) != (self.quiet_to is None):
            raise ValueError("quiet_from va quiet_to birga beriladi")
        return self


class TelegramLinkCodeOut(BaseModel):
    code: str  # faqat shu javobda bir marta — bazada xeshi
    expires_at: datetime
    bot_username: str | None
    deep_link: str | None  # https://t.me/<bot>?start=<code>


class TelegramLinkStatus(BaseModel):
    linked: bool
    linked_at: datetime | None
    bot_username: str | None
    bot_configured: bool


NotificationOut.model_rebuild()


# ------------------------------------------------------------------------------ xaridor matnlari (5b)
TemplateLocale = Literal["uz", "ru", "en"]


class MessageTemplateOut(BaseModel):
    """Bitta kalit + til: standart matn, amaldagi matn va shop o'zgartirganmi (DEC-139)."""

    template_key: str
    locale: TemplateLocale
    body: str  # amaldagi (shop matni yoki standart)
    default_body: str
    overridden: bool
    version: int | None  # shop matni versiyasi; standartda None
    required_variables: list[str]
    allowed_variables: list[str]


class MessageTemplateList(BaseModel):
    items: list[MessageTemplateOut]


class MessageTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CleanText = Field(min_length=1, max_length=1000)  # bo'shliqsiz, NUL va ko'rinmas belgilarsiz
