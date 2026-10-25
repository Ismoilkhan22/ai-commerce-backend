"""Buyurtma javoblari: kartochka, ro'yxat qatori, "ko'rib chiqish" belgisi va ruxsat etilgan amallar."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce import permissions as perm
from app.domains.commerce.common import Policy, branch_names, discount_limit, member_names
from app.domains.commerce.orders import access
from app.domains.commerce.orders.models.orm import Order, OrderLine, OrderNote, Reservation
from app.domains.commerce.orders.schemas import (
    OrderAction,
    OrderLineOut,
    OrderListItem,
    OrderNoteOut,
    OrderOut,
    OrderReview,
    PaidMarkOut,
    ReservationOut,
)
from app.domains.commerce.orders.services.pricing import discount_status
from app.domains.commerce.schemas import member_ref
from app.shared.types.actor import ActorContext

OPEN_RESERVATIONS = ("ACTIVE", "ALLOCATED")
# 72 soatlik ko'rib chiqish: ochiq bandi bor holatlar. Muammoli buyurtma ham mahsulotni ushlab turadi
REVIEWABLE = ("CONFIRMED", "PROCESSING", "EXCEPTION")
_DIGITS = re.compile(r"\D")


def mask_phone(phone: str | None) -> str | None:
    """ "+998901234567" → "+998 90 *** ** 67" (ro'yxatda to'liq raqam ko'rsatilmaydi)."""
    if not phone:
        return None
    digits = _DIGITS.sub("", phone)
    if len(digits) != 12:
        return "***"
    return f"+{digits[:3]} {digits[3:5]} *** ** {digits[-2:]}"


def review_of(
    order: Order, review_due_at: datetime | None, policy: Policy, now: datetime
) -> OrderReview | None:
    if order.status == "PENDING_CONFIRMATION" and order.submitted_at is not None:
        due = order.submitted_at + timedelta(hours=policy.unconfirmed_after_hours)
        if due <= now:
            return OrderReview(reason="UNCONFIRMED", due_at=due)
    if order.status in REVIEWABLE and review_due_at is not None and review_due_at <= now:
        return OrderReview(reason="RESERVATION_REVIEW", due_at=review_due_at)
    return None


def allowed_actions(
    actor: ActorContext, order: Order, lines: Sequence[OrderLine], review: OrderReview | None, policy: Policy
) -> list[OrderAction]:
    if not access.can_see(actor, order):
        return []
    p, s = actor.permissions, order.status
    own, editable = access.is_own(actor, order), access.can_edit(actor, order)
    acts: list[OrderAction] = []
    if editable:
        acts += ["EDIT", "REFRESH_PRICES"]
        if perm.DISCOUNT_APPLY in p or perm.DISCOUNT_REQUEST in p:
            acts.append("DISCOUNT")
        limit = discount_limit(actor, policy)
        if perm.DISCOUNT_APPROVE in p and any(
            discount_status(line) == "PENDING" and line.discount_pct <= limit for line in lines
        ):  # limiti yetmaydigan chegirma — ega tasdiqlaydi, menejerga tugma ko'rsatilmaydi (QA F8)
            acts.append("APPROVE_DISCOUNT")
        if s == "DRAFT":
            acts.append("SUBMIT")
    pending_discount = any(discount_status(line) == "PENDING" for line in lines)
    if s == "PENDING_CONFIRMATION" and perm.ORDER_CONFIRM in p and own and not pending_discount:
        acts.append("CONFIRM")  # tasdiqlanmagan chegirma bilan tasdiqlab bo'lmaydi (APPROVAL_REQUIRED)
    if s == "CONFIRMED" and perm.ORDER_PROCESS in p and own:
        acts.append("START_PROCESSING")
    if s == "PROCESSING" and own:
        if perm.ORDER_PROCESS in p and order.ready_at is None:
            acts.append("MARK_READY")
        if perm.ORDER_COMPLETE in p:
            acts.append("COMPLETE")
        if perm.ORDER_PROCESS in p:
            acts.append("RAISE_EXCEPTION")
    if s == "EXCEPTION" and perm.ORDER_CANCEL in p:
        acts.append("RESOLVE_EXCEPTION")
    if (s == "DRAFT" and (editable or perm.ORDER_CANCEL in p)) or (
        s in ("PENDING_CONFIRMATION", "CONFIRMED", "EXCEPTION") and perm.ORDER_CANCEL in p
    ):
        acts.append("CANCEL")
    if review is not None and review.reason == "RESERVATION_REVIEW" and perm.ORDER_CANCEL in p:
        acts.append("REVIEW_DECISION")
    if s not in ("DRAFT", "CANCELLED") and order.paid_mark_at is None and perm.ORDER_PAID_MARK in p and own:
        acts.append("PAID_MARK")
    if perm.ORDER_NOTE in p and own:
        acts.append("NOTE")
    if s not in access.TERMINAL:
        if order.assigned_membership_id is None and perm.ORDER_CONFIRM in p:
            acts.append("TAKE")
        if perm.ORDER_ASSIGN in p:
            acts.append("ASSIGN")
    return acts


class OrderViews:
    async def lines(self, db: AsyncSession, order: Order) -> list[OrderLine]:
        rows = await db.execute(
            select(OrderLine)
            .where(OrderLine.shop_id == order.shop_id, OrderLine.order_id == order.id)
            .order_by(OrderLine.position, OrderLine.created_at)
            .execution_options(populate_existing=True)
        )
        return list(rows.scalars())

    async def reservations(
        self,
        db: AsyncSession,
        order: Order,
        *,
        statuses: Sequence[str] | None = None,
        for_update: bool = False,
    ) -> list[Reservation]:
        query = select(Reservation).where(
            Reservation.shop_id == order.shop_id, Reservation.order_id == order.id
        )
        if statuses:
            query = query.where(Reservation.status.in_(statuses))
        query = query.order_by(Reservation.branch_id, Reservation.sku_id).execution_options(
            populate_existing=True
        )
        return list((await db.execute(query.with_for_update() if for_update else query)).scalars())

    async def review_due(
        self, db: AsyncSession, shop_id: UUID, order_ids: Sequence[UUID]
    ) -> dict[UUID, datetime]:
        """Har buyurtma uchun ochiq bandlarning eng erta `review_at` (DEC-104)."""
        if not order_ids:
            return {}
        rows = await db.execute(
            select(Reservation.order_id, func.min(Reservation.review_at))
            .where(
                Reservation.shop_id == shop_id,
                Reservation.order_id.in_(list(order_ids)),
                Reservation.status.in_(OPEN_RESERVATIONS),
            )
            .group_by(Reservation.order_id)
        )
        return {order_id: due for order_id, due in rows}

    async def detail(
        self, db: AsyncSession, actor: ActorContext, order: Order, policy: Policy, now: datetime
    ) -> OrderOut:
        await db.refresh(order)
        lines = await self.lines(db, order)
        reservations = {r.order_line_id: r for r in await self.reservations(db, order)}
        notes = list(
            (
                await db.execute(
                    select(OrderNote)
                    .where(OrderNote.shop_id == order.shop_id, OrderNote.order_id == order.id)
                    .order_by(OrderNote.created_at, OrderNote.id)
                )
            ).scalars()
        )
        due = await self.review_due(db, order.shop_id, [order.id])
        review = review_of(order, due.get(order.id), policy, now)
        people = [
            order.assigned_membership_id,
            order.created_by,
            order.confirmed_by,
            order.ready_by,
            order.completed_by,
            order.cancelled_by,
            order.paid_mark_by,
            *(m for line in lines for m in (line.discount_requested_by, line.discount_approved_by)),
            *(n.author_membership_id for n in notes),
        ]
        names = await member_names(db, order.shop_id, people)
        branches = await branch_names(db, order.shop_id, [order.branch_id])
        phone, address = order.customer_phone_enc, order.delivery_address_enc
        if access.is_warehouse(actor):
            # Omborchiga to'liq raqam kerak emas (10 §6.8): ism va yashirilgan raqam;
            # manzil — faqat yetkazishda
            phone = mask_phone(phone)
            address = address if order.fulfillment_method == "DELIVERY" else None
        paid = None
        if order.paid_mark_at is not None and order.paid_mark_method is not None:
            paid = PaidMarkOut(
                at=order.paid_mark_at,
                by=member_ref(order.paid_mark_by, names),
                method=order.paid_mark_method,
            )
        return OrderOut(
            id=order.id,
            number=order.number,
            status=order.status,
            source=order.source,
            fulfillment_method=order.fulfillment_method,
            branch_id=order.branch_id,
            branch_name=branches.get(order.branch_id) if order.branch_id else None,
            assigned=member_ref(order.assigned_membership_id, names),
            customer_name=order.customer_name,
            customer_phone=phone,
            customer_locale=order.customer_locale,
            customer_comment=order.customer_comment,
            delivery_address=address,
            consent_version=order.consent_version,
            pii_erased_at=order.pii_erased_at,
            currency="UZS",
            total_minor=order.total_minor,
            lines=[self._line_out(line, reservations.get(line.id), names) for line in lines],
            notes=[
                OrderNoteOut(
                    id=n.id,
                    kind=n.kind,
                    body=n.body,
                    author=member_ref(n.author_membership_id, names),
                    created_at=n.created_at,
                )
                for n in notes
            ],
            paid_mark=paid,
            review=review,
            submitted_at=order.submitted_at,
            confirmed_at=order.confirmed_at,
            confirmed_by=member_ref(order.confirmed_by, names),
            processing_at=order.processing_at,
            ready_at=order.ready_at,
            ready_by=member_ref(order.ready_by, names),
            completed_at=order.completed_at,
            completed_by=member_ref(order.completed_by, names),
            cancelled_at=order.cancelled_at,
            cancelled_by=member_ref(order.cancelled_by, names),
            cancel_reason=order.cancel_reason,
            exception_reason=order.exception_reason,
            created_by=member_ref(order.created_by, names),
            created_at=order.created_at,
            updated_at=order.updated_at,
            version=order.version,
            allowed_actions=allowed_actions(actor, order, lines, review, policy),
        )

    async def list_items(
        self, db: AsyncSession, actor: ActorContext, orders: Sequence[Order], policy: Policy, now: datetime
    ) -> list[OrderListItem]:
        if not orders:
            return []
        assert actor.shop_id is not None
        ids = [o.id for o in orders]
        count_rows = await db.execute(
            select(OrderLine.order_id, func.count())
            .where(OrderLine.shop_id == actor.shop_id, OrderLine.order_id.in_(ids))
            .group_by(OrderLine.order_id)
        )
        counts = {order_id: int(count) for order_id, count in count_rows}
        due = await self.review_due(db, actor.shop_id, ids)
        names = await member_names(db, actor.shop_id, (o.assigned_membership_id for o in orders))
        branches = await branch_names(db, actor.shop_id, (o.branch_id for o in orders))
        items = []
        for o in orders:
            review = review_of(o, due.get(o.id), policy, now)
            items.append(
                OrderListItem(
                    id=o.id,
                    number=o.number,
                    status=o.status,
                    source=o.source,
                    fulfillment_method=o.fulfillment_method,
                    branch_id=o.branch_id,
                    branch_name=branches.get(o.branch_id) if o.branch_id else None,
                    assigned=member_ref(o.assigned_membership_id, names),
                    customer_name=o.customer_name,
                    customer_phone_masked=mask_phone(o.customer_phone_enc),
                    currency="UZS",
                    total_minor=o.total_minor,
                    line_count=int(counts.get(o.id, 0)),
                    paid_marked=o.paid_mark_at is not None,
                    ready=o.ready_at is not None,
                    review_reason=review.reason if review else None,
                    submitted_at=o.submitted_at,
                    confirmed_at=o.confirmed_at,
                    created_at=o.created_at,
                    updated_at=o.updated_at,
                    version=o.version,
                )
            )
        return items

    @staticmethod
    def _line_out(line: OrderLine, reservation: Reservation | None, names: dict[UUID, str]) -> OrderLineOut:
        return OrderLineOut(
            id=line.id,
            position=line.position,
            sku_id=line.sku_id,
            product_id=line.product_id,
            title=line.title_snapshot,
            sku_code=line.sku_code_snapshot,
            qty=line.qty,
            price_version_id=line.price_version_id,
            unit_price_minor=line.unit_price_minor,
            currency="USD" if line.currency == "USD" else "UZS",
            exchange_rate_snapshot=line.exchange_rate_snapshot,
            unit_price_uzs_minor=line.unit_price_uzs_minor,
            discount_pct=line.discount_pct,
            discount_status=discount_status(line),
            discount_requested_by=member_ref(line.discount_requested_by, names),
            discount_approved_by=member_ref(line.discount_approved_by, names),
            discount_approved_at=line.discount_approved_at,
            line_total_minor=line.line_total_minor,
            warranty_months=line.warranty_months,
            reservation=ReservationOut(
                id=reservation.id,
                status=reservation.status,
                qty=reservation.qty,
                review_at=reservation.review_at,
                allocated_at=reservation.allocated_at,
                closed_at=reservation.closed_at,
            )
            if reservation
            else None,
            version=line.version,
        )
