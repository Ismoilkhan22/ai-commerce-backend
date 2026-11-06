"""StockQueryPort implementatsiyasi (app/shared/contracts/commerce.py). Ulanish — app/dependencies.py.

Faqat sotuvga mavjud son va holat; faqat chiqarilgan va faol SKU'lar (CatalogQueryPort orqali tekshiriladi).
Faol filiallar bo'yicha jami; olib ketish joylari alohida (sayt mahsulot sahifasi, DEC-135).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import load_policy
from app.domains.commerce.inventory.models.orm import ImportStockResult, StockBalance
from app.domains.commerce.orders.models.orm import Order
from app.domains.commerce.orders.schemas import OrderCreate
from app.domains.commerce.orders.services.order_service import OrderService
from app.platform.shops.models.orm import Branch
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import (
    OPEN_ORDER_STATUSES,
    BranchAvailability,
    OrderRef,
    SkuAvailability,
    StockDisplayPolicy,
    stock_status,
)
from app.shared.contracts.imports import ImportStockOutcome, ImportStockResultCode, StockLevel
from app.shared.db.session import set_shop_context
from app.shared.types.actor import ActorContext


class StockQueryPortImpl:
    def __init__(self, catalog: CatalogQueryPort) -> None:
        self.catalog = catalog

    async def availability(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuAvailability]:
        if not sku_ids:
            return {}
        snapshots = await self.catalog.get_skus(db, shop_id, list(sku_ids))
        sellable = [sku_id for sku_id, snap in snapshots.items() if snap.sellable]
        if not sellable:
            return {}
        threshold = (await load_policy(db, shop_id)).low_stock_threshold
        rows = await db.execute(
            select(StockBalance, Branch.is_pickup_point)
            .join(Branch, (Branch.shop_id == StockBalance.shop_id) & (Branch.id == StockBalance.branch_id))
            .where(
                StockBalance.shop_id == shop_id, StockBalance.sku_id.in_(sellable), Branch.status == "ACTIVE"
            )
            .order_by(StockBalance.sku_id, StockBalance.branch_id)
        )
        totals: dict[UUID, int] = dict.fromkeys(sellable, 0)
        pickups: dict[UUID, list[BranchAvailability]] = {sku_id: [] for sku_id in sellable}
        for balance, is_pickup in rows:
            available = max(balance.available, 0)
            totals[balance.sku_id] += available
            if is_pickup:
                pickups[balance.sku_id].append(
                    BranchAvailability(balance.branch_id, available, stock_status(available, threshold))
                )
        return {
            sku_id: SkuAvailability(
                sku_id=sku_id,
                available=totals[sku_id],
                status=stock_status(totals[sku_id], threshold),
                pickup_branches=tuple(pickups[sku_id]),
            )
            for sku_id in sellable
        }

    async def display_policy(self, db: AsyncSession, shop_id: UUID) -> StockDisplayPolicy:
        policy = await load_policy(db, shop_id)
        return StockDisplayPolicy(
            stock_display="EXACT" if policy.stock_display == "EXACT" else "STATUS_ONLY",
            low_stock_threshold=policy.low_stock_threshold,
        )


class OrderQueryPortImpl:
    """Platforma shopni yopishdan oldin ochiq buyurtmalarni sanaydi (OrderQueryPort)."""

    async def open_order_counts(self, db: AsyncSession, shop_id: UUID) -> dict[str, int]:
        await set_shop_context(db, shop_id)  # commerce.orders — RLS (FORCE)
        rows = await db.execute(
            select(Order.status, func.count())
            .where(Order.shop_id == shop_id, Order.status.in_(OPEN_ORDER_STATUSES))
            .group_by(Order.status)
        )
        return {status: int(count) for status, count in rows if count}


class ConversationOrdersPortImpl:
    """messaging (5b): suhbatdan buyurtma qoralamasi va bog'lash (ConversationOrdersPort)."""

    def __init__(self, orders: OrderService) -> None:
        self.orders = orders

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
    ) -> OrderRef:
        data = OrderCreate(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_locale=customer_locale if customer_locale in ("uz", "ru", "en") else "uz",
            branch_id=branch_id,
            fulfillment_method=fulfillment_method,
        )
        out = await self.orders.create(
            db, actor, data, conversation_id=conversation_id, customer_ref=customer_ref
        )
        return OrderRef(id=out.id, number=out.number, status=out.status)

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
    ) -> OrderRef:
        order, previous = await self.orders.link_conversation(
            db,
            actor,
            order_id,
            conversation_id,
            customer_ref,
            relink=relink,
            expected_version=expected_version,
        )
        return OrderRef(
            id=order.id,
            number=order.number,
            status=order.status,
            version=order.version,
            previous_conversation_id=previous,
        )

    async def for_conversation(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID
    ) -> list[OrderRef]:
        return [
            OrderRef(id=o.id, number=o.number, status=o.status)
            for o in await self.orders.for_conversation(db, actor, conversation_id)
        ]


class ImportStockResultsImpl:
    """Katalog importi: commerce qo'llagan qoldiq natijasi va joriy qoldiq (catalog hisoboti uchun)."""

    async def results(
        self, db: AsyncSession, shop_id: UUID, batch_id: UUID, sku_ids: Sequence[UUID] | None = None
    ) -> list[ImportStockOutcome]:
        query = select(ImportStockResult).where(
            ImportStockResult.shop_id == shop_id, ImportStockResult.batch_id == batch_id
        )
        if sku_ids is not None:
            if not sku_ids:
                return []
            query = query.where(ImportStockResult.sku_id.in_(sku_ids))
        rows = (await db.execute(query)).scalars()
        return [ImportStockOutcome(r.sku_id, r.branch_id, cast_result(r.result), r.error_code) for r in rows]

    async def current_stock(
        self, db: AsyncSession, shop_id: UUID, keys: Sequence[tuple[UUID, UUID]]
    ) -> dict[tuple[UUID, UUID], int]:
        if not keys:
            return {}
        rows = await db.execute(
            select(StockBalance.sku_id, StockBalance.branch_id, StockBalance.on_hand).where(
                StockBalance.shop_id == shop_id,
                tuple_(StockBalance.sku_id, StockBalance.branch_id).in_(list(set(keys))),
            )
        )
        return {(sku, branch): on_hand for sku, branch, on_hand in rows.all()}

    async def stock_levels(
        self, db: AsyncSession, shop_id: UUID, keys: Sequence[tuple[UUID, UUID]]
    ) -> dict[tuple[UUID, UUID], StockLevel]:
        if not keys:
            return {}
        rows = await db.execute(
            select(
                StockBalance.sku_id,
                StockBalance.branch_id,
                StockBalance.on_hand,
                StockBalance.reserved + StockBalance.allocated,
            ).where(
                StockBalance.shop_id == shop_id,
                tuple_(StockBalance.sku_id, StockBalance.branch_id).in_(list(set(keys))),
            )
        )
        return {(sku, branch): StockLevel(on_hand, held) for sku, branch, on_hand, held in rows.all()}


def cast_result(value: str) -> ImportStockResultCode:
    assert value in ("APPLIED", "NO_CHANGE", "PENDING_APPROVAL", "ERROR")
    return value  # type: ignore[return-value]
