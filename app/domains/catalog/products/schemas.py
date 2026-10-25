"""Toifalar, mahsulotlar, SKU va rasmlar API kontrakti (11 §9.3, db/catalog.dbml)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.shared.money import MAX_SAFE_MINOR, MAX_USD_MINOR, Currency
from app.shared.text import Text

ProductStatus = Literal["DRAFT", "IN_REVIEW", "PUBLISHED", "HIDDEN", "ARCHIVED"]
SkuStatus = Literal["ACTIVE", "ARCHIVED"]
SkuCondition = Literal["NEW", "USED", "REFURBISHED"]
SpecCategory = Literal["CPU", "MOTHERBOARD", "GPU", "RAM", "PSU", "CASE", "CPU_COOLER", "STORAGE"]
LinkMethod = Literal["AUTO_MPN", "AUTO_MODEL", "MANUAL"]
ProductSort = Literal["-updated_at", "-created_at", "title"]

CATEGORY_CODE = r"^[A-Z][A-Z0-9_]{1,39}$"
SKU_CODE = r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,63}$"
MAX_SKU_ATTRIBUTES = 30
MAX_SKUS_PER_REQUEST = 20

AttrValue = str | int | float | bool


def _check_attributes(value: dict[str, AttrValue]) -> dict[str, AttrValue]:
    if len(value) > MAX_SKU_ATTRIBUTES:
        raise ValueError(f"at most {MAX_SKU_ATTRIBUTES} attributes")
    for key, item in value.items():
        if not 1 <= len(key.strip()) <= 40:
            raise ValueError("attribute name must be 1-40 characters")
        if isinstance(item, str) and len(item) > 200:
            raise ValueError("attribute value must be at most 200 characters")
        # NaN/Infinity jsonb'ga yozilmaydi; 2^53 dan katta son brauzerda buziladi
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("attribute value must be a finite number")
        if isinstance(item, int) and not isinstance(item, bool) and abs(item) > MAX_SAFE_MINOR:
            raise ValueError("attribute value is too large")
    return value


# ------------------------------------------------------------------ toifalar


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    parent_code: str | None
    name_uz: str
    name_ru: str
    name_en: str
    spec_category: SpecCategory | None
    position: int
    is_active: bool


class CategoryList(BaseModel):
    items: list[CategoryOut]


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=CATEGORY_CODE)
    parent_code: str | None = Field(default=None, pattern=CATEGORY_CODE)
    name_uz: Text = Field(min_length=1, max_length=80)
    name_ru: Text = Field(min_length=1, max_length=80)
    name_en: Text = Field(min_length=1, max_length=80)
    spec_category: SpecCategory | None = None
    position: int = Field(default=0, ge=0, le=10_000)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    """PATCH: yuborilmagan maydon o'zgarmaydi. Kod o'zgarmaydi (mahsulotlar unga bog'langan)."""

    model_config = ConfigDict(extra="forbid")

    parent_code: str | None = Field(default=None, pattern=CATEGORY_CODE)
    name_uz: Text | None = Field(default=None, min_length=1, max_length=80)
    name_ru: Text | None = Field(default=None, min_length=1, max_length=80)
    name_en: Text | None = Field(default=None, min_length=1, max_length=80)
    spec_category: SpecCategory | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None


# ------------------------------------------------------------------ narx (SKU ichida ko'rinishi)


class PriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Currency  # amount_minor'dan oldin: dollar chegarasi valyutaga qarab tekshiriladi
    amount_minor: int = Field(ge=1, le=10**15, description="Tiyin yoki sent: 4 500 000 so'm = 450000000")
    reason: Text | None = Field(default=None, max_length=300)

    @field_validator("amount_minor")
    @classmethod
    def _usd_limit(cls, value: int, info: ValidationInfo) -> int:
        # Eng katta kursda ham so'mdagi narx brauzer aniq o'qiydigan son ichida qolsin (app.shared.money)
        if info.data.get("currency") == "USD" and value > MAX_USD_MINOR:
            raise PydanticCustomError(
                "less_than_equal", "Input should be less than or equal to {le}", {"le": MAX_USD_MINOR}
            )
        return value


class PriceOut(BaseModel):
    price_version_id: UUID
    amount_minor: int
    currency: Currency
    # Xaridor ko'radigan so'm narxi (tiyinda): dollar bo'lsa shop kursi bo'yicha, yaxlitlanmaydi (DEC-133).
    # Kurs kiritilmagan bo'lsa — null
    uzs_amount_minor: int | None
    version: int  # joriy narx ko'rsatkichi versiyasi — narx o'zgartirishda If-Match
    updated_at: datetime


class SpecLinkOut(BaseModel):
    spec_id: UUID
    category: SpecCategory
    brand: str
    model_name: str
    variant_key: str
    method: LinkMethod
    linked_at: datetime


# ------------------------------------------------------------------ SKU


class SkuIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_code: Text = Field(pattern=SKU_CODE)
    variant_name: Text | None = Field(default=None, max_length=120)
    condition: SkuCondition = "NEW"
    mpn: Text | None = Field(default=None, max_length=64)
    model_name: Text | None = Field(default=None, max_length=200)
    attributes: dict[str, AttrValue] = Field(default_factory=dict)
    warranty_months: int | None = Field(default=None, ge=0, le=120)
    price: PriceIn | None = None

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, value: dict[str, AttrValue]) -> dict[str, AttrValue]:
        return _check_attributes(value)


