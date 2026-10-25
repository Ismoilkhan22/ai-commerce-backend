"""StockQueryPort implementatsiyasi (app/shared/contracts/commerce.py). Ulanish — app/dependencies.py.

Faqat sotuvga mavjud son va holat; faqat chiqarilgan va faol SKU'lar (CatalogQueryPort orqali tekshiriladi).
Faol filiallar bo'yicha jami; olib ketish joylari alohida (sayt mahsulot sahifasi, DEC-135).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import load_policy
from app.domains.commerce.inventory.models.orm import StockBalance
from app.domains.commerce.orders.models.orm import Order
from app.platform.shops.models.orm import Branch
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import (
    OPEN_ORDER_STATUSES,
    BranchAvailability,
    SkuAvailability,
    StockDisplayPolicy,
    stock_status,
)
from app.shared.db.session import set_shop_context


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
