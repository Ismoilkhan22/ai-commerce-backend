"""Tannarx: shop × SKU o'rtacha tortilgan narx, so'mda (DEC-146, db/commerce_cost_price.md).

Faqat ega ko'radi va kiritadi (`commerce.cost.view` / `commerce.cost.edit`). O'rtacha faqat tannarxli kirim
yoki qo'lda to'g'rilash bilan o'zgaradi — sotuv, band va tuzatish unga tegmaydi. Sotuv paytida o'rtacha qator
nusxasiga yoziladi (`current_unit_costs`) va foyda shu bilan muzlaydi.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce import permissions as perm
from app.domains.commerce.common import (
    cursor_time,
    cursor_uuid,
    field,
    make_cursor,
    member_names,
    read_cursor,
)
from app.domains.commerce.inventory.models.orm import (
    SkuCost,
    SkuCostChange,
    StockBalance,
    StockReceiptCost,
)
from app.domains.commerce.inventory.schemas import (
    MAX_UNIT_COST_MINOR,
    ReceiptLineIn,
    SkuCostChangeOut,
    SkuCostHistory,
    SkuCostList,
    SkuCostOut,
    SkuCostSetIn,
)
from app.domains.commerce.schemas import member_ref
from app.platform.audit.services.audit_service import AuditService
from app.shared.contracts.catalog import CatalogQueryPort, RateSnapshot
from app.shared.errors.base import ForbiddenError, NotFoundError, ValidationError
from app.shared.money import MAX_SAFE_MINOR, to_uzs_minor
from app.shared.types.actor import ActorContext

ENTITY = "commerce.sku_cost"


@dataclass(frozen=True)
class CostEntry:
    """Bitta kirimdagi bitta SKU'ning tannarxi (qatorlar birlashtirilgan)."""

    sku_id: UUID
    qty: int
    unit_cost_minor: int
    currency: str
    rate: RateSnapshot | None
    unit_cost_uzs_minor: int


def weighted_average(old_avg: int, old_qty: int, in_cost: int, in_qty: int) -> int:
    """(eski × B + yangi × q) / (B + q), eng yaqin butun tiyinga (0.5 yuqoriga). B = 0 bo'lsa — yangi narx."""
    if old_qty <= 0:
        return in_cost
    numerator = old_avg * old_qty + in_cost * in_qty
    denominator = old_qty + in_qty
    return (2 * numerator + denominator) // (2 * denominator)


def _weighted(pairs: Sequence[tuple[int, int]]) -> int:
    """Bir SKU'ning bir necha qatori: miqdor bo'yicha tortilgan o'rtacha narx."""
    qty = sum(q for _, q in pairs)
    return (2 * sum(c * q for c, q in pairs) + qty) // (2 * qty)


