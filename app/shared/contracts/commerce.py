"""StockQueryPort — boshqa domenlar (storefront, sales_ai) mavjudlikni shu orqali o'qiydi (ADR-032).

Faqat **sotuvga mavjud** son (qoldiq − band − ajratilgan, BL-019) va shundan chiqqan holat: aniq qoldiq,
band va ombor tafsiloti tashqariga chiqmaydi. Faqat saytda chiqarilgan va faol SKU'lar qaytadi — boshqasi
natijada yo'q (yashirilgan mahsulot haqida "bor" deyilmaydi). `commerce` kodini import qilish — TAQIQ.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

StockStatus = Literal["IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"]


def stock_status(available: int, low_stock_threshold: int) -> StockStatus:
    """ "Bor / kam qoldi / yo'q" (DEC-128): `low_stock_threshold` dan kam bo'lsa — "kam qoldi" (08 §4.5)."""
    if available <= 0:
        return "OUT_OF_STOCK"
    return "LOW_STOCK" if available < low_stock_threshold else "IN_STOCK"


@dataclass(frozen=True)
class BranchAvailability:
    branch_id: UUID
    available: int
    status: StockStatus


@dataclass(frozen=True)
class SkuAvailability:
    sku_id: UUID
    available: int  # hamma faol filiallar bo'yicha jami
    status: StockStatus
    # Faqat faol va olib ketish joyi bo'lgan filiallar (sayt mahsulot sahifasi, DEC-135)
    pickup_branches: tuple[BranchAvailability, ...]


@dataclass(frozen=True)
class StockDisplayPolicy:
    stock_display: Literal["EXACT", "STATUS_ONLY"]  # DEC-128: saytda aniq son yoki faqat holat
    low_stock_threshold: int


class StockQueryPort(Protocol):
    async def availability(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuAvailability]:
        """Chiqarilgan va faol SKU'lar mavjudligi. Qoldiq qatori yo'q SKU — 0 (OUT_OF_STOCK)."""
        ...

    async def display_policy(self, db: AsyncSession, shop_id: UUID) -> StockDisplayPolicy: ...


# Hali yakunlanmagan buyurtma holatlari: shop yopilishidan oldin oxiriga yetkazilishi kerak (FSM-01, TC-023)
OPEN_ORDER_STATUSES = ("PENDING_CONFIRMATION", "CONFIRMED", "PROCESSING", "EXCEPTION")


class OrderQueryPort(Protocol):
    async def open_order_counts(self, db: AsyncSession, shop_id: UUID) -> dict[str, int]:
        """Ochiq buyurtmalar soni holat bo'yicha (faqat noldan kattalari). Tranzaksiyaga shu shop
        konteksti o'rnatiladi (RLS)."""
        ...
