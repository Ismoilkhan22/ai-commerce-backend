"""Narx tarixi va shop kursi API kontrakti (11 §9.3, DEC-121)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.shared.money import MAX_RATE, Currency

RATE_EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)


class PriceHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount_minor: int
    currency: Currency
    source: Literal["MANUAL", "IMPORT"]
    reason: str | None
    created_by: UUID | None
    created_at: datetime


class PriceHistory(BaseModel):
    items: list[PriceHistoryItem]


class ExchangeRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: Decimal = Field(
        ge=Decimal("0.000001"), le=MAX_RATE, decimal_places=6, description='1 dollar necha so\'m: "12800.00"'
    )
    # Vaqt mintaqasi bilan (11 §3): "2026-10-25T09:00:00Z" yoki "+05:00". Mintaqasiz vaqt — 422
    effective_at: AwareDatetime | None = Field(
        default=None, ge=RATE_EARLIEST, description="Bo'sh bo'lsa — hozirdan"
    )


class ExchangeRateOut(BaseModel):
    id: UUID
    base: Literal["USD"]
    quote: Literal["UZS"]
    rate: Decimal  # matn sifatida qaytadi ("12800.000000") — aniqlik yo'qolmaydi
    source: Literal["MANUAL", "CBU"]
    effective_at: datetime
    created_at: datetime
    is_stale: bool  # 3 kundan eski — yangi taklif berilmaydi (BL-018, 3-modul)


class ExchangeRateList(BaseModel):
    current: ExchangeRateOut | None
    items: list[ExchangeRateOut]  # tarix, yangisi birinchi
    max_age_hours: int