class SkuUpdate(BaseModel):
    """PATCH: yuborilmagan maydon o'zgarmaydi; `null` — tozalash (ixtiyoriy maydonlar uchun)."""

    model_config = ConfigDict(extra="forbid")

    sku_code: Text | None = Field(default=None, pattern=SKU_CODE)
    variant_name: Text | None = Field(default=None, max_length=120)
    condition: SkuCondition | None = None
    mpn: Text | None = Field(default=None, max_length=64)
    model_name: Text | None = Field(default=None, max_length=200)
    attributes: dict[str, AttrValue] | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=120)

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, value: dict[str, AttrValue] | None) -> dict[str, AttrValue] | None:
        return None if value is None else _check_attributes(value)


class SkuOut(BaseModel):
    id: UUID
    product_id: UUID
    sku_code: str
    variant_name: str | None
    condition: SkuCondition
    mpn: str | None
    model_name: str | None
    attributes: dict[str, Any]
    warranty_months: int | None
    status: SkuStatus
    price: PriceOut | None
    spec_link: SpecLinkOut | None
    # Xodim bog'lanishni qo'lda uzgan — avtomatik bog'lash o'chiq, xodim o'zi bog'laguncha
    spec_autolink_blocked: bool
    created_at: datetime
    updated_at: datetime
    version: int


# ------------------------------------------------------------------ mahsulot


class MediaOut(BaseModel):
    id: UUID
    file_id: UUID
    url: str
    position: int


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_code: str = Field(pattern=CATEGORY_CODE)
    title: Text = Field(min_length=1, max_length=300)
    brand: Text | None = Field(default=None, max_length=100)
    description: Text | None = Field(default=None, max_length=5000)
    # Ko'p mahsulotda bitta variant bo'ladi — kartochka, SKU va narx bitta so'rovda
    skus: list[SkuIn] = Field(default_factory=list, max_length=MAX_SKUS_PER_REQUEST)


class ProductUpdate(BaseModel):
    """PATCH: yuborilmagan maydon o'zgarmaydi."""

    model_config = ConfigDict(extra="forbid")

    category_code: str | None = Field(default=None, pattern=CATEGORY_CODE)
    title: Text | None = Field(default=None, min_length=1, max_length=300)
    brand: Text | None = Field(default=None, max_length=100)
    description: Text | None = Field(default=None, max_length=5000)


class ProductOut(BaseModel):
    id: UUID
    category_code: str
    brand: str | None
    title: str
    description: str | None
    status: ProductStatus
    published_at: datetime | None
    archived_at: datetime | None
    # Toifa PC qismi bo'lsa — SKU texnik kutubxonaga bog'lanadi (bog'lanmagani PC yig'mada "tekshirish kerak")
    spec_category: SpecCategory | None
    skus: list[SkuOut]
    media: list[MediaOut]
    created_at: datetime
    updated_at: datetime
    version: int


class ProductListItem(BaseModel):
    id: UUID
    category_code: str
    brand: str | None
    title: str
    status: ProductStatus
    sku_count: int
    active_sku_count: int
    # Faol variantlar ichida eng arzon so'm narxi (tiyinda); narx yoki kurs yo'q bo'lsa — null
    price_from_uzs_minor: int | None
    image_url: str | None
    updated_at: datetime
    version: int


class ProductList(BaseModel):
    items: list[ProductListItem]
    next_cursor: str | None
    has_more: bool


class ProductCounts(BaseModel):
    """Holat bo'yicha sanoq — ro'yxat tablari uchun."""

    by_status: dict[ProductStatus, int]
    total: int


class TransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Text | None = Field(default=None, max_length=500)


class MediaAttachIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID


class MediaOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_ids: Annotated[list[UUID], Field(min_length=1, max_length=10)]
