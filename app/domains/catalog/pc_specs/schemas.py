"""Texnik ma'lumotlar kutubxonasi, SKU bog'lanishi va shop so'rovlari API kontrakti (engineering/17 §10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.catalog.products.schemas import SpecCategory
from app.shared.text import Text

SpecStatus = Literal["DRAFT", "APPROVED", "RETIRED"]
SpecVersionStatus = Literal["PENDING", "APPROVED", "REJECTED"]
SpecRequestStatus = Literal["OPEN", "RESOLVED", "REJECTED"]
_URL = r"^https?://[^\s]+$"


class HardwareSpecOut(BaseModel):
    id: UUID
    category: SpecCategory
    brand: str
    model_name: str
    variant_key: str
    mpn: str | None
    attributes: dict[str, Any]
    source_url: str
    status: SpecStatus
    version: int
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    pending_version: int | None  # tasdiq kutayotgan taklif bo'lsa — uning raqami


class HardwareSpecList(BaseModel):
    items: list[HardwareSpecOut]
    total: int


class _SpecData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: Text = Field(min_length=1, max_length=100)
    model_name: Text = Field(min_length=1, max_length=200)
    variant_key: Text = Field(
        default="", max_length=40, description='Bir model ichidagi farq: "8GB" / "16GB"'
    )
    mpn: Text | None = Field(default=None, max_length=64)
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_url: Text = Field(
        pattern=_URL, max_length=500, description="Ishlab chiqaruvchi sahifasi (DEC-120)"
    )


class HardwareSpecIn(_SpecData):
    category: SpecCategory


class SpecVersionIn(_SpecData):
    """O'zgarish taklifi — to'liq nusxa; ikkinchi odam tasdiqlagach asosiy yozuvga ko'chadi."""


class SpecVersionOut(BaseModel):
    version: int
    brand: str
    model_name: str
    variant_key: str
    mpn: str | None
    attributes: dict[str, Any]
    source_url: str
    status: SpecVersionStatus
    proposed_by: UUID
    proposed_by_name: str | None
    proposed_at: datetime
    reviewed_by: UUID | None
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    review_note: str | None


class HardwareSpecDetail(HardwareSpecOut):
    versions: list[SpecVersionOut]


class SpecReviewQueueItem(BaseModel):
    spec_id: UUID
    category: SpecCategory
    brand: str
    model_name: str
    variant_key: str
    version: int
    is_new: bool  # yangi model (hali tasdiqlanmagan) yoki mavjudiga o'zgarish
    proposed_by: UUID
    proposed_by_name: str | None
    proposed_at: datetime


class SpecReviewQueue(BaseModel):
    items: list[SpecReviewQueueItem]


class SpecNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Text = Field(min_length=3, max_length=500)


# ------------------------------------------------------------------ shop: bog'lash va so'rovlar


class SpecLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: UUID


class SpecCandidates(BaseModel):
    """SKU uchun aniq mos kelgan modellar. Bittadan ko'p bo'lsa — avtomatik bog'lanmaydi, xodim tanlaydi."""

    items: list[HardwareSpecOut]


class AutoLinkResult(BaseModel):
    checked: int
    linked: int


class SpecRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID | None = None
    category: SpecCategory
    brand: Text = Field(min_length=1, max_length=100)
    model_name: Text = Field(min_length=1, max_length=200)
    mpn: Text | None = Field(default=None, max_length=64)
    source_url: Text | None = Field(default=None, pattern=_URL, max_length=500)
    comment: Text | None = Field(default=None, max_length=1000)


class SpecRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_id: UUID | None
    category: SpecCategory
    brand: str
    model_name: str
    mpn: str | None
    source_url: str | None
    comment: str | None
    status: SpecRequestStatus
    resolved_spec_id: UUID | None
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None


class SpecRequestList(BaseModel):
    items: list[SpecRequestOut]


class PlatformSpecRequestOut(SpecRequestOut):
    shop_id: UUID
    shop_name: str
    shop_slug: str
    # So'ralgan SKU mahsulotining HOZIRGI turi — so'rovdagi `category` bilan farq qilsa, bog'lab bo'lmaydi
    sku_spec_category: SpecCategory | None = None


class PlatformSpecRequestList(BaseModel):
    items: list[PlatformSpecRequestOut]
    total: int


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: UUID