async def current_unit_costs(db: AsyncSession, shop_id: UUID, sku_ids: Iterable[UUID]) -> dict[UUID, int]:
    """Sotuv nusxasi uchun: SKU → joriy o'rtacha. Qator yo'q SKU natijada bo'lmaydi (noma'lum)."""
    wanted = list(set(sku_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(SkuCost.sku_id, SkuCost.avg_unit_cost_uzs_minor).where(
            SkuCost.shop_id == shop_id, SkuCost.sku_id.in_(wanted)
        )
    )
    return {sku_id: int(avg) for sku_id, avg in rows}


class CostService:
    def __init__(self, audit: AuditService, catalog: CatalogQueryPort) -> None:
        self.audit = audit
        self.catalog = catalog

    # ================================================================== kirim
    @staticmethod
    def require_edit(actor: ActorContext) -> None:
        if perm.COST_EDIT not in actor.permissions:
            raise ForbiddenError("Permission denied", permission=perm.COST_EDIT)

    async def entries_for_receipt(
        self, db: AsyncSession, actor: ActorContext, lines: Sequence[ReceiptLineIn]
    ) -> list[CostEntry]:
        """Kirim qatorlaridagi tannarxni tekshiradi, SKU bo'yicha birlashtiradi. Tannarx yo'q — bo'sh.
        Dollar tannarxi shopning joriy kursi bilan so'mga o'giriladi (eski kurs bloklanmaydi)."""
        assert actor.shop_id is not None
        if all(line.unit_cost_minor is None for line in lines):
            return []
        self.require_edit(actor)
        rate = (
            await self.catalog.current_rate(db, actor.shop_id)
            if any(line.cost_currency == "USD" and line.unit_cost_minor is not None for line in lines)
            else None
        )
        by_sku: dict[UUID, list[tuple[int, ReceiptLineIn]]] = {}
        for index, line in enumerate(lines):
            by_sku.setdefault(line.sku_id, []).append((index, line))
        problems: list[dict[str, Any]] = []
        entries: list[CostEntry] = []
        for sku_id, group in by_sku.items():
            missing = [i for i, line in group if line.unit_cost_minor is None]
            if missing:  # bir SKU'ning ba'zi qatorlari tannarxli, ba'zilari yo'q — noaniq
                problems.append(field(f"lines[{missing[0]}].unit_cost_minor", "required"))
                continue
            if len({line.cost_currency for _, line in group}) > 1:
                problems.append(field(f"lines[{group[1][0]}].cost_currency", "mismatch"))
                continue
            currency = group[0][1].cost_currency
            if currency == "USD" and rate is None:
                problems.append(field(f"lines[{group[0][0]}].cost_currency", "no_exchange_rate"))
                continue
            converted: list[tuple[int, int]] = []
            original: list[tuple[int, int]] = []
            for index, line in group:
                assert line.unit_cost_minor is not None
                uzs = to_uzs_minor(line.unit_cost_minor, currency, rate.rate if rate else None)
                if uzs is None or uzs <= 0 or uzs > MAX_UNIT_COST_MINOR or uzs * line.qty > MAX_SAFE_MINOR:
                    problems.append(field(f"lines[{index}].unit_cost_minor", "max_value"))
                    break
                converted.append((uzs, line.qty))
                original.append((line.unit_cost_minor, line.qty))
            else:
                entries.append(
                    CostEntry(
                        sku_id=sku_id,
                        qty=sum(line.qty for _, line in group),
                        unit_cost_minor=_weighted(original),
                        currency=currency,
                        rate=rate if currency == "USD" else None,
                        unit_cost_uzs_minor=_weighted(converted),
                    )
                )
        if problems:
            raise ValidationError("Invalid cost", fields=problems)
        return entries

    async def basis_qty(self, db: AsyncSession, shop_id: UUID, sku_ids: Iterable[UUID]) -> dict[UUID, int]:
        """Hamma filialdagi qoldiq + tekshiruvdagilar (o'rtacha hisobi uchun B)."""
        wanted = list(set(sku_ids))
        if not wanted:
            return {}
        rows = await db.execute(
            select(StockBalance.sku_id, func.sum(StockBalance.on_hand + StockBalance.quarantine_qty))
            .where(StockBalance.shop_id == shop_id, StockBalance.sku_id.in_(wanted))
            .group_by(StockBalance.sku_id)
        )
        return {sku_id: int(total or 0) for sku_id, total in rows}

    async def record_receipt(
        self,
        db: AsyncSession,
        actor: ActorContext,
        receipt_id: UUID,
        entries: Sequence[CostEntry],
        basis: dict[UUID, int],
    ) -> None:
        """Kirim tranzaksiyasida: tannarx qatori, yangi o'rtacha, tarix. `basis` — kirimdan OLDINGI qoldiq."""
        assert actor.shop_id is not None and actor.membership_id is not None
        for entry in sorted(entries, key=lambda e: e.sku_id):
            line_cost = StockReceiptCost(
                shop_id=actor.shop_id,
                receipt_id=receipt_id,
                sku_id=entry.sku_id,
                qty=entry.qty,
                unit_cost_minor=entry.unit_cost_minor,
                cost_currency=entry.currency,
                exchange_rate_id=entry.rate.rate_id if entry.rate else None,
                exchange_rate_snapshot=entry.rate.rate if entry.rate else None,
                unit_cost_uzs_minor=entry.unit_cost_uzs_minor,
                entered_by=actor.membership_id,
            )
            db.add(line_cost)
            await db.flush()
            before = basis.get(entry.sku_id, 0)
            await self._write(
                db,
                actor,
                entry.sku_id,
                "RECEIPT",
                before_qty=before,
                incoming_qty=entry.qty,
                incoming_cost=entry.unit_cost_uzs_minor,
                ref_id=line_cost.id,
                note=None,
            )

    # ================================================================== qo'lda
    async def set_manual(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, data: SkuCostSetIn
    ) -> SkuCostOut:
        """Tizimgacha bo'lgan qoldiq yoki xato o'rtachani qo'lda qo'yish. Izoh majburiy (`MANUAL_SET`)."""
        assert actor.shop_id is not None
        if sku_id not in await self.catalog.get_skus(db, actor.shop_id, [sku_id]):
            raise NotFoundError("SKU not found")
        basis = (await self.basis_qty(db, actor.shop_id, [sku_id])).get(sku_id, 0)
        await self._write(
            db,
            actor,
            sku_id,
            "MANUAL_SET",
            before_qty=basis,
            incoming_qty=None,
            incoming_cost=None,
            ref_id=None,
            note=data.reason,
            set_to=data.avg_unit_cost_uzs_minor,
        )
        return await self.get(db, actor, sku_id)

    async def _write(
        self,
        db: AsyncSession,
        actor: ActorContext,
        sku_id: UUID,
        reason: str,
        *,
        before_qty: int,
        incoming_qty: int | None,
        incoming_cost: int | None,
        ref_id: UUID | None,
        note: str | None,
        set_to: int | None = None,
    ) -> None:
        """`sku_costs` qatorini qulflab yangilaydi (yo'q bo'lsa ochadi) va tarixga yozadi."""
        assert actor.shop_id is not None and actor.membership_id is not None
        first_value = set_to if set_to is not None else incoming_cost
        assert first_value is not None
        basis_after = before_qty + (incoming_qty or 0)
        inserted = (
            await db.execute(
                insert(SkuCost)
                .values(
                    shop_id=actor.shop_id,
                    sku_id=sku_id,
                    avg_unit_cost_uzs_minor=first_value,
                    basis_qty=basis_after,
                    cost_version=1,
                    last_reason=reason,
                    version=1,
                )
                .on_conflict_do_nothing()
                .returning(SkuCost.sku_id)
            )
        ).first()
        avg_before: int | None = None
        if inserted is not None:
            avg_after = first_value
        else:
            row = (
                await db.execute(
                    select(SkuCost)
                    .where(SkuCost.shop_id == actor.shop_id, SkuCost.sku_id == sku_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            avg_before = row.avg_unit_cost_uzs_minor
            avg_after = (
                set_to
                if set_to is not None
                else weighted_average(avg_before, before_qty, first_value, incoming_qty or 0)
            )
            row.avg_unit_cost_uzs_minor = avg_after
            row.basis_qty = basis_after
            row.cost_version += 1
            row.last_reason = reason
        db.add(
            SkuCostChange(
                shop_id=actor.shop_id,
                sku_id=sku_id,
                reason=reason,
                ref_id=ref_id,
                avg_before_uzs_minor=avg_before,
                avg_after_uzs_minor=avg_after,
                basis_qty=basis_after,
                incoming_qty=incoming_qty,
                incoming_unit_cost_uzs_minor=incoming_cost,
                note=note,
                actor_membership_id=actor.membership_id,
            )
        )
        await db.flush()
        await self.audit.record(
            db,
            action="commerce.cost.changed",
            entity_type=ENTITY,
            entity_id=sku_id,
            actor=actor,
            diff={"reason": reason, "before": avg_before, "after": avg_after},
        )

    # ================================================================== o'qish
    async def get(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> SkuCostOut:
        row = (
            await db.execute(
                select(SkuCost)
                .where(SkuCost.shop_id == actor.shop_id, SkuCost.sku_id == sku_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Cost is not known for this SKU")
        return (await self._out(db, actor, [row]))[0]

    async def list_costs(
        self, db: AsyncSession, actor: ActorContext, *, limit: int, cursor: str | None
    ) -> SkuCostList:
        query = select(SkuCost).where(SkuCost.shop_id == actor.shop_id)
        if cursor:
            raw = read_cursor(cursor, "skucost", ("id",))
            query = query.where(SkuCost.sku_id > cursor_uuid(raw["id"]))
        rows = list((await db.execute(query.order_by(SkuCost.sku_id).limit(limit + 1))).scalars())
        page, has_more = rows[:limit], len(rows) > limit
        next_cursor = make_cursor("skucost", id=page[-1].sku_id) if has_more and page else None
        return SkuCostList(items=await self._out(db, actor, page), next_cursor=next_cursor, has_more=has_more)

    async def history(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, *, limit: int, cursor: str | None
    ) -> SkuCostHistory:
        assert actor.shop_id is not None
        query = select(SkuCostChange).where(
            SkuCostChange.shop_id == actor.shop_id, SkuCostChange.sku_id == sku_id
        )
        if cursor:
            raw = read_cursor(cursor, "costchange", ("t", "id"))
            after = (cursor_time(raw["t"]), cursor_uuid(raw["id"]))
            query = query.where(tuple_(SkuCostChange.created_at, SkuCostChange.id) < after)
        rows = list(
            (
                await db.execute(
                    query.order_by(SkuCostChange.created_at.desc(), SkuCostChange.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        names = await member_names(db, actor.shop_id, (c.actor_membership_id for c in page))
        items = [
            SkuCostChangeOut(
                id=c.id,
                reason=c.reason,
                ref_id=c.ref_id,
                avg_before_uzs_minor=c.avg_before_uzs_minor,
                avg_after_uzs_minor=c.avg_after_uzs_minor,
                basis_qty=c.basis_qty,
                incoming_qty=c.incoming_qty,
                incoming_unit_cost_uzs_minor=c.incoming_unit_cost_uzs_minor,
                note=c.note,
                actor=member_ref(c.actor_membership_id, names),
                created_at=c.created_at,
            )
            for c in page
        ]
        next_cursor = (
            make_cursor("costchange", t=page[-1].created_at, id=page[-1].id) if has_more and page else None
        )
        return SkuCostHistory(items=items, next_cursor=next_cursor, has_more=has_more)

    async def _out(self, db: AsyncSession, actor: ActorContext, rows: Sequence[SkuCost]) -> list[SkuCostOut]:
        assert actor.shop_id is not None
        skus = await self.catalog.get_skus(db, actor.shop_id, [r.sku_id for r in rows])
        return [
            SkuCostOut(
                sku_id=r.sku_id,
                sku_code=skus[r.sku_id].sku_code if r.sku_id in skus else None,
                title=skus[r.sku_id].title if r.sku_id in skus else None,
                avg_unit_cost_uzs_minor=r.avg_unit_cost_uzs_minor,
                basis_qty=r.basis_qty,
                cost_version=r.cost_version,
                last_reason=r.last_reason,
                updated_at=r.updated_at,
                version=r.version,
            )
            for r in rows
        ]


__all__ = ["CostEntry", "CostService", "current_unit_costs", "weighted_average"]
