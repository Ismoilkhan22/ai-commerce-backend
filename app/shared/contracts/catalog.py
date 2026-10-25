"""CatalogQueryPort — boshqa domenlar (commerce, sales_ai) katalogdan narx va SKU'ni shu orqali o'qiydi.

Buyurtma qoralamasida narx nusxasi olinadi, tasdiqlashda esa joriy narx shu port orqali sinxron, keshsiz
o'qilib solishtiriladi (12 §5.1, DEC-127, DEC-134). `catalog` kodini import qilish — TAQIQ (ADR-032).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.money import Currency


@dataclass(frozen=True)
class SkuSnapshot:
    sku_id: UUID
    product_id: UUID
    title: str  # mahsulot nomi + variant: "MSI GeForce RTX 4060 Ventus 2X · 8 GB"
    sku_code: str
    sellable: bool  # mahsulot saytda chiqarilgan va SKU faol
    product_status: str  # DRAFT | PUBLISHED | HIDDEN | ARCHIVED (FSM-02)
    sku_status: str  # ACTIVE | ARCHIVED
    warranty_months: int | None
    price_version_id: UUID | None
    amount_minor: int | None
    currency: Currency | None
    exchange_rate_id: UUID | None  # dollar narxi bo'lsa — qaysi kurs bilan o'girildi
    exchange_rate: Decimal | None
    exchange_rate_effective_at: datetime | None
    exchange_rate_stale: bool  # dollar narxi va kurs 3 kundan eski — yakuniy narx berilmaydi (BL-018)
    uzs_amount_minor: int | None  # xaridor ko'radigan narx (tiyinda), yaxlitlanmaydi (DEC-133)
    product_title: str = ""  # tanlash ro'yxati uchun nom va variant alohida
    variant_name: str | None = None


class CatalogQueryPort(Protocol):
    async def get_skus(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuSnapshot]:
        """Shu shopning SKU'lari joriy narx bilan. Boshqa shopniki yoki yo'q SKU natijada bo'lmaydi."""
        ...

    async def search_sku_ids(self, db: AsyncSession, shop_id: UUID, q: str, limit: int) -> list[UUID]:
        """Matn bo'yicha SKU'lar (nom, brend, SKU kodi, MPN) — boshqa domen ro'yxatini filtrlash uchun."""
        ...

    async def pick_sku_ids(self, db: AsyncSession, shop_id: UUID, q: str | None, limit: int) -> list[UUID]:
        """Tanlash ro'yxati (buyurtma qatori, tez sotuv): arxivda bo'lmagan SKU'lar, matn bo'lsa — mos
        kelganlari, bo'lmasa — eng yangilari."""
        ...
