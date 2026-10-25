"""Shop, sozlamalar, filiallar va platforma API kontraktlari (11 §9.2, §9.10)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
