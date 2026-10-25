"""Buyurtma holatlari (FSM-08) va band qilish (FSM-07) — qoldiq bilan bitta tranzaksiyada (12 §5, §6).

Tasdiqlash tartibi (12 §5, DEC-127, DEC-134):
1. buyurtma `FOR UPDATE` + If-Match → holat qoidasi → operator faqat o'ziniki (DEC-108);
2. chegirmalar tasdiqlangan, filial ochiq;
3. qoldiq qatorlari tartib bilan `FOR UPDATE` → har qatorda sotuvga mavjud ≥ miqdor;
4. joriy narx (katalogdan, keshsiz) × joriy kurs: so'mdagi narx farq qilsa — `PRICE_CHANGED`;
5. har qatorga band (ACTIVE) va daftarga RESERVE → buyurtma CONFIRMED.
Qisman natija yo'q (12 §2.7). Keyingi o'tishlar ham shu tartibda qulflaydi: buyurtma → band → qoldiq.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce import permissions as perm
from app.domains.commerce.common import RESERVATION_REVIEW_HOURS, STALE_RATE_HOURS, field, load_branch
from app.domains.commerce.inventory.services.stock_service import Movement, StockService, shortage
from app.domains.commerce.orders import access
from app.domains.commerce.orders.models.orm import Order, OrderLine, OrderNote, Reservation
from app.domains.commerce.orders.schemas import OrderOut
from app.domains.commerce.orders.services.order_service import OrderService
from app.domains.commerce.orders.services.pricing import apply_snapshot, discount_status, usable
from app.domains.commerce.orders.services.views import OPEN_RESERVATIONS, REVIEWABLE, OrderViews
from app.domains.commerce.state_machine import ORDER, RESERVATION
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.services.sales_gate import ensure_shop_can_sell
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort, SkuSnapshot
from app.shared.errors.base import (
    ApprovalRequiredError,
    ExchangeRateStaleError,
    ForbiddenError,
    InsufficientStockError,
    InvalidTransitionError,
    PriceChangedError,
    ProductNotAvailableError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

_TARGETS = {
    "SUBMIT": "PENDING_CONFIRMATION",
    "CONFIRM": "CONFIRMED",
    "START_PROCESSING": "PROCESSING",
    "COMPLETE": "COMPLETED",
    "CANCEL": "CANCELLED",
    "RAISE_EXCEPTION": "EXCEPTION",
    "RESOLVE_EXCEPTION": "PROCESSING",
    "EXPIRE": "CANCELLED",
}


def _money(amount: int) -> dict[str, object]:
    return {"amount_minor": amount, "currency": "UZS"}


class OrderLifecycleService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        orders: OrderService,
        stock: StockService,
        catalog: CatalogQueryPort,
        views: OrderViews,
    ) -> None:
        self.use = use
        self.audit = audit
        self.orders = orders
        self.stock = stock
        self.catalog = catalog
        self.views = views

    # ================================================================== qoralama → tasdiq kutilmoqda
    async def submit(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> OrderOut:
        order = await self.orders.editable(db, actor, order_id, expected_version, "SUBMIT")
        rule = self.use.validate_transition(ORDER, order.status, "PENDING_CONFIRMATION", "SUBMIT", actor)
        await ensure_shop_can_sell(db, order.shop_id)  # qoralamani yuborish — yangi savdo (QA N2)
        self._ensure_complete(order, await self.views.lines(db, order))
        order.status = rule.to_status
        order.submitted_at = utcnow()  # 24 soatlik eslatma shundan (DEC-104)
        return await self._finish(db, actor, order, rule.command, rule.from_status, None)

    # ================================================================== tasdiqlash (12 §5)
    async def confirm(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> OrderOut:
        order = await self._locked(db, actor, order_id, expected_version)
        rule = self.use.validate_transition(ORDER, order.status, "CONFIRMED", "CONFIRM", actor)
        access.ensure_own(actor, order)  # operator — faqat o'ziga biriktirilgani (DEC-108, TC-029)
        lines = sorted(await self.views.lines(db, order), key=lambda line: line.sku_id)
        self._ensure_complete(order, lines)
        if order.branch_id is None:
            raise ValidationError("Branch required", fields=[field("branch_id", "required")])
        await load_branch(db, actor, order.branch_id, pickup=order.fulfillment_method == "PICKUP")
        pending = [line.id for line in lines if discount_status(line) == "PENDING"]
        if pending:
            raise ApprovalRequiredError(
                "Discount approval required",
                reason="DISCOUNT",
                approver_roles=["MANAGER", "OWNER"],
                line_ids=pending,
            )
        branch_id = order.branch_id
        balances = await self.stock.lock_balances(
            db, order.shop_id, [(branch_id, line.sku_id) for line in lines]
        )
        short = [
            shortage(balances.get((branch_id, line.sku_id)), branch_id, line.sku_id, line.qty)
            for line in lines
            if (b := balances.get((branch_id, line.sku_id))) is None or b.available < line.qty
        ]
        if short:  # bir qator yetmasa — hech narsa band qilinmaydi (BL-020, TC-002)
            raise InsufficientStockError("Insufficient available stock", lines=short)
        snapshots = await self.catalog.get_skus(db, order.shop_id, [line.sku_id for line in lines])
        self._ensure_prices_current(lines, snapshots)
        now = utcnow()
        reservations = [
            Reservation(
                shop_id=order.shop_id,
                order_id=order.id,
                order_line_id=line.id,
                branch_id=branch_id,
                sku_id=line.sku_id,
                qty=line.qty,
                status="ACTIVE",
                review_at=now + timedelta(hours=RESERVATION_REVIEW_HOURS),  # DEC-104, DEC-134
            )
            for line in lines
        ]
        db.add_all(reservations)
        await db.flush()
        await self.stock.apply(
            db,
            actor,
            [
                Movement(r.branch_id, r.sku_id, "RESERVE", "RESERVATION", r.id, reserved=r.qty)
                for r in reservations
            ],
            balances,
        )
        order.status = rule.to_status
        order.confirmed_at, order.confirmed_by = now, actor.membership_id
        if order.assigned_membership_id is None:  # biriktirilmagan bo'lsa — tasdiqlagan mas'ul bo'ladi
            order.assigned_membership_id = actor.membership_id
        # TODO(S0-06): outbox — commerce.order.confirmed, commerce.reservation.created;
        # xaridorga xabar — S4-06
        return await self._finish(db, actor, order, rule.command, rule.from_status, None)

    async def refresh_prices(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int, note: str | None
    ) -> OrderOut:
        """ "Narxlarni yangilash": xaridor yangi narxga rozi bo'lgach, qatorlar joriy narxga o'tadi
        (DEC-134)."""
        order = await self.orders.editable(db, actor, order_id, expected_version, "REFRESH_PRICES")
        lines = await self.views.lines(db, order)
        snapshots = await self.catalog.get_skus(db, order.shop_id, [line.sku_id for line in lines])
        self._ensure_usable(lines, snapshots)
        if sum((snapshots[line.sku_id].uzs_amount_minor or 0) * line.qty for line in lines) > sum(
            line.unit_price_uzs_minor * line.qty for line in lines
        ):  # narx oshsa — to'xtatilgan shopda yangi summa qabul qilinmaydi (QA N2)
            await ensure_shop_can_sell(db, order.shop_id)
        changed = 0
        for line in lines:
            snap = snapshots[line.sku_id]
            if (
                snap.uzs_amount_minor != line.unit_price_uzs_minor
                or snap.price_version_id != line.price_version_id
            ):
                apply_snapshot(line, snap)
                changed += 1
        if changed:
            await db.flush()
            await self.orders.touch_total(db, order)
        if note:
            db.add(
                OrderNote(
                    shop_id=order.shop_id,
                    order_id=order.id,
                    kind="CALL_RESULT",
                    author_membership_id=actor.membership_id,
                    body=note,
                )
            )
            await db.flush()
        await self.audit.record(
            db,
            action="commerce.order.prices_refreshed",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"changed_lines": changed},
        )
        return await self.orders.detail(db, actor, order)

    # ================================================================== tayyorlash va topshirish (12 §6)
    async def start_processing(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> OrderOut:
        order = await self._locked(db, actor, order_id, expected_version)
        rule = self.use.validate_transition(ORDER, order.status, "PROCESSING", "START_PROCESSING", actor)
        access.ensure_own(actor, order)
        await self._move_reservations(db, actor, order, ("ACTIVE",), "ALLOCATE", "ALLOCATED")
        order.status = rule.to_status
        order.processing_at = utcnow()
        return await self._finish(db, actor, order, rule.command, rule.from_status, None)

    async def mark_ready(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> OrderOut:
        """ "Olib ketishga tayyor" — holat o'zgarmaydi, xaridorga xabar ketadi (S4-06, fon ishlari bilan)."""
        order = await self._locked(db, actor, order_id, expected_version)
        access.ensure_own(actor, order)
        if order.status != "PROCESSING":
            raise InvalidTransitionError(
                "Order is not processing", entity=ORDER, **{"from": order.status}, command="MARK_READY"
            )
        if order.ready_at is None:
            rule = self.use.validate_transition(ORDER, order.status, "PROCESSING", "MARK_READY", actor)
            order.ready_at, order.ready_by = utcnow(), actor.membership_id
            await db.flush()
            await self.use.log_transition(db, entity_id=order.id, rule=rule, actor=actor)
            await self.audit.record(
                db,
                action="commerce.order.ready",
                entity_type=ORDER,
                entity_id=order.id,
                actor=actor,
                entity_version=order.version,
            )
            # TODO(S0-06): outbox — commerce.order.ready_for_pickup → xaridorga xabar (S4-06)
        return await self.orders.detail(db, actor, order)

    async def complete(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> OrderOut:
        """Qoldiq bir marta kamayadi: ikkinchi "Topshirildi" — 409 (holat), daftarda bitta SALE (TC-030)."""
        order = await self._locked(db, actor, order_id, expected_version)
        rule = self.use.validate_transition(ORDER, order.status, "COMPLETED", "COMPLETE", actor)
        access.ensure_own(actor, order)
        await self._move_reservations(db, actor, order, ("ALLOCATED",), "CONSUME", "CONSUMED")
        order.status = rule.to_status
        order.completed_at, order.completed_by = utcnow(), actor.membership_id
        return await self._finish(db, actor, order, rule.command, rule.from_status, None)

    # ================================================================== bekor qilish va muammo
    async def cancel(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int, reason: str | None
    ) -> OrderOut:
        order = await self._locked(db, actor, order_id, expected_version)
        rule = self.use.validate_transition(ORDER, order.status, "CANCELLED", "CANCEL", actor)
        self._require_reason(rule.requires_reason, reason)
        if perm.ORDER_CANCEL in actor.permissions:
            access.ensure_visible(actor, order)
        elif order.status == "DRAFT" and access.can_edit(actor, order):
            pass  # qoralamani operator o'zi bekor qila oladi (FSM-08)
        else:  # tasdiq kutilayotgan va tasdiqlanganini — faqat menejer yoki ega (DEC-108, BL-049)
            raise ForbiddenError("Permission denied", permission=perm.ORDER_CANCEL)
        await self._release(db, actor, order, "RELEASE", "RELEASED")
        self._mark_cancelled(order, actor, reason)
        return await self._finish(db, actor, order, rule.command, rule.from_status, reason)

    async def raise_exception(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int, reason: str
    ) -> OrderOut:
        order = await self._locked(db, actor, order_id, expected_version)
        rule = self.use.validate_transition(ORDER, order.status, "EXCEPTION", "RAISE_EXCEPTION", actor)
        access.ensure_own(actor, order)
        order.status = rule.to_status
        order.exception_reason = reason
        return await self._finish(db, actor, order, rule.command, rule.from_status, reason)

    async def resolve_exception(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        expected_version: int,
        resolution: str,
        reason: str | None,
    ) -> OrderOut:
        order = await self._locked(db, actor, order_id, expected_version)
        access.ensure_visible(actor, order)
        if resolution == "CANCELLED":
            rule = self.use.validate_transition(ORDER, order.status, "CANCELLED", "CANCEL", actor)
            self._require_reason(rule.requires_reason, reason)
            await self._release(db, actor, order, "RELEASE", "RELEASED")
            self._mark_cancelled(order, actor, reason)
        else:
            rule = self.use.validate_transition(ORDER, order.status, "PROCESSING", "RESOLVE_EXCEPTION", actor)
            order.status = rule.to_status
        return await self._finish(db, actor, order, rule.command, rule.from_status, reason)

    async def review_decision(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        expected_version: int,
        decision: str,
        reason: str | None,
    ) -> OrderOut:
        """72 soatlik vazifa (DEC-104, DEC-134): "kutamiz" — muddat suriladi; "bekor" — band
        "muddati o'tdi"."""
        order = await self._locked(db, actor, order_id, expected_version)
        access.ensure_visible(actor, order)
        now = utcnow()
        open_reservations = await self.views.reservations(
            db, order, statuses=OPEN_RESERVATIONS, for_update=True
        )
        if order.status not in REVIEWABLE or not any(r.review_at <= now for r in open_reservations):
            raise InvalidTransitionError(
                "Nothing to review", entity=ORDER, **{"from": order.status}, command="REVIEW"
            )
        if decision == "WAIT":
            for reservation in open_reservations:
                reservation.review_at = now + timedelta(hours=RESERVATION_REVIEW_HOURS)
            await db.flush()
            await self.audit.record(
                db,
                action="commerce.order.review_postponed",
                entity_type=ORDER,
                entity_id=order.id,
                actor=actor,
                entity_version=order.version,
                reason=reason,
            )
            return await self.orders.detail(db, actor, order)
        rule = self.use.validate_transition(ORDER, order.status, "CANCELLED", "EXPIRE", actor)
        self._require_reason(rule.requires_reason, reason)
        await self._release(db, actor, order, "EXPIRE", "EXPIRED", reservations=open_reservations)
        self._mark_cancelled(order, actor, reason)
        return await self._finish(db, actor, order, rule.command, rule.from_status, reason)

    # ================================================================== ichki
    async def _locked(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> Order:
        order = await self.orders.load(db, actor, order_id, for_update=True)
        check_version(order.version, expected_version)
        return order

    @staticmethod
    def _ensure_complete(order: Order, lines: list[OrderLine]) -> None:
        """Yuborish va tasdiqlashdan oldin: qator, xaridor ismi va telefoni; yetkazishda — manzil."""
        problems = []
        if not lines:
            problems.append(field("lines", "required"))
        if not order.customer_name:
            problems.append(field("customer_name", "required"))
        if not order.customer_phone_enc:
            problems.append(field("customer_phone", "required"))
        if order.fulfillment_method == "DELIVERY" and not order.delivery_address_enc:
            problems.append(field("delivery_address", "required"))
        if problems:
            raise ValidationError("Order is incomplete", fields=problems)

    @staticmethod
    def _ensure_usable(lines: list[OrderLine], snapshots: dict[UUID, SkuSnapshot]) -> None:
        missing = [
            {
                "line_id": line.id,
                "sku_id": line.sku_id,
                # UI sababini aytadi: yashirilgan, arxivda yoki narxsiz (POST /orders bilan bir xil shakl)
                "product_status": snap.product_status if snap else None,
                "sku_status": snap.sku_status if snap else None,
            }
            for line in lines
            if not usable(snap := snapshots.get(line.sku_id))
        ]
        if missing:  # yashirilgan, arxivlangan yoki narxi olib tashlangan mahsulot (UAT-M07)
            raise ProductNotAvailableError("Product is not available", lines=missing)
        stale = [s for s in snapshots.values() if s.exchange_rate_stale]
        if stale:  # eskirgan kurs bilan yakuniy narx berilmaydi (BL-018)
            raise ExchangeRateStaleError(
                "Exchange rate is stale",
                rate_effective_at=stale[0].exchange_rate_effective_at,
                max_age_hours=STALE_RATE_HOURS,
            )

    def _ensure_prices_current(self, lines: list[OrderLine], snapshots: dict[UUID, SkuSnapshot]) -> None:
        """So'mdagi narx (joriy narx × joriy kurs) so'ralgan paytdagidan farq qilsa — PRICE_CHANGED
        (DEC-134)."""
        self._ensure_usable(lines, snapshots)
        changed = [
            {
                "line_id": line.id,
                "sku_id": line.sku_id,
                "old": _money(line.unit_price_uzs_minor),
                "new": _money(snap.uzs_amount_minor or 0),
            }
            for line in lines
            if (snap := snapshots[line.sku_id]).uzs_amount_minor != line.unit_price_uzs_minor
        ]
        if changed:
            raise PriceChangedError("Price changed", lines=changed)

    async def _move_reservations(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order: Order,
        sources: tuple[str, ...],
        command: str,
        target: str,
    ) -> None:
        """ALLOCATE (band → ajratilgan) yoki CONSUME (ajratilgan → qoldiqdan chiqadi, daftarda SALE)."""
        reservations = await self.views.reservations(db, order, statuses=sources, for_update=True)
        balances = await self.stock.lock_balances(
            db, order.shop_id, [(r.branch_id, r.sku_id) for r in reservations]
        )
        now = utcnow()
        movements = []
        for r in reservations:
            self.use.validate_transition(RESERVATION, r.status, target, command, actor)
            if command == "ALLOCATE":
                movements.append(
                    Movement(
                        r.branch_id,
                        r.sku_id,
                        "ALLOCATE",
                        "RESERVATION",
                        r.id,
                        reserved=-r.qty,
                        allocated=r.qty,
                    )
                )
                r.allocated_at = now
            else:
                movements.append(
                    Movement(
                        r.branch_id, r.sku_id, "SALE", "RESERVATION", r.id, allocated=-r.qty, on_hand=-r.qty
                    )
                )
                r.closed_at = now
            r.status = target
        await self.stock.apply(db, actor, movements, balances)

    async def _release(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order: Order,
        command: str,
        target: str,
        *,
        reservations: list[Reservation] | None = None,
    ) -> None:
        """Band yoki ajratilgan mahsulot bir marta bo'shaydi (BL-021): daftarda bitta RELEASE."""
        if reservations is None:
            reservations = await self.views.reservations(
                db, order, statuses=OPEN_RESERVATIONS, for_update=True
            )
        if not reservations:
            return
        balances = await self.stock.lock_balances(
            db, order.shop_id, [(r.branch_id, r.sku_id) for r in reservations]
        )
        now = utcnow()
        movements = []
        for r in reservations:
            self.use.validate_transition(RESERVATION, r.status, target, command, actor)
            held = {"reserved": -r.qty} if r.status == "ACTIVE" else {"allocated": -r.qty}
            movements.append(Movement(r.branch_id, r.sku_id, "RELEASE", "RESERVATION", r.id, **held))
            r.status, r.closed_at = target, now
        await self.stock.apply(db, actor, movements, balances)

    @staticmethod
    def _mark_cancelled(order: Order, actor: ActorContext, reason: str | None) -> None:
        order.status = "CANCELLED"
        order.cancelled_at, order.cancelled_by = utcnow(), actor.membership_id
        order.cancel_reason = reason

    @staticmethod
    def _require_reason(required: bool, reason: str | None) -> None:
        if required and not (reason and reason.strip()):  # BL-049: bekor qilish sababi majburiy
            raise ValidationError("Reason required", fields=[field("reason", "required")])

    async def _finish(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order: Order,
        command: str,
        from_status: str,
        reason: str | None,
    ) -> OrderOut:
        await db.flush()
        rule = self.use.registry.find(ORDER, from_status, command)
        assert rule is not None
        await self.use.log_transition(db, entity_id=order.id, rule=rule, actor=actor, reason=reason)
        await self.audit.record(
            db,
            action=f"commerce.order.{command.lower()}",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            reason=reason,
            diff={"status": {"old": from_status, "new": order.status}},
        )
        return await self.orders.detail(db, actor, order)
