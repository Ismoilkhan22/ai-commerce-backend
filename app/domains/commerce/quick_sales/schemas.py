"""Tez sotuv API kontrakti (DEC-123, db/commerce.md §5–§6): mahsulot + miqdor, narx katalogdan avtomatik."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.commerce.schemas import MemberRef


class QuickSaleLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    qty: int = Field(ge=1, le=1000)


class QuickSaleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    lines: list[QuickSaleLineIn] = Field(min_length=1, max_length=50)


class QuickSaleLineOut(BaseModel):
    id: UUID  # kafolat murojaati shu qatordan ochiladi (7b)
    sku_id: UUID
    title: str
    sku_code: str
    qty: int
    unit_price_minor: int  # asl valyutada
    currency: Literal["UZS", "USD"]
    exchange_rate_snapshot: Decimal | None
    unit_price_uzs_minor: int
    line_total_minor: int  # so'mda
    warranty_months: int | None


class QuickSaleOut(BaseModel):
    id: UUID
    branch_id: UUID
    branch_name: str | None
    currency: Literal["UZS"]
    total_minor: int
    sold_by: MemberRef | None
    created_at: datetime
    lines: list[QuickSaleLineOut]


class QuickSaleList(BaseModel):
    items: list[QuickSaleOut]
    next_cursor: str | None
    has_more: bool
