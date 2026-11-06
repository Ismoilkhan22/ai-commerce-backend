"""Narx ro'yxati DTO'lari (DEC-149, 1-qism)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.money import Currency

RunStatus = Literal["READING", "READY", "APPLIED", "FAILED", "CANCELLED"]
MatchMethod = Literal["CODE", "AI", "MANUAL", "NONE"]
UzsRound = Literal[100, 10000, 100000, 1000000]


class PriceListCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    supplier_name: str | None = Field(default=None, max_length=120)
    markup_percent: Decimal = Field(default=Decimal(0), ge=0, le=500, decimal_places=2)


class PriceListSettingsIn(BaseModel):
    """Ustama va yaxlitlash — o'zgarsa taklif narxlari qayta hisoblanadi (ega yozgan narxlar saqlanadi)."""

    model_config = ConfigDict(extra="forbid")

    markup_percent: Decimal | None = Field(default=None, ge=0, le=500, decimal_places=2)
    uzs_round_minor: UzsRound | None = None


class PriceListItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected: bool | None = None
    sku_id: UUID | None = None  # qo'lda moslash
    unmatch: bool = False  # moslashni olib tashlash
    proposed_amount_minor: int | None = Field(default=None, ge=1, le=10**15)


class PriceListItemOut(BaseModel):
    id: UUID
    line_no: int
    name: str
    code: str | None
    supplier_price_minor: int
    currency: Currency
    sku_id: UUID | None
    sku_title: str | None
    sku_code: str | None
    match_method: MatchMethod
    current_amount_minor: int | None
    current_currency: Currency | None
    proposed_amount_minor: int | None
    proposed_currency: Currency | None
    manual_price: bool
    changed: bool  # taklif joriy narxdan farq qiladi
    selected: bool
    result: str | None
    error_code: str | None


class PriceListOut(BaseModel):
    id: UUID
    version: int
    status: RunStatus
    source_format: str
    supplier_name: str | None
    markup_percent: Decimal
    uzs_round_minor: int
    item_count: int
    matched_count: int
    selected_count: int
    applied_count: int
    error_code: str | None
    created_at: datetime
    applied_at: datetime | None
    items: list[PriceListItemOut] = []


class PriceListSummary(BaseModel):
    id: UUID
    status: RunStatus
    supplier_name: str | None
    item_count: int
    matched_count: int
    applied_count: int
    created_at: datetime


class PriceListList(BaseModel):
    items: list[PriceListSummary]
