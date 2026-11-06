"""Shop, sozlamalar, filiallar va platforma API kontraktlari (11 §9.2, §9.10)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.platform.staff.schemas import LinkOut

ShopStatus = Literal["DRAFT", "PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "CLOSED"]
Locale = Literal["uz", "ru", "en"]
_SLUG = r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"
_TIN = r"^[0-9]{9}$"


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    legal_name: str | None
    tin: str
    status: ShopStatus
    default_locale: Locale
    timezone: str
    activated_at: datetime | None
    created_at: datetime
    version: int
    signup_source: Literal["PLATFORM", "SELF"] = "PLATFORM"  # M21: SELF — ega o'zi ro'yxatdan o'tgan


class ShopOwnerOut(BaseModel):
    membership_id: UUID
    full_name: str
    phone: str
    status: Literal["INVITED", "ACTIVE", "DISABLED"]


class PlatformShopOut(ShopOut):
    """Platforma kartochkasi: shop holati va ega bilan bog'lanish (savdo ma'lumotisiz, 10 §9)."""

    owners: list[ShopOwnerOut]


class ShopProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    legal_name: str | None = Field(default=None, max_length=200)
    tin: str = Field(pattern=_TIN)
    default_locale: Locale = "uz"
    timezone: str = Field(default="Asia/Tashkent", max_length=64)


_HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class InboxHours(BaseModel):
    """Operatorlar ish vaqti (shop vaqt mintaqasida): kunlar (1 — dushanba … 7 — yakshanba) va soat oralig'i.
    Ish vaqtidan tashqari "operator kutilmoqda" eslatmasi kechiktiriladi, xaridorga bir marta
    `customer.handoff_after_hours` matni ketadi (db/notifications.md §5). Bo'sh — doim ish vaqti."""

    model_config = ConfigDict(extra="forbid")

    days: list[Annotated[int, Field(ge=1, le=7)]] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=_HHMM, description="09:00")
    end: str = Field(
        pattern=_HHMM, description="19:00 (start dan katta bo'lsa — o'sha kun; kichik — tungi smena)"
    )

    @field_validator("days")
    @classmethod
    def _unique_days(cls, days: list[int]) -> list[int]:
        return sorted(set(days))  # [1, 1, 1] → [1] (QA 5b M4): takror kun ma'no o'zgartirmaydi

    @field_validator("end")
    @classmethod
    def _not_empty_window(cls, end: str, info: ValidationInfo) -> str:
        if end == info.data.get("start"):  # 09:00–09:00 — "doim yopiq" emas, xato (QA 5b M4)
            raise PydanticCustomError("invalid_range", "end must differ from start")
        return end


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quote_ttl_hours: int
    discount_limit_sales_pct: Decimal
    discount_limit_manager_pct: Decimal
    order_reminder_hours: list[int]
    quote_approval_mode: Literal["ALL", "RISKY_ONLY"]
    exchange_rate_source: Literal["MANUAL", "CBU"]
    stock_display: Literal["EXACT", "STATUS_ONLY"]
    low_stock_threshold: int
    delivery_enabled: bool
    handoff_reminder_minutes: int
    inbox_hours: InboxHours | None
    version: int


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_ttl_hours: int = Field(ge=1, le=720)
    discount_limit_sales_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    discount_limit_manager_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    order_reminder_hours: list[Annotated[int, Field(ge=1, le=720)]] = Field(min_length=1, max_length=5)
    quote_approval_mode: Literal["ALL", "RISKY_ONLY"]
    exchange_rate_source: Literal["MANUAL", "CBU"]
    stock_display: Literal["EXACT", "STATUS_ONLY"]
    low_stock_threshold: int = Field(ge=0, le=1000)
    # Yuborilmasa o'zgarmaydi (eski klientlar uchun): sayt formasida "yetkazib berish" bormi
    delivery_enabled: bool | None = None
    # 5b: "operator kutilmoqda" eslatmasi (daqiqa) va ish vaqti. Yuborilmasa o'zgarmaydi;
    # `inbox_hours: null` — o'chiriladi (doim ish vaqti)
    handoff_reminder_minutes: int | None = Field(default=None, ge=1, le=1440)
    inbox_hours: InboxHours | None = None


class BranchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=3, max_length=300)
    phone: str | None = Field(default=None, max_length=20)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    working_hours: dict[str, Any] = Field(default_factory=dict)
    is_pickup_point: bool = True


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    address: str
    phone: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    working_hours: dict[str, Any]
    is_pickup_point: bool
    status: Literal["ACTIVE", "CLOSED"]
    version: int


class BranchList(BaseModel):
    items: list[BranchOut]


class BranchOption(BaseModel):
    """Filial tanlash ro'yxati uchun — har xodimga ochiq (manzil va telefonsiz)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: Literal["ACTIVE", "CLOSED"]
    is_pickup_point: bool


class BranchOptionList(BaseModel):
    items: list[BranchOption]


class ShopCreateIn(BaseModel):
    """Platforma admini shop yaratadi va egani taklif qiladi (DEC-122)."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG)
    name: str = Field(min_length=2, max_length=120)
    legal_name: str | None = Field(default=None, max_length=200)
    tin: str = Field(pattern=_TIN)
    default_locale: Locale = "uz"
    owner_phone: str = Field(min_length=9, max_length=20)
    owner_full_name: str = Field(min_length=2, max_length=120)


class ShopCreatedOut(BaseModel):
    shop: ShopOut
    owner_membership_id: UUID
    owner_invite: LinkOut


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)
