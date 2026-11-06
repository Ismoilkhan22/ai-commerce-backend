"""support kontraktlari (7b, DEC-145): kafolat murojaati sotuv va ombor bilan shu orqali gaplashadi (ADR-032).

`support` kodi `commerce` ni, `commerce` esa `support` ni import qilmaydi. Ombor yozuvi faqat commerce'da
(DEC-126): support tranzaksiyasida port chaqiriladi, commerce `StockService` orqali daftarga yozadi — holat
o'tishi va daftar yozuvi bitta COMMIT'da (yoki ikkalasi ham yo'q).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.types.actor import ActorContext


@dataclass(frozen=True)
class SaleLine:
    """Sotuv qatorining murojaat uchun nusxasi. `customer_phone` — ochiq (faqat xotirada, E.164):
    support uni darhol shifrlab saqlaydi; log, event va audit'ga tushmaydi."""

    source: Literal["ORDER_LINE", "QUICK_SALE_LINE"]
    sale_id: UUID  # order_id | quick_sale_id
    line_id: UUID
    branch_id: UUID | None
    sku_id: UUID
    product_id: UUID | None
    title: str
    sku_code: str
    qty: int
    sold_at: (
        datetime | None
    )  # buyurtma: completed_at (hali topshirilmagan bo'lsa None); tez sotuv: created_at
    warranty_months: int | None  # sotuv paytidagi nusxa (BL-057, DEC-114)
    unit_price_uzs_minor: int | None = (
        None  # sotuv paytidagi dona narxi (so'm, tiyinda) — qaytarish chegarasi
    )
    sale_status: str | None = None  # buyurtma holati (tez sotuvda None)
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_locale: str | None = None
    conversation_id: UUID | None = None
    customer_ref: UUID | None = None


@dataclass(frozen=True)
class CaseStock:
    quarantined: int  # karantinga tushgan
    restocked: int  # sotuvga qaytarilgan (RESTOCK)
    written_off: int  # hisobdan chiqarilgan (WRITE_OFF)
    replacement_issued: int  # almashtirish uchun chiqarilgan (WARRANTY_REPLACEMENT)


class SupportCommercePort(Protocol):
    async def order_line(
        self, db: AsyncSession, shop_id: UUID, order_id: UUID, line_id: UUID
    ) -> SaleLine | None:
        """Shu shopning buyurtma qatori; yo'q bo'lsa `None`."""
        ...

    async def quick_sale_line(
        self, db: AsyncSession, shop_id: UUID, sale_id: UUID, line_id: UUID
    ) -> SaleLine | None: ...

    async def quarantine_returned(
        self, db: AsyncSession, actor: ActorContext, *, case_id: UUID, branch_id: UUID, sku_id: UUID, qty: int
    ) -> None:
        """RETURN_QUARANTINE: qaytgan dona tekshiruvga. Takror chaqiruv xavfsiz."""
        ...

    async def issue_replacement(
        self, db: AsyncSession, actor: ActorContext, *, case_id: UUID, branch_id: UUID, sku_id: UUID, qty: int
    ) -> None:
        """WARRANTY_REPLACEMENT: yangi dona ombordan. Mavjud son yetmasa `InsufficientStockError`."""
        ...

    async def case_stock(self, db: AsyncSession, shop_id: UUID, case_id: UUID) -> CaseStock: ...
