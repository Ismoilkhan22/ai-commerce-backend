"""Tez sotuv — peshtaxtadan sotuv qoldiqni darhol kamaytiradi (DEC-123, BL-109, 12 §7).

Faqat **sotuvga mavjud** sondan: mahsulot online buyurtmaga band bo'lsa, sotib bo'lmaydi (TC-027) —
`INSUFFICIENT_AVAILABLE_STOCK`, `details.lines[].reserved` > 0 bo'lsa UI "band qilingan" deydi.
Narx — joriy katalog narxi (xodim kiritmaydi). Kurs eskirgan bo'lsa ham sotuv yoziladi: sotuv allaqachon
bo'lgan, uni yozmaslik qoldiqni buzardi (eskirgan kurs faqat yakuniy narx berishni to'xtatadi, BL-018).
Bekor qilinmaydi — xato bo'lsa tuzatish (+) bilan.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import (
    branch_names,
    cursor_time,
    cursor_uuid,
    ensure_branch_scope,
    field,
    load_branch,
    make_cursor,
    member_names,
    read_cursor,
)
from app.domains.commerce.inventory.services.stock_service import Movement, StockService, shortage
from app.domains.commerce.quick_sales.models.orm import QuickSale, QuickSaleLine
from app.domains.commerce.quick_sales.schemas import (
    QuickSaleIn,
    QuickSaleLineOut,
    QuickSaleList,
    QuickSaleOut,
)
from app.domains.commerce.schemas import member_ref
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.services.sales_gate import ensure_shop_can_sell
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.errors.base import (
    InsufficientStockError,
    NotFoundError,
    ProductNotAvailableError,
    ValidationError,
)
from app.shared.money import MAX_SAFE_MINOR
from app.shared.types.actor import ActorContext

ENTITY = "commerce.quick_sale"
# Saytdan yashirilgan (HIDDEN) mahsulot do'konda sotilaveradi; qoralama va arxivdagi — yo'q
SELLABLE_OFFLINE = frozenset({"PUBLISHED", "HIDDEN"})


class QuickSaleService:
    def __init__(self, audit: AuditService, stock: StockService, catalog: CatalogQueryPort) -> None:
        self.audit = audit
        self.stock = stock
        self.catalog = catalog

    async def create(self, db: AsyncSession, actor: ActorContext, data: QuickSaleIn) -> QuickSaleOut:
        assert actor.shop_id is not None
        await ensure_shop_can_sell(db, actor.shop_id)  # to'xtatilgan shopda yangi savdo yo'q (FSM-01)
        await load_branch(db, actor, data.branch_id)
        quantities: dict[UUID, int] = {}
        for item in data.lines:
            quantities[item.sku_id] = quantities.get(item.sku_id, 0) + item.qty
        snapshots = await self.catalog.get_skus(db, actor.shop_id, list(quantities))
        unknown = [
            field(f"lines[{i}].sku_id", "invalid")
            for i, line in enumerate(data.lines)
            if line.sku_id not in snapshots
        ]
        if unknown:  # boshqa shop SKU'si — xuddi yo'qdek (TC-001)
            raise ValidationError("Unknown SKU", fields=unknown)
        blocked = [
            {"sku_id": sku_id, "product_status": snap.product_status, "sku_status": snap.sku_status}
            for sku_id, snap in snapshots.items()
            if snap.product_status not in SELLABLE_OFFLINE or snap.sku_status != "ACTIVE"
        ]
        if blocked:  # qoralama va arxivdagi mahsulot do'konda ham sotilmaydi (QA F4)
            raise ProductNotAvailableError("Product is not available", lines=blocked)
        no_price = [
            {"sku_id": sku_id, "reason": "NO_PRICE" if snap.price_version_id is None else "NO_RATE"}
            for sku_id, snap in snapshots.items()
            if snap.price_version_id is None or snap.uzs_amount_minor is None
        ]
        if no_price:  # narxsiz yoki kurssiz dollar narxli mahsulotni sotib bo'lmaydi
            raise ProductNotAvailableError("Product has no usable price", lines=no_price)
        balances = await self.stock.lock_balances(
            db, actor.shop_id, [(data.branch_id, s) for s in quantities]
        )
        short = [
            shortage(balances.get((data.branch_id, sku_id)), data.branch_id, sku_id, qty)
            for sku_id, qty in quantities.items()
            if (b := balances.get((data.branch_id, sku_id))) is None or b.available < qty
        ]
        if short:
            raise InsufficientStockError("Insufficient available stock", lines=short)
        lines = []
        for sku_id, qty in quantities.items():
            snap = snapshots[sku_id]
            assert snap.price_version_id and snap.amount_minor and snap.currency and snap.uzs_amount_minor
            lines.append(
                QuickSaleLine(
                    shop_id=actor.shop_id,
                    sku_id=sku_id,
                    title_snapshot=snap.title,
                    sku_code_snapshot=snap.sku_code,
                    qty=qty,
                    price_version_id=snap.price_version_id,
                    unit_price_minor=snap.amount_minor,
                    currency=snap.currency,
                    exchange_rate_snapshot=snap.exchange_rate,
                    unit_price_uzs_minor=snap.uzs_amount_minor,
                    line_total_minor=qty * snap.uzs_amount_minor,
                    warranty_months=snap.warranty_months,  # kafolat nusxasi (BL-057)
                )
            )
        total = sum(sl.line_total_minor for sl in lines)
        if total > MAX_SAFE_MINOR:
            raise ValidationError("Total too large", fields=[field("lines", "max_value")])
        sale = QuickSale(
            shop_id=actor.shop_id, branch_id=data.branch_id, total_minor=total, sold_by=actor.membership_id
        )
        db.add(sale)
        await db.flush()
        for sale_line in lines:
            sale_line.quick_sale_id = sale.id
        db.add_all(lines)
        await db.flush()
        await self.stock.apply(
            db,
            actor,
            [
                Movement(
                    data.branch_id, line.sku_id, "OFFLINE_SALE", "QUICK_SALE", sale.id, on_hand=-line.qty
                )
                for line in lines
            ],
            balances,
        )
        await self.audit.record(
            db,
            action="commerce.quick_sale.created",
            entity_type=ENTITY,
            entity_id=sale.id,
            actor=actor,
            diff={"lines": len(lines), "units": sum(quantities.values())},
        )
        return (await self._out(db, actor, [sale]))[0]

    async def get(self, db: AsyncSession, actor: ActorContext, sale_id: UUID) -> QuickSaleOut:
        sale = (
            await db.execute(
                select(QuickSale).where(QuickSale.id == sale_id, QuickSale.shop_id == actor.shop_id)
            )
        ).scalar_one_or_none()
        if sale is None:
            raise NotFoundError("Quick sale not found")
        ensure_branch_scope(actor, sale.branch_id)
        return (await self._out(db, actor, [sale]))[0]

    async def list_sales(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        branch_id: UUID | None,
        mine: bool,
        limit: int,
        cursor: str | None,
    ) -> QuickSaleList:
        query = select(QuickSale).where(QuickSale.shop_id == actor.shop_id)
        if actor.branch_ids is not None:
            query = query.where(QuickSale.branch_id.in_(actor.branch_ids))
        if branch_id is not None:
            query = query.where(QuickSale.branch_id == branch_id)
        if mine:
            query = query.where(QuickSale.sold_by == actor.membership_id)
        if cursor:
            raw = read_cursor(cursor, "quick_sale", ("t", "id"))
            after = (cursor_time(raw["t"]), cursor_uuid(raw["id"]))
            query = query.where(tuple_(QuickSale.created_at, QuickSale.id) < after)
        rows = list(
            (
                await db.execute(
                    query.order_by(QuickSale.created_at.desc(), QuickSale.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        next_cursor = (
            make_cursor("quick_sale", t=page[-1].created_at, id=page[-1].id) if has_more and page else None
        )
        return QuickSaleList(
            items=await self._out(db, actor, page), next_cursor=next_cursor, has_more=has_more
        )

    async def _out(
        self, db: AsyncSession, actor: ActorContext, sales: Sequence[QuickSale]
    ) -> list[QuickSaleOut]:
        if not sales:
            return []
        for sale in sales:
            await db.refresh(sale)
        rows = await db.execute(
            select(QuickSaleLine)
            .where(
                QuickSaleLine.shop_id == actor.shop_id, QuickSaleLine.quick_sale_id.in_([s.id for s in sales])
            )
            .order_by(QuickSaleLine.title_snapshot, QuickSaleLine.id)
        )
        by_sale: dict[UUID, list[QuickSaleLine]] = {}
        for line in rows.scalars():
            by_sale.setdefault(line.quick_sale_id, []).append(line)
        branches = await branch_names(db, actor.shop_id, (s.branch_id for s in sales))
        names = await member_names(db, actor.shop_id, (s.sold_by for s in sales))
        return [
            QuickSaleOut(
                id=sale.id,
                branch_id=sale.branch_id,
                branch_name=branches.get(sale.branch_id),
                currency="UZS",
                total_minor=sale.total_minor,
                sold_by=member_ref(sale.sold_by, names),
                created_at=sale.created_at,
                lines=[
                    QuickSaleLineOut(
                        sku_id=line.sku_id,
                        title=line.title_snapshot,
                        sku_code=line.sku_code_snapshot,
                        qty=line.qty,
                        unit_price_minor=line.unit_price_minor,
                        currency="USD" if line.currency == "USD" else "UZS",
                        exchange_rate_snapshot=line.exchange_rate_snapshot,
                        unit_price_uzs_minor=line.unit_price_uzs_minor,
                        line_total_minor=line.line_total_minor,
                        warranty_months=line.warranty_months,
                    )
                    for line in by_sale.get(sale.id, [])
                ],
            )
            for sale in sales
        ]
