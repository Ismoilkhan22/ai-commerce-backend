"""StockQueryPort — boshqa domenlar (storefront, sales_ai) mavjudlikni shu orqali o'qiydi (ADR-032).

Faqat **sotuvga mavjud** son (qoldiq − band − ajratilgan, BL-019) va shundan chiqqan holat: aniq qoldiq,
band va ombor tafsiloti tashqariga chiqmaydi. Faqat saytda chiqarilgan va faol SKU'lar qaytadi — boshqasi
natijada yo'q (yashirilgan mahsulot haqida "bor" deyilmaydi). `commerce` kodini import qilish — TAQIQ.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.types.actor import ActorContext

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


@dataclass(frozen=True)
class OrderRef:
    id: UUID
    number: int
    status: str
    version: int = 0
    previous_conversation_id: UUID | None = None  # qayta bog'lashda — eski suhbat (last_order_id yangilanadi)


class ConversationOrdersPort(Protocol):
    """messaging (5b) suhbatdan buyurtma qoralamasini shu orqali ochadi va buyurtmani suhbatga bog'laydi.
    Ruxsat va ko'rinish (operator — o'ziniki) commerce'ning o'zida tekshiriladi (10 §6.8)."""

    async def create_draft(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        customer_ref: UUID,
        customer_name: str | None,
        customer_phone: str | None,
        customer_locale: str,
        branch_id: UUID | None,
        fulfillment_method: str,
    ) -> OrderRef: ...

    async def link(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        order_id: UUID,
        conversation_id: UUID,
        customer_ref: UUID,
        relink: bool = False,
        expected_version: int | None = None,
    ) -> OrderRef: ...

    async def for_conversation(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID
    ) -> list[OrderRef]: ...


# ------------------------------------------------------------------ AI sotuvchi qoralamalari (6b)
@dataclass(frozen=True)
class DraftRef:
    kind: Literal["LEAD", "QUOTE", "ORDER"]
    id: UUID
    number: int
    status: str
    label: str  # "L-57" | "T-1042" | "#1042" — model va operator uchun


@dataclass(frozen=True)
class DraftLine:
    sku_id: UUID
    qty: int


class SalesDraftsPort(Protocol):
    """sales_ai (6b) AI tool'lari faqat QORALAMA yaratadi — tasdiqlash, yuborish, chegirma, band qilish yo'q
    (BL-110, DEC-142 Q4). Qoida va narx commerce'ning o'zida (narx katalogdan, mijoz yuborganidan emas).
    Aktor — `AI_AGENT` (ruxsat va ko'rinish commerce'da tekshiriladi)."""

    async def capture_lead(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        requirements: dict[str, Any],
        idempotency_key: str,
    ) -> DraftRef: ...

    async def prepare_quote_draft(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        lines: Sequence[DraftLine],
    ) -> DraftRef: ...

    async def create_order_draft(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        customer_ref: UUID,
        customer_phone: str | None,
        customer_locale: str,
        lines: Sequence[DraftLine],
        fulfillment_method: str,
        branch_id: UUID | None,
    ) -> DraftRef: ...
