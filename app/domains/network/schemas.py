"""network DTO'lari (Stage 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OfferField = Literal["price", "condition", "warranty", "availability"]
OfferStatus = Literal["ACTIVE", "WITHDRAWN", "SUSPENDED"]
LinkStatus = Literal["LINKED", "PENDING_REVIEW", "UNLINKED"]


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_ids: list[UUID] = Field(min_length=1, max_length=100)
    permitted_fields: list[OfferField] | None = None


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku_id: UUID
    canonical_id: UUID | None
    status: OfferStatus
    listing_version: int
    permitted_fields: list[str]
    title: str
    price_uzs_minor: int | None
    availability: str | None
    withdraw_reason: str | None
    published_at: datetime
    last_verified_at: datetime


class NetworkSkuRow(BaseModel):
    """Panel: shop mahsuloti va uning global qidiruvdagi holati."""

    sku_id: UUID
    title: str
    brand: str | None
    sellable: bool
    price_uzs_minor: int | None
    publishable_problem: str | None  # NOT_SELLABLE | NO_PRICE
    offer: OfferOut | None
    link_status: LinkStatus | None
    link_reason: str | None
    canonical_title: str | None


class NetworkSkuList(BaseModel):
    items: list[NetworkSkuRow]
    shop_verified: bool


class OfferList(BaseModel):
    items: list[OfferOut]


class ReviewItem(BaseModel):
    shop_id: UUID
    shop_name: str
    sku_id: UUID
    title: str
    brand: str | None
    reason: str | None
    updated_at: datetime


class ReviewList(BaseModel):
    items: list[ReviewItem]


class LinkDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_id: UUID | None = None  # mavjud umumiy mahsulotga bog'lash
    create: CanonicalIn | None = None  # yangisini yaratib bog'lash
    unlink: bool = False


class CanonicalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str | None = Field(default=None, max_length=100)
    mpn: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=2, max_length=300)
    category_code: str = Field(min_length=1, max_length=40)


class CanonicalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand: str | None
    mpn_norm: str | None
    title: str
    category_code: str
    status: str
    source: str


class CanonicalList(BaseModel):
    items: list[CanonicalOut]


LinkDecisionIn.model_rebuild()
