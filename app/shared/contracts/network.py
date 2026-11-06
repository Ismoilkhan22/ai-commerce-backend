"""NetworkQueryPort (Stage 3): global qidiruv faqat shu orqali o'qiydi — db/marketplace.md.

Faqat ommaviy ma'lumot: ACTIVE takliflar, ACTIVE shoplar. Har chaqiruv jadvalning o'zidan (kechikadigan indeks
yo'q) — qaytarib olingan taklif hech qachon chiqmaydi (BR-X07, TC-015).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

MarketSort = Literal["relevance", "price_asc", "price_desc"]


@dataclass(frozen=True)
class MarketOffer:
    offer_id: UUID
    shop_id: UUID
    shop_name: str
    shop_slug: str
    shop_verified: bool  # M29: amaldagi "Tasdiqlangan do'kon" belgisi bor
    canonical_id: UUID | None
    title: str
    brand: str | None
    category_code: str
    price_uzs_minor: int | None  # `permitted_fields` da `price` yo'q bo'lsa — None
    condition: str | None
    warranty_months: int | None
    availability: str | None
    last_verified_at: datetime


@dataclass(frozen=True)
class MarketResult:
    """Qidiruv natijasi: umumiy mahsulot (bir nechta shop takliflari) yoki bog'lanmagan yakka taklif."""

    canonical_id: UUID | None
    title: str
    brand: str | None
    category_code: str
    offers_count: int
    in_stock_count: int
    min_price_uzs_minor: int | None
    max_price_uzs_minor: int | None
    offer: MarketOffer | None  # yakka taklif yoki eng arzon taklif (yorliqsiz, BL-092)


@dataclass(frozen=True)
class MarketProduct:
    canonical_id: UUID
    title: str
    brand: str | None
    category_code: str
    offers: tuple[MarketOffer, ...]  # narx bo'yicha


@dataclass(frozen=True)
class VisitTarget:
    offer_id: UUID
    shop_id: UUID
    shop_slug: str
    product_id: UUID | None


class NetworkQueryPort(Protocol):
    async def search(
        self,
        db: AsyncSession,
        *,
        q: str | None,
        category: str | None,
        max_price_uzs_minor: int | None,
        in_stock: bool,
        sort: MarketSort,
        limit: int,
    ) -> list[MarketResult]: ...

    async def product(self, db: AsyncSession, canonical_id: UUID) -> MarketProduct | None: ...

    async def visit_target(self, db: AsyncSession, offer_id: UUID) -> VisitTarget | None:
        """Taklif hozir ACTIVE va shop ACTIVE bo'lsa — yo'naltirish manzili uchun (read-time deny)."""
        ...
