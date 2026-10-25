"""CatalogQueryPort — boshqa domenlar (commerce, sales_ai) katalogdan narx va SKU'ni shu orqali o'qiydi.

Buyurtma qoralamasida narx nusxasi olinadi, tasdiqlashda esa joriy narx shu port orqali sinxron, keshsiz
o'qilib solishtiriladi (12 §5.1, DEC-127, DEC-134). `catalog` kodini import qilish — TAQIQ (ADR-032).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
    warranty_months: int | None
    price_version_id: UUID | None
    amount_minor: int | None
    currency: Currency | None
    exchange_rate_id: UUID | None  # dollar narxi bo'lsa — qaysi kurs bilan o'girildi
    exchange_rate: Decimal | None
    uzs_amount_minor: int | None  # xaridor ko'radigan narx (tiyinda), yaxlitlanmaydi (DEC-133)


class CatalogQueryPort(Protocol):
    async def get_skus(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuSnapshot]:
        """Shu shopning SKU'lari joriy narx bilan. Boshqa shopniki yoki yo'q SKU natijada bo'lmaydi."""
        ...
