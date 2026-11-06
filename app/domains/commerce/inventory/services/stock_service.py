"""Ombor: qoldiq o'zgarishi (daftar bilan), kirim, qo'lda tuzatish, ro'yxatlar va solishtirish (S1-05, 12 §6).

Har qoldiq o'zgarishi shu yerdagi `apply()` orqali o'tadi:
qoldiq qatorlari `(branch_id, sku_id)` o'sish tartibida `FOR UPDATE` qulflanadi → yangi qiymatlar tekshiriladi
(hech biri manfiy emas, band + ajratilgan ≤ qoldiq) → qator yangilanadi → daftarga yozuv (o'zgarishdan keyingi
qiymatlar bilan). Bir hujjat bir SKU'ni bir sabab bilan faqat bir marta o'zgartiradi — daftardagi unikal
kalit.
Qulf tartibi hamma joyda bir xil: buyurtma → band → qoldiq (deadlock bo'lmasin, 12 §2).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import (
    branch_names,
    cursor_time,
    cursor_uuid,
    ensure_branch_scope,
    field,
    load_branch,
    load_policy,
    make_cursor,
    member_names,
    read_cursor,
)
from app.domains.commerce.events import stock_changed
from app.domains.commerce.inventory.models.orm import StockAdjustment, StockBalance, StockLedger, StockReceipt
from app.domains.commerce.inventory.schemas import (
    AdjustmentIn,
    AdjustmentList,
    AdjustmentOut,
    EvidenceOut,
    LedgerItem,
    LedgerList,
    ReceiptIn,
    ReceiptLineOut,
    ReceiptList,
    ReceiptListItem,
    ReceiptOut,
    SkuPickItem,
    SkuPickList,
    StockItem,
    StockList,
)
from app.domains.commerce.inventory.services.cost_service import CostService, current_unit_costs
from app.domains.commerce.schemas import member_ref
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import ADJUSTMENT_APPROVAL, REQUESTER_PARAM, TaskService
from app.platform.storage.services.file_service import FileService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort, SkuSnapshot
from app.shared.contracts.commerce import stock_status
from app.shared.errors.base import (
    InsufficientStockError,
    InvalidTransitionError,
    NotFoundError,
    ProductNotAvailableError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

ADJUSTMENT = "commerce.stock_adjustment"
RECEIPT = "commerce.stock_receipt"
SEARCH_LIMIT = 500  # matn qidiruvi — shuncha SKU'gacha
MAX_STOCK = 2**31 - 1  # qoldiq ustunlari INTEGER: oshsa — 500 emas, 422 (QA F3)
Key = tuple[UUID, UUID]  # (branch_id, sku_id)


@dataclass(frozen=True)
class Movement:
    """Bitta qoldiq qatorining o'zgarishi va unga sabab bo'lgan hujjat."""

    branch_id: UUID
    sku_id: UUID
    reason: str
    ref_type: str
    ref_id: UUID
    on_hand: int = 0
    reserved: int = 0
    allocated: int = 0
    quarantine: int = 0

    @property
    def key(self) -> Key:
        return (self.branch_id, self.sku_id)


def shortage(balance: StockBalance | None, branch_id: UUID, sku_id: UUID, requested: int) -> dict[str, Any]:
    """INSUFFICIENT_AVAILABLE_STOCK tafsiloti (11 §6.3). `reserved` > 0 — mahsulot buyurtmaga band
    (BL-109): UI "online buyurtma uchun band qilingan" deydi."""
    return {
        "sku_id": sku_id,
        "branch_id": branch_id,
        "requested": requested,
        "available": balance.available if balance else 0,
        "reserved": (balance.reserved + balance.allocated) if balance else 0,
    }


class StockService:
    def __init__(self, audit: AuditService, files: FileService, catalog: CatalogQueryPort) -> None:
        self.audit = audit
        self.files = files
        self.catalog = catalog
        self.costs = CostService(audit, catalog)
        self.tasks = TaskService()
        self.notifications = NotificationService()

    # ================================================================== yadro
    async def lock_balances(
        self, db: AsyncSession, shop_id: UUID, keys: Iterable[Key], *, create: bool = False
    ) -> dict[Key, StockBalance]:
        """Qoldiq qatorlari doim bir xil tartibda qulflanadi (12 §2). `create` — yo'q qatorni 0 bilan
        ochadi."""
        ordered = sorted(set(keys))
        if not ordered:
            return {}
        if create:
            await db.execute(
                insert(StockBalance)
                .values([{"shop_id": shop_id, "branch_id": b, "sku_id": s, "version": 1} for b, s in ordered])
                .on_conflict_do_nothing()
            )
        rows = await db.execute(
            select(StockBalance)
            .where(
                StockBalance.shop_id == shop_id,
                tuple_(StockBalance.branch_id, StockBalance.sku_id).in_(ordered),
            )
            .order_by(StockBalance.branch_id, StockBalance.sku_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {(b.branch_id, b.sku_id): b for b in rows.scalars()}

    async def apply(
        self,
        db: AsyncSession,
        actor: ActorContext,
        movements: Sequence[Movement],
        balances: dict[Key, StockBalance] | None = None,
        *,
        create: bool = False,
        paths: dict[Key, str] | None = None,
    ) -> list[StockLedger]:
        """`paths` — chegaradan oshganda qaysi maydon xato ko'rsatilsin (`lines[0].qty`, `delta`)."""
        assert actor.shop_id is not None
        if balances is None:
            balances = await self.lock_balances(db, actor.shop_id, (m.key for m in movements), create=create)
        entries: list[StockLedger] = []
        problems: list[dict[str, Any]] = []
        too_big: list[dict[str, Any]] = []
        for move in sorted(movements, key=lambda m: m.key):
            balance = balances.get(move.key)
            if balance is None:
                problems.append(shortage(None, move.branch_id, move.sku_id, -min(move.on_hand, 0)))
                continue
            on_hand = balance.on_hand + move.on_hand
            reserved = balance.reserved + move.reserved
            allocated = balance.allocated + move.allocated
            quarantine = balance.quarantine_qty + move.quarantine
            if max(on_hand, reserved, allocated, quarantine) > MAX_STOCK:
                room = MAX_STOCK - max(balance.on_hand, balance.quarantine_qty)
                path = (paths or {}).get(move.key, "qty")
                too_big.append(field(path, "max_value", max=max(room, 0)))
                continue
            if min(on_hand, reserved, allocated, quarantine) < 0 or reserved + allocated > on_hand:
                requested = max(-move.on_hand, move.reserved, -move.quarantine, 1)
                problems.append(shortage(balance, move.branch_id, move.sku_id, requested))
                continue
            balance.on_hand, balance.reserved, balance.allocated = on_hand, reserved, allocated
            balance.quarantine_qty = quarantine
            entries.append(
                StockLedger(
                    shop_id=actor.shop_id,
                    branch_id=move.branch_id,
                    sku_id=move.sku_id,
                    reason=move.reason,
                    delta_on_hand=move.on_hand,
                    delta_reserved=move.reserved,
                    delta_allocated=move.allocated,
                    delta_quarantine=move.quarantine,
                    on_hand_after=on_hand,
                    reserved_after=reserved,
                    allocated_after=allocated,
                    quarantine_after=quarantine,
                    ref_type=move.ref_type,
                    ref_id=move.ref_id,
                    actor_membership_id=actor.membership_id,
                )
            )
        if too_big:
            raise ValidationError("Stock quantity too large", fields=too_big)
        if problems:  # oxirgi himoya: chaqiruvchi odatda oldinroq aniqroq xato beradi
            raise InsufficientStockError("Insufficient available stock", lines=problems)
        await db.flush()
        db.add_all(entries)
        await db.flush()
        # Sayt keshi, AI qidiruvi va panel signali (05 §8.2) — absolyut qiymatlar bilan
        await stock_changed(db, actor, entries, balances)
        return entries

    # ================================================================== kafolat (7b, DEC-145)
    async def return_to_quarantine(
        self, db: AsyncSession, actor: ActorContext, *, case_id: UUID, branch_id: UUID, sku_id: UUID, qty: int
    ) -> bool:
        """Qaytgan dona tekshiruvga (RETURN_QUARANTINE): sotilgan dona omborga qaytmaydi, shuning uchun
        `on_hand` o'zgarmaydi, faqat `quarantine_qty` +qty. Bir murojaat bir SKU'ni bir marta (daftar kaliti):
        takror chaqiruv hech narsa yozmaydi (`False`)."""
        assert actor.shop_id is not None
        if await self._case_entry(db, actor.shop_id, "RETURN_QUARANTINE", case_id, sku_id) is not None:
            return False
        movement = Movement(
            branch_id, sku_id, "RETURN_QUARANTINE", "SUPPORT_CASE", case_id, on_hand=0, quarantine=qty
        )
        await self.apply(db, actor, [movement], create=True, paths={movement.key: "qty"})
        return True

    async def issue_replacement(
        self, db: AsyncSession, actor: ActorContext, *, case_id: UUID, branch_id: UUID, sku_id: UUID, qty: int
    ) -> bool:
        """Yangi dona xaridorga berildi (WARRANTY_REPLACEMENT): `on_hand` -qty. Sotuvga mavjud son yetmasa —
        `InsufficientStockError` (band mahsulot berilmaydi, BL-019). Takror chaqiruv hech narsa yozmaydi."""
        assert actor.shop_id is not None
        if await self._case_entry(db, actor.shop_id, "WARRANTY_REPLACEMENT", case_id, sku_id) is not None:
            return False
        movement = Movement(branch_id, sku_id, "WARRANTY_REPLACEMENT", "SUPPORT_CASE", case_id, on_hand=-qty)
        balances = await self.lock_balances(db, actor.shop_id, [movement.key])
        balance = balances.get(movement.key)
        if balance is None or balance.available < qty:
            raise InsufficientStockError(
                "Insufficient available stock for the replacement",
                lines=[shortage(balance, branch_id, sku_id, qty)],
            )
        await self.apply(db, actor, [movement], balances, paths={movement.key: "qty"})
        return True

    async def case_stock(self, db: AsyncSession, shop_id: UUID, case_id: UUID) -> dict[str, int]:
        """Murojaat kartochkasi uchun: karantinga tushgan, sotuvga qaytarilgan, hisobdan chiqarilgan va
        almashtirish uchun chiqarilgan sonlar."""
        ledger: dict[str, int] = dict(
            (
                await db.execute(
                    select(
                        StockLedger.reason, func.coalesce(func.sum(func.abs(StockLedger.delta_on_hand)), 0)
                    )
                    .where(
                        StockLedger.shop_id == shop_id,
                        StockLedger.ref_type == "SUPPORT_CASE",
                        StockLedger.ref_id == case_id,
                    )
                    .group_by(StockLedger.reason)
                )
            ).all()
        )
        quarantined = (
            await db.scalar(
                select(func.coalesce(func.sum(StockLedger.delta_quarantine), 0)).where(
                    StockLedger.shop_id == shop_id,
                    StockLedger.ref_type == "SUPPORT_CASE",
                    StockLedger.ref_id == case_id,
                    StockLedger.reason == "RETURN_QUARANTINE",
                )
            )
            or 0
        )
        done = dict(
            (
                await db.execute(
                    select(StockAdjustment.kind, func.coalesce(func.sum(StockAdjustment.delta), 0))
                    .where(
                        StockAdjustment.shop_id == shop_id,
                        StockAdjustment.support_case_id == case_id,
                        StockAdjustment.status == "APPROVED",
                    )
                    .group_by(StockAdjustment.kind)
                )
            ).all()
        )
        return {
            "quarantined": int(quarantined),
            "restocked": int(done.get("RESTOCK", 0)),
            "written_off": int(done.get("WRITE_OFF", 0)),
            "replacement_issued": int(ledger.get("WARRANTY_REPLACEMENT", 0)),
        }

    @staticmethod
    async def _case_entry(
        db: AsyncSession, shop_id: UUID, reason: str, case_id: UUID, sku_id: UUID
    ) -> UUID | None:
        return await db.scalar(
            select(StockLedger.id).where(
                StockLedger.shop_id == shop_id,
                StockLedger.reason == reason,
                StockLedger.ref_type == "SUPPORT_CASE",
                StockLedger.ref_id == case_id,
                StockLedger.sku_id == sku_id,
            )
        )

    async def _check_case_quarantine(self, db: AsyncSession, actor: ActorContext, data: AdjustmentIn) -> None:
        """RESTOCK / WRITE_OFF `support_case_id` bilan: shu murojaat shu SKU'ni shu filialda karantinga
        yozgan bo'lishi va tuzatishlar yig'indisi karantinga tushgandan oshmasligi shart."""
        assert actor.shop_id is not None
        if data.kind not in ("RESTOCK", "WRITE_OFF"):
            raise ValidationError(
                "Only RESTOCK or WRITE_OFF may reference a case", fields=[field("support_case_id", "invalid")]
            )
        quarantined = int(
            await db.scalar(
                select(func.coalesce(func.sum(StockLedger.delta_quarantine), 0)).where(
                    StockLedger.shop_id == actor.shop_id,
                    StockLedger.reason == "RETURN_QUARANTINE",
                    StockLedger.ref_type == "SUPPORT_CASE",
                    StockLedger.ref_id == data.support_case_id,
                    StockLedger.branch_id == data.branch_id,
                    StockLedger.sku_id == data.sku_id,
                )
            )
            or 0
        )
        if quarantined <= 0:
            raise ValidationError(
                "Case has no quarantined unit here", fields=[field("support_case_id", "invalid")]
            )
        used = int(
            await db.scalar(
                select(func.coalesce(func.sum(StockAdjustment.delta), 0)).where(
                    StockAdjustment.shop_id == actor.shop_id,
                    StockAdjustment.support_case_id == data.support_case_id,
                    StockAdjustment.branch_id == data.branch_id,
                    StockAdjustment.sku_id == data.sku_id,
                    StockAdjustment.status.in_(("PENDING", "APPROVED")),
                )
            )
            or 0
        )
        if used + data.delta > quarantined:
            raise InsufficientStockError(
                "Not enough quarantined stock for this case",
                lines=[
                    {
                        "sku_id": data.sku_id,
                        "branch_id": data.branch_id,
                        "requested": data.delta,
                        "available": quarantined - used,
                        "quarantine": quarantined - used,
                    }
                ],
            )

    # ================================================================== qoldiq va daftar
    async def list_balances(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        branch_id: UUID | None,
        sku_id: UUID | None,
        q: str | None,
        low_only: bool,
        limit: int,
        cursor: str | None,
    ) -> StockList:
        assert actor.shop_id is not None
        policy = await load_policy(db, actor.shop_id)
        query = select(StockBalance).where(StockBalance.shop_id == actor.shop_id)
        if actor.branch_ids is not None:
            query = query.where(StockBalance.branch_id.in_(actor.branch_ids))
        if branch_id is not None:
            query = query.where(StockBalance.branch_id == branch_id)
        if sku_id is not None:
            query = query.where(StockBalance.sku_id == sku_id)
        if q and q.strip():
            ids = await self.catalog.search_sku_ids(db, actor.shop_id, q, SEARCH_LIMIT)
            if not ids:
                return StockList(
                    items=[], next_cursor=None, has_more=False, low_stock_threshold=policy.low_stock_threshold
                )
            query = query.where(StockBalance.sku_id.in_(ids))
        if low_only:
            available = StockBalance.on_hand - StockBalance.reserved - StockBalance.allocated
            query = query.where(available < policy.low_stock_threshold)
        if cursor:
            raw = read_cursor(cursor, "stock", ("sku", "br"))
            after = (cursor_uuid(raw["sku"]), cursor_uuid(raw["br"]))
            query = query.where(tuple_(StockBalance.sku_id, StockBalance.branch_id) > after)
        rows = list(
            (
                await db.execute(query.order_by(StockBalance.sku_id, StockBalance.branch_id).limit(limit + 1))
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        skus = await self.catalog.get_skus(db, actor.shop_id, list({b.sku_id for b in page}))
        names = await branch_names(db, actor.shop_id, (b.branch_id for b in page))
        items = []
        for b in page:
            snap = skus.get(b.sku_id)
            items.append(self._stock_item(b, snap, names.get(b.branch_id), policy.low_stock_threshold))
        next_cursor = (
            make_cursor("stock", sku=page[-1].sku_id, br=page[-1].branch_id) if has_more and page else None
        )
        return StockList(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            low_stock_threshold=policy.low_stock_threshold,
        )

    async def pick_skus(
        self, db: AsyncSession, actor: ActorContext, *, q: str | None, branch_id: UUID | None, limit: int
    ) -> SkuPickList:
        """SKU tanlash: bitta so'rovda nom, holat, narx va filialdagi sotuvga mavjud son (frontend 2 ta
        so'rov qilmasin)."""
        assert actor.shop_id is not None
        if branch_id is not None:
            ensure_branch_scope(actor, branch_id)
        ids = await self.catalog.pick_sku_ids(db, actor.shop_id, q, limit)
        snapshots = await self.catalog.get_skus(db, actor.shop_id, ids)
        roles = await self.catalog.sku_spec_categories(db, actor.shop_id, ids)
        balances: dict[UUID, StockBalance] = {}
        policy = await load_policy(db, actor.shop_id)
        if branch_id is not None and ids:
            rows = await db.execute(
                select(StockBalance).where(
                    StockBalance.shop_id == actor.shop_id,
                    StockBalance.branch_id == branch_id,
                    StockBalance.sku_id.in_(ids),
                )
            )
            balances = {b.sku_id: b for b in rows.scalars()}
        items = []
        for sku_id in ids:
            snap = snapshots.get(sku_id)
            if snap is None:
                continue
            priced = snap.price_version_id is not None and snap.uzs_amount_minor is not None
            available = None
            if branch_id is not None:
                balance = balances.get(sku_id)
                available = balance.available if balance else 0
            items.append(
                SkuPickItem(
                    sku_id=snap.sku_id,
                    product_id=snap.product_id,
                    title=snap.title,
                    product_title=snap.product_title or snap.title,
                    variant_name=snap.variant_name,
                    sku_code=snap.sku_code,
                    spec_category=roles.get(sku_id),
                    product_status=snap.product_status,
                    sku_status=snap.sku_status,
                    orderable=snap.sellable and priced,
                    quick_sellable=snap.product_status in ("PUBLISHED", "HIDDEN")
                    and snap.sku_status == "ACTIVE"
                    and priced,
                    currency=snap.currency,
                    amount_minor=snap.amount_minor,
                    uzs_amount_minor=snap.uzs_amount_minor,
                    exchange_rate_stale=snap.exchange_rate_stale,
                    available=available,
                    stock_status=stock_status(available, policy.low_stock_threshold)
                    if available is not None
                    else None,
                )
            )
        return SkuPickList(items=items)

    @staticmethod
    def _stock_item(
        b: StockBalance, snap: SkuSnapshot | None, branch_name: str | None, threshold: int
    ) -> StockItem:
        return StockItem(
            branch_id=b.branch_id,
            branch_name=branch_name,
            sku_id=b.sku_id,
            product_id=snap.product_id if snap else None,
            sku_code=snap.sku_code if snap else None,
            title=snap.title if snap else None,
            on_hand=b.on_hand,
            reserved=b.reserved,
            allocated=b.allocated,
            quarantine_qty=b.quarantine_qty,
            available=b.available,
            stock_status=stock_status(b.available, threshold),
            updated_at=b.updated_at,
            version=b.version,
        )

    async def history(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        sku_id: UUID,
        branch_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> LedgerList:
        """ "Mahsulot tarixi": daftar yozuvlari, yangisi birinchi."""
        query = select(StockLedger).where(StockLedger.shop_id == actor.shop_id, StockLedger.sku_id == sku_id)
        if actor.branch_ids is not None:
            query = query.where(StockLedger.branch_id.in_(actor.branch_ids))
        if branch_id is not None:
            query = query.where(StockLedger.branch_id == branch_id)
        if cursor:
            raw = read_cursor(cursor, "ledger", ("t", "id"))
            after = (cursor_time(raw["t"]), cursor_uuid(raw["id"]))
            query = query.where(tuple_(StockLedger.created_at, StockLedger.id) < after)
        rows = list(
            (
                await db.execute(
                    query.order_by(StockLedger.created_at.desc(), StockLedger.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        names = await member_names(db, actor.shop_id, (r.actor_membership_id for r in page))
        items = [
            LedgerItem(
                id=r.id,
                branch_id=r.branch_id,
                sku_id=r.sku_id,
                reason=r.reason,
                delta_on_hand=r.delta_on_hand,
                delta_reserved=r.delta_reserved,
                delta_allocated=r.delta_allocated,
                delta_quarantine=r.delta_quarantine,
                on_hand_after=r.on_hand_after,
                reserved_after=r.reserved_after,
                allocated_after=r.allocated_after,
                quarantine_after=r.quarantine_after,
                ref_type=r.ref_type,
                ref_id=r.ref_id,
                actor=member_ref(r.actor_membership_id, names),
                created_at=r.created_at,
            )
            for r in page
        ]
        next_cursor = (
            make_cursor("ledger", t=page[-1].created_at, id=page[-1].id) if has_more and page else None
        )
        return LedgerList(items=items, next_cursor=next_cursor, has_more=has_more)

    async def reconcile(self, db: AsyncSession, shop_id: UUID) -> list[dict[str, Any]]:
        """Daftar yig'indisi qoldiq bilan teng ekanini tekshiradi (12 §6.1). Farqlar ro'yxati (bo'sh —
        hammasi joyida). Har kecha `stock_reconcile` rejali ishi chaqiradi: farq bo'lsa — vazifa va alert,
        qoldiq avtomatik tuzatilmaydi (DEC-138, 5-qaror).
        """
        sums = (
            select(
                StockLedger.branch_id,
                StockLedger.sku_id,
                func.sum(StockLedger.delta_on_hand).label("on_hand"),
                func.sum(StockLedger.delta_reserved).label("reserved"),
                func.sum(StockLedger.delta_allocated).label("allocated"),
                func.sum(StockLedger.delta_quarantine).label("quarantine"),
            )
            .where(StockLedger.shop_id == shop_id)
            .group_by(StockLedger.branch_id, StockLedger.sku_id)
            .subquery()
        )
        rows = await db.execute(
            select(StockBalance, sums.c.on_hand, sums.c.reserved, sums.c.allocated, sums.c.quarantine)
            .outerjoin(
                sums, (sums.c.branch_id == StockBalance.branch_id) & (sums.c.sku_id == StockBalance.sku_id)
            )
            .where(StockBalance.shop_id == shop_id)
        )
        mismatches = []
        for balance, on_hand, reserved, allocated, quarantine in rows:
            ledger = (int(on_hand or 0), int(reserved or 0), int(allocated or 0), int(quarantine or 0))
            actual = (balance.on_hand, balance.reserved, balance.allocated, balance.quarantine_qty)
            if ledger != actual:
                mismatches.append(
                    {
                        "branch_id": balance.branch_id,
                        "sku_id": balance.sku_id,
                        "ledger": ledger,
                        "balance": actual,
                    }
                )
        return mismatches

    # ================================================================== kirim
    async def create_receipt(
        self, db: AsyncSession, actor: ActorContext, data: ReceiptIn, *, import_batch_id: UUID | None = None
    ) -> ReceiptOut:
        assert actor.shop_id is not None
        await load_branch(db, actor, data.branch_id)
        quantities: dict[UUID, int] = {}
        for line in data.lines:  # bir SKU ikki marta kelsa — qo'shib yuboriladi (commerce.md §3)
            quantities[line.sku_id] = quantities.get(line.sku_id, 0) + line.qty
        snapshots = await self.catalog.get_skus(db, actor.shop_id, list(quantities))
        self._ensure_known(snapshots, [line.sku_id for line in data.lines], "lines")
        cost_entries = await self.costs.entries_for_receipt(
            db, actor, data.lines
        )  # tannarx: faqat ega (DEC-146)
        receipt = StockReceipt(
            shop_id=actor.shop_id,
            branch_id=data.branch_id,
            note=data.note or None,
            received_by=actor.membership_id,
            import_batch_id=import_batch_id,  # katalog importidan (5c)
        )
        db.add(receipt)
        await db.flush()
        first_line: dict[UUID, str] = {}
        for index, line in enumerate(data.lines):
            first_line.setdefault(line.sku_id, f"lines[{index}].qty")
        movements = [
            Movement(data.branch_id, sku_id, "RECEIPT", "RECEIPT", receipt.id, on_hand=qty)
            for sku_id, qty in quantities.items()
        ]
        paths = {(data.branch_id, sku_id): path for sku_id, path in first_line.items()}
        if cost_entries:
            # O'rtacha kirimdan OLDINGI qoldiq bilan hisoblanadi: avval qoldiq qulflanadi, so'ng B o'qiladi,
            # keyin kirim qo'llanadi va tannarx shu tranzaksiyada yoziladi
            balances = await self.lock_balances(db, actor.shop_id, (m.key for m in movements), create=True)
            basis = await self.costs.basis_qty(db, actor.shop_id, (e.sku_id for e in cost_entries))
            await self.apply(db, actor, movements, balances, paths=paths)
            await self.costs.record_receipt(db, actor, receipt.id, cost_entries, basis)
        else:
            await self.apply(db, actor, movements, create=True, paths=paths)
        await self.audit.record(
            db,
            action="commerce.stock.received",
            entity_type=RECEIPT,
            entity_id=receipt.id,
            actor=actor,
            diff={"lines": len(quantities), "units": sum(quantities.values())},
        )
        return await self.receipt(db, actor, receipt.id)

    async def receipt(self, db: AsyncSession, actor: ActorContext, receipt_id: UUID) -> ReceiptOut:
        receipt = (
            await db.execute(
                select(StockReceipt).where(
                    StockReceipt.id == receipt_id, StockReceipt.shop_id == actor.shop_id
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("Receipt not found")
        ensure_branch_scope(actor, receipt.branch_id)
        entries = list(
            (
                await db.execute(
                    select(StockLedger)
                    .where(
                        StockLedger.shop_id == receipt.shop_id,
                        StockLedger.ref_type == "RECEIPT",
                        StockLedger.ref_id == receipt.id,
                    )
                    .order_by(StockLedger.created_at, StockLedger.id)
                )
            ).scalars()
        )
        skus = await self.catalog.get_skus(db, receipt.shop_id, [e.sku_id for e in entries])
        branches = await branch_names(db, receipt.shop_id, [receipt.branch_id])
        names = await member_names(db, receipt.shop_id, [receipt.received_by])
        return ReceiptOut(
            id=receipt.id,
            branch_id=receipt.branch_id,
            branch_name=branches.get(receipt.branch_id),
            note=receipt.note,
            received_by=member_ref(receipt.received_by, names),
            created_at=receipt.created_at,
            lines=[
                ReceiptLineOut(
                    sku_id=e.sku_id,
                    sku_code=skus[e.sku_id].sku_code if e.sku_id in skus else None,
                    title=skus[e.sku_id].title if e.sku_id in skus else None,
                    qty=e.delta_on_hand,
                    on_hand_after=e.on_hand_after,
                )
                for e in entries
            ],
        )

    async def list_receipts(
        self, db: AsyncSession, actor: ActorContext, *, branch_id: UUID | None, limit: int, cursor: str | None
    ) -> ReceiptList:
        query = select(StockReceipt).where(StockReceipt.shop_id == actor.shop_id)
        if actor.branch_ids is not None:
            query = query.where(StockReceipt.branch_id.in_(actor.branch_ids))
        if branch_id is not None:
            query = query.where(StockReceipt.branch_id == branch_id)
        if cursor:
            raw = read_cursor(cursor, "receipt", ("t", "id"))
            after = (cursor_time(raw["t"]), cursor_uuid(raw["id"]))
            query = query.where(tuple_(StockReceipt.created_at, StockReceipt.id) < after)
        rows = list(
            (
                await db.execute(
                    query.order_by(StockReceipt.created_at.desc(), StockReceipt.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        totals: dict[UUID, tuple[int, int]] = {}
        if page:
            sums = await db.execute(
                select(StockLedger.ref_id, func.count(), func.sum(StockLedger.delta_on_hand))
                .where(
                    StockLedger.shop_id == actor.shop_id,
                    StockLedger.ref_type == "RECEIPT",
                    StockLedger.ref_id.in_([r.id for r in page]),
                )
                .group_by(StockLedger.ref_id)
            )
            totals = {ref_id: (int(count), int(units or 0)) for ref_id, count, units in sums}
        branches = await branch_names(db, actor.shop_id, (r.branch_id for r in page))
        names = await member_names(db, actor.shop_id, (r.received_by for r in page))
        items = [
            ReceiptListItem(
                id=r.id,
                branch_id=r.branch_id,
                branch_name=branches.get(r.branch_id),
                note=r.note,
                received_by=member_ref(r.received_by, names),
                created_at=r.created_at,
                line_count=totals.get(r.id, (0, 0))[0],
                units=totals.get(r.id, (0, 0))[1],
            )
            for r in page
        ]
        next_cursor = (
            make_cursor("receipt", t=page[-1].created_at, id=page[-1].id) if has_more and page else None
        )
        return ReceiptList(items=items, next_cursor=next_cursor, has_more=has_more)

    # ================================================================== tuzatish
    async def create_adjustment(
        self,
        db: AsyncSession,
        actor: ActorContext,
        data: AdjustmentIn,
        *,
        import_batch_id: UUID | None = None,
        target_on_hand: int | None = None,
    ) -> AdjustmentOut:
        """Omborchi — so'rov (PENDING); ega/menejer (`adjust_approve`) — darhol qo'llanadi (DEC-134).
        `target_on_hand` — import tuzatishi: farq tasdiq paytida joriy qoldiqdan qayta hisoblanadi (QA F3)."""
        assert actor.shop_id is not None
        await load_branch(db, actor, data.branch_id)
        if data.kind == "ADJUSTMENT" and data.delta == 0:
            raise ValidationError("Delta must not be zero", fields=[field("delta", "invalid")])
        if data.kind != "ADJUSTMENT" and data.delta <= 0:
            raise ValidationError("Delta must be positive", fields=[field("delta", "min_value", min=1)])
        snapshots = await self.catalog.get_skus(db, actor.shop_id, [data.sku_id])
        self._ensure_known(
            snapshots,
            [data.sku_id],
            None,
            field_name="sku_id",
            allow_archived=self._decreases(data.kind, data.delta),
        )
        if data.evidence_file_id is not None:
            await self._usable_evidence(db, actor, data.evidence_file_id)
        balances = await self.lock_balances(db, actor.shop_id, [(data.branch_id, data.sku_id)], create=True)
        balance = balances[(data.branch_id, data.sku_id)]
        if data.support_case_id is not None:  # soxta murojaat ID'si 422; karantindan ko'p chiqarish 409
            await self._check_case_quarantine(db, actor, data)
        self._check_adjustment(balance, data.kind, data.delta)  # so'rovda ham — imkonsiz so'rov yuborilmasin
        adjustment = StockAdjustment(
            shop_id=actor.shop_id,
            branch_id=data.branch_id,
            sku_id=data.sku_id,
            kind=data.kind,
            delta=data.delta,
            reason=data.reason,
            evidence_file_id=data.evidence_file_id,
            status="PENDING",
            requested_by=actor.membership_id,
            import_batch_id=import_batch_id,  # katalog importi farqi (5c, DEC-140)
            target_on_hand=target_on_hand,
            support_case_id=data.support_case_id,
        )
        db.add(adjustment)
        await db.flush()
        if "commerce.stock.adjust_approve" in actor.permissions:
            await self._apply_adjustment(db, actor, adjustment, balances, None)
            action = "commerce.stock.adjusted"
        else:
            action = "commerce.stock.adjustment_requested"
            await self._request_approval(db, actor, adjustment)
        await self.audit.record(
            db,
            action=action,
            entity_type=ADJUSTMENT,
            entity_id=adjustment.id,
            actor=actor,
            entity_version=adjustment.version,
            reason=data.reason,
            diff={"kind": data.kind, "delta": data.delta},
        )
        return await self._adjustment_out(db, actor, adjustment)

    async def approve_adjustment(
        self,
        db: AsyncSession,
        actor: ActorContext,
        adjustment_id: UUID,
        expected_version: int,
        note: str | None,
    ) -> AdjustmentOut:
        adjustment = await self._pending(db, actor, adjustment_id, expected_version, "APPROVE")
        assert actor.shop_id is not None
        balances = await self.lock_balances(db, actor.shop_id, [(adjustment.branch_id, adjustment.sku_id)])
        balance = balances.get((adjustment.branch_id, adjustment.sku_id))
        unchanged = False
        if adjustment.target_on_hand is not None:
            # Import tuzatishi: maqsad — absolyut qoldiq; farq HOZIRGI qoldiqdan (QA F3). So'rovdan keyin
            # sotuv yoki kirim bo'lgan bo'lsa ham natija fayldagi raqamga teng bo'ladi.
            delta = adjustment.target_on_hand - (balance.on_hand if balance else 0)
            unchanged = delta == 0
            if not unchanged:
                adjustment.delta = delta
        # So'rovdan keyin mahsulot arxivlangan bo'lishi mumkin: oshiruvchi tuzatish endi qo'llanmaydi
        snapshots = await self.catalog.get_skus(db, actor.shop_id, [adjustment.sku_id])
        self._ensure_known(
            snapshots,
            [adjustment.sku_id],
            None,
            allow_archived=unchanged or self._decreases(adjustment.kind, adjustment.delta),
        )
        if unchanged:  # qoldiq allaqachon maqsadda — daftarga yozuv yo'q, tuzatish yopiladi
            current = balance.on_hand if balance else 0
            adjustment.status, adjustment.decided_by = "APPROVED", actor.membership_id
            adjustment.decided_at, adjustment.decision_note = utcnow(), note
            adjustment.on_hand_before = adjustment.on_hand_after = current
            await db.flush()
        else:
            # Qayta tekshiruv: so'rovdan keyin qoldiq o'zgargan bo'lishi mumkin (TC-CON-12)
            self._check_adjustment(balance, adjustment.kind, adjustment.delta)
            await self._apply_adjustment(db, actor, adjustment, balances, note)
        await self._close_approval(db, actor, adjustment)
        await self.audit.record(
            db,
            action="commerce.stock.adjustment_approved",
            entity_type=ADJUSTMENT,
            entity_id=adjustment.id,
            actor=actor,
            entity_version=adjustment.version,
            reason=note,
            diff={"status": {"old": "PENDING", "new": "APPROVED"}},
        )
        return await self._adjustment_out(db, actor, adjustment)

    async def supersede_import_adjustments(
        self, db: AsyncSession, actor: ActorContext, branch_id: UUID, sku_id: UUID, note: str
    ) -> int:
        """Shu SKU+filial uchun kutilayotgan ESKI import tuzatishlari rad etiladi (QA F3): yangi import ularni
        almashtiradi, tasdiqlovchi bir xil ikki so'rovni ko'rmaydi va farqlar ustma-ust qo'shilmaydi."""
        assert actor.shop_id is not None
        stale = list(
            (
                await db.execute(
                    select(StockAdjustment)
                    .where(
                        StockAdjustment.shop_id == actor.shop_id,
                        StockAdjustment.branch_id == branch_id,
                        StockAdjustment.sku_id == sku_id,
                        StockAdjustment.status == "PENDING",
                        StockAdjustment.import_batch_id.is_not(None),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        for adjustment in stale:
            adjustment.status, adjustment.decided_by = "REJECTED", actor.membership_id
            adjustment.decided_at, adjustment.decision_note = utcnow(), note
            await db.flush()
            await self._close_approval(db, actor, adjustment)
            await self.audit.record(
                db,
                action="commerce.stock.adjustment_superseded",
                entity_type=ADJUSTMENT,
                entity_id=adjustment.id,
                actor=actor,
                entity_version=adjustment.version,
                reason=note,
                diff={"status": {"old": "PENDING", "new": "REJECTED"}},
            )
        return len(stale)

    async def reject_adjustment(
        self, db: AsyncSession, actor: ActorContext, adjustment_id: UUID, expected_version: int, note: str
    ) -> AdjustmentOut:
        adjustment = await self._pending(db, actor, adjustment_id, expected_version, "REJECT")
        adjustment.status = "REJECTED"
        adjustment.decided_by = actor.membership_id
        adjustment.decided_at = utcnow()
        adjustment.decision_note = note
        await db.flush()
        await self._close_approval(db, actor, adjustment)
        await self.audit.record(
            db,
            action="commerce.stock.adjustment_rejected",
            entity_type=ADJUSTMENT,
            entity_id=adjustment.id,
            actor=actor,
            entity_version=adjustment.version,
            reason=note,
            diff={"status": {"old": "PENDING", "new": "REJECTED"}},
        )
        return await self._adjustment_out(db, actor, adjustment)

    async def get_adjustment(
        self, db: AsyncSession, actor: ActorContext, adjustment_id: UUID
    ) -> AdjustmentOut:
        adjustment = await self._adjustment(db, actor, adjustment_id)
        return await self._adjustment_out(db, actor, adjustment)

    async def list_adjustments(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        statuses: Sequence[str],
        branch_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> AdjustmentList:
        query = select(StockAdjustment).where(StockAdjustment.shop_id == actor.shop_id)
        if actor.branch_ids is not None:
            query = query.where(StockAdjustment.branch_id.in_(actor.branch_ids))
        if statuses:
            query = query.where(StockAdjustment.status.in_(statuses))
        if branch_id is not None:
            query = query.where(StockAdjustment.branch_id == branch_id)
        if cursor:
            raw = read_cursor(cursor, "adjustment", ("t", "id"))
            after = (cursor_time(raw["t"]), cursor_uuid(raw["id"]))
            query = query.where(tuple_(StockAdjustment.requested_at, StockAdjustment.id) < after)
        rows = list(
            (
                await db.execute(
                    query.order_by(StockAdjustment.requested_at.desc(), StockAdjustment.id.desc()).limit(
                        limit + 1
                    )
                )
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        items = await self._adjustments_out(db, actor, page)
        next_cursor = (
            make_cursor("adjustment", t=page[-1].requested_at, id=page[-1].id) if has_more and page else None
        )
        return AdjustmentList(items=items, next_cursor=next_cursor, has_more=has_more)

    # ================================================================== ichki
    def _ensure_known(
        self,
        snapshots: dict[UUID, SkuSnapshot],
        sku_ids: Sequence[UUID],
        list_name: str | None,
        *,
        field_name: str = "sku_id",
        allow_archived: bool = False,
    ) -> None:
        """SKU shu shopniki (boshqa shop SKU'si — xuddi yo'qdek, TC-001 → 422). Arxivdagi mahsulot yoki
        SKU — 409 `PRODUCT_NOT_AVAILABLE`; qoldig'ini kamaytirish (hisobdan chiqarish) esa mumkin
        (`allow_archived`)."""
        unknown = []
        archived: list[dict[str, Any]] = []
        for index, sku_id in enumerate(sku_ids):
            snap = snapshots.get(sku_id)
            if snap is None:
                unknown.append(field(f"{list_name}[{index}].sku_id" if list_name else field_name, "invalid"))
            elif snap.sku_status != "ACTIVE" or snap.product_status == "ARCHIVED":
                archived.append(
                    {"sku_id": sku_id, "product_status": snap.product_status, "sku_status": snap.sku_status}
                )
        if unknown:
            raise ValidationError("Unknown SKU", fields=unknown)
        if archived and not allow_archived:
            raise ProductNotAvailableError("Product is archived", lines=archived)

    async def _request_approval(
        self, db: AsyncSession, actor: ActorContext, adjustment: StockAdjustment
    ) -> None:
        """Omborchi so'radi — menejer va egaga vazifa va xabar (DEC-134). Hal qilinsa vazifa o'zi yopiladi."""
        assert actor.shop_id is not None
        await self.tasks.open(
            db,
            shop_id=actor.shop_id,
            actor=actor,
            type=ADJUSTMENT_APPROVAL,
            subject_type=ADJUSTMENT,
            subject_id=adjustment.id,
            dedup_key=f"adjustment_approval:{adjustment.id}",
            assignee_role="MANAGER",
            branch_id=adjustment.branch_id,
            params={"kind": adjustment.kind, "delta": adjustment.delta, REQUESTER_PARAM: actor.membership_id},
        )
        await self.notifications.notify_staff(
            db,
            shop_id=actor.shop_id,
            actor=actor,
            template_key="staff.adjustment_approval",
            aggregate_type=ADJUSTMENT,
            aggregate_id=adjustment.id,
            aggregate_version=adjustment.version,
            variables={"kind": adjustment.kind, "delta": adjustment.delta},
            roles=("OWNER", "MANAGER"),
            branch_id=adjustment.branch_id,
            exclude=[actor.membership_id],
        )

    async def _close_approval(
        self, db: AsyncSession, actor: ActorContext, adjustment: StockAdjustment
    ) -> None:
        assert actor.shop_id is not None
        await self.tasks.resolve(
            db, shop_id=actor.shop_id, actor=actor, subject_type=ADJUSTMENT, subject_id=adjustment.id
        )

    @staticmethod
    def _decreases(kind: str, delta: int) -> bool:
        """Qoldiqni faqat kamaytiradigan tuzatish — arxivdagi mahsulotda ham ruxsat (QA F4)."""
        return (kind == "ADJUSTMENT" and delta < 0) or kind in ("QUARANTINE_IN", "WRITE_OFF")

    async def _usable_evidence(self, db: AsyncSession, actor: ActorContext, file_id: UUID) -> None:
        assert actor.shop_id is not None
        try:
            await self.files.usable(db, actor.shop_id, file_id, "STOCK_EVIDENCE")
        except ValidationError as exc:
            raise ValidationError(
                "Evidence file not usable", fields=[field("evidence_file_id", "invalid")]
            ) from exc

    @staticmethod
    def _movement(adjustment: StockAdjustment) -> Movement:
        d = adjustment.delta
        deltas = {
            "ADJUSTMENT": {"on_hand": d},
            "QUARANTINE_IN": {"on_hand": -d, "quarantine": d},
            "RESTOCK": {"on_hand": d, "quarantine": -d},
            "WRITE_OFF": {"quarantine": -d},
        }[adjustment.kind]
        return Movement(
            adjustment.branch_id, adjustment.sku_id, adjustment.kind, "ADJUSTMENT", adjustment.id, **deltas
        )

    @staticmethod
    def _check_adjustment(balance: StockBalance | None, kind: str, delta: int) -> None:
        """Qoldiq band + ajratilgandan pastga tushmaydi (TC-CON-12); tekshiruvdagidan ko'p chiqarilmaydi."""
        on_hand = balance.on_hand if balance else 0
        held = (balance.reserved + balance.allocated) if balance else 0
        quarantine = balance.quarantine_qty if balance else 0
        adds_on_hand = delta if (kind == "ADJUSTMENT" and delta > 0) or kind == "RESTOCK" else 0
        adds_quarantine = delta if kind == "QUARANTINE_IN" else 0
        if on_hand + adds_on_hand > MAX_STOCK or quarantine + adds_quarantine > MAX_STOCK:
            room = MAX_STOCK - (on_hand if adds_on_hand else quarantine)
            raise ValidationError("Stock quantity too large", fields=[field("delta", "max_value", max=room)])
        removes_on_hand = (
            -delta if kind == "ADJUSTMENT" and delta < 0 else (delta if kind == "QUARANTINE_IN" else 0)
        )
        if removes_on_hand and on_hand - removes_on_hand < held:
            raise InsufficientStockError(
                "Adjustment would go below reserved stock",
                lines=[
                    {
                        "sku_id": balance.sku_id if balance else None,
                        "branch_id": balance.branch_id if balance else None,
                        "requested": removes_on_hand,
                        "available": on_hand - held,
                        "reserved": held,
                    }
                ],
            )
        if kind in ("RESTOCK", "WRITE_OFF") and delta > quarantine:
            raise InsufficientStockError(
                "Not enough stock in quarantine",
                lines=[
                    {
                        "sku_id": balance.sku_id if balance else None,
                        "branch_id": balance.branch_id if balance else None,
                        "requested": delta,
                        "available": quarantine,
                        "quarantine": quarantine,
                    }
                ],
            )

    async def _apply_adjustment(
        self,
        db: AsyncSession,
        actor: ActorContext,
        adjustment: StockAdjustment,
        balances: dict[Key, StockBalance],
        note: str | None,
    ) -> None:
        key = (adjustment.branch_id, adjustment.sku_id)
        balance = balances[key]
        before = balance.on_hand
        await self.apply(db, actor, [self._movement(adjustment)], balances, paths={key: "delta"})
        if adjustment.kind == "WRITE_OFF" or (
            adjustment.kind == "ADJUSTMENT" and adjustment.delta < 0
        ):  # yo'qotish qiymati uchun nusxa (DEC-146)
            adjustment.unit_cost_uzs_minor = (
                await current_unit_costs(db, adjustment.shop_id, [adjustment.sku_id])
            ).get(adjustment.sku_id)
        adjustment.status = "APPROVED"
        adjustment.decided_by = actor.membership_id
        adjustment.decided_at = utcnow()
        adjustment.decision_note = note
        adjustment.on_hand_before, adjustment.on_hand_after = before, balance.on_hand
        await db.flush()

    async def _adjustment(
        self, db: AsyncSession, actor: ActorContext, adjustment_id: UUID, *, for_update: bool = False
    ) -> StockAdjustment:
        query = select(StockAdjustment).where(
            StockAdjustment.id == adjustment_id, StockAdjustment.shop_id == actor.shop_id
        )
        adjustment = (await db.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()
        if adjustment is None:
            raise NotFoundError("Adjustment not found")
        ensure_branch_scope(actor, adjustment.branch_id)
        return adjustment

    async def _pending(
        self, db: AsyncSession, actor: ActorContext, adjustment_id: UUID, expected_version: int, command: str
    ) -> StockAdjustment:
        adjustment = await self._adjustment(db, actor, adjustment_id, for_update=True)
        check_version(adjustment.version, expected_version)
        if adjustment.status != "PENDING":
            raise InvalidTransitionError(
                "Adjustment already decided",
                entity=ADJUSTMENT,
                **{"from": adjustment.status},
                command=command,
            )
        return adjustment

    async def _adjustment_out(
        self, db: AsyncSession, actor: ActorContext, adjustment: StockAdjustment
    ) -> AdjustmentOut:
        await db.refresh(adjustment)
        return (await self._adjustments_out(db, actor, [adjustment]))[0]

    async def _adjustments_out(
        self, db: AsyncSession, actor: ActorContext, rows: list[StockAdjustment]
    ) -> list[AdjustmentOut]:
        if not rows:
            return []
        assert actor.shop_id is not None
        skus = await self.catalog.get_skus(db, actor.shop_id, list({r.sku_id for r in rows}))
        branches = await branch_names(db, actor.shop_id, (r.branch_id for r in rows))
        names = await member_names(
            db, actor.shop_id, [m for r in rows for m in (r.requested_by, r.decided_by)]
        )
        files = await self.files.by_ids(
            db, actor.shop_id, [r.evidence_file_id for r in rows if r.evidence_file_id]
        )
        pending = [(r.branch_id, r.sku_id) for r in rows if r.status == "PENDING"]
        current: dict[Key, int] = {}
        if pending:  # tasdiqlovchi uchun "maqsad X (hozir Y)" (QA F3)
            current = {
                (b, s): on_hand
                for b, s, on_hand in (
                    await db.execute(
                        select(StockBalance.branch_id, StockBalance.sku_id, StockBalance.on_hand).where(
                            StockBalance.shop_id == actor.shop_id,
                            tuple_(StockBalance.branch_id, StockBalance.sku_id).in_(pending),
                        )
                    )
                ).all()
            }
        result = []
        for r in rows:
            snap = skus.get(r.sku_id)
            stored = files.get(r.evidence_file_id) if r.evidence_file_id else None
            evidence = None
            if stored is not None:
                url, expires_at = self.files.url_for(stored)
                evidence = EvidenceOut(
                    file_id=stored.id, mime_type=stored.mime_type, url=url, url_expires_at=expires_at
                )
            result.append(
                AdjustmentOut(
                    id=r.id,
                    branch_id=r.branch_id,
                    branch_name=branches.get(r.branch_id),
                    sku_id=r.sku_id,
                    sku_code=snap.sku_code if snap else None,
                    title=snap.title if snap else None,
                    kind=r.kind,
                    delta=r.delta,
                    reason=r.reason,
                    evidence=evidence,
                    status=r.status,
                    requested_by=member_ref(r.requested_by, names),
                    requested_at=r.requested_at,
                    decided_by=member_ref(r.decided_by, names),
                    decided_at=r.decided_at,
                    decision_note=r.decision_note,
                    on_hand_before=r.on_hand_before,
                    on_hand_after=r.on_hand_after,
                    target_on_hand=r.target_on_hand,
                    support_case_id=r.support_case_id,
                    current_on_hand=(
                        current.get((r.branch_id, r.sku_id), 0) if r.status == "PENDING" else None
                    ),
                    version=r.version,
                )
            )
        return result
