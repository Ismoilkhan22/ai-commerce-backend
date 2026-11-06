"""Buyurtma qoralamasi va uning atrofidagi amallar (S4-01, S4-03; db/commerce.md §7–§10).

- Qoralama mahsulotni band qilmaydi (DEC-100b). Qatorda narx, kurs va kafolat — katalogdan nusxa.
- Qatorlar va xaridor ma'lumoti faqat qoralama va tasdiq kutilayotgan holatda o'zgaradi (DEC-134).
- Buyurtma — agregat: qator o'zgarsa ham buyurtma `version` i oshadi, `If-Match` buyurtma versiyasi.
- Chegirma (DEC-110): rol limitigacha darhol, undan ko'pi — tasdiq so'rovi; tasdiqlanmaguncha summaga
  kirmaydi.
- Xaridor telefoni va manzili shifrlangan; audit diff'ga faqat maydon nomlari tushadi (TC-SEC-08).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, ColumnElement, cast, func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce import permissions as perm
from app.domains.commerce.common import (
    RESERVATION_REVIEW_HOURS,
    Policy,
    cursor_time,
    cursor_uuid,
    discount_limit,
    field,
    load_branch,
    load_policy,
    make_cursor,
    member_names,
    read_cursor,
)
from app.domains.commerce.events import ORDER_EVENTS, order_event
from app.domains.commerce.orders import access
from app.domains.commerce.orders.models.orm import Order, OrderLine, OrderNote, Reservation
from app.domains.commerce.orders.schemas import (
    MAX_LINES,
    OrderCounts,
    OrderCreate,
    OrderHistory,
    OrderHistoryItem,
    OrderLineIn,
    OrderList,
    OrderNoteIn,
    OrderNoteOut,
    OrderOut,
    OrderReviewQueue,
    OrderSort,
    OrderUpdate,
)
from app.domains.commerce.orders.services.pricing import apply_snapshot, discount_status, recompute, usable
from app.domains.commerce.orders.services.views import OPEN_RESERVATIONS, REVIEWABLE, OrderViews
from app.domains.commerce.schemas import member_ref
from app.domains.commerce.state_machine import ORDER
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.services.sales_gate import ensure_shop_can_sell
from app.platform.staff.models.orm import Membership, MembershipBranch, Principal
from app.platform.use.models.orm import TransitionLog
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import (
    DiscountLimitExceededError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    OrderLinkedElsewhereError,
    ProductNotAvailableError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.money import MAX_SAFE_MINOR
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

REVIEW_QUEUE_LIMIT = 50
_SORTS: dict[str, Any] = {"-created_at": Order.created_at, "-updated_at": Order.updated_at}
_NUMBER = re.compile(r"^#?\s*(\d{1,12})$")
_CONFIRMER_ROLES = ("OWNER", "MANAGER", "SALES")  # buyurtmaga mas'ul bo'la oladiganlar (DEC-108)


async def next_order_number(db: AsyncSession, shop_id: UUID) -> int:
    """Shop ichida ketma-ket raqam (§10): shu tranzaksiyada +1, bekor bo'lsa raqam ham qaytadi."""
    number = (
        await db.execute(
            text(
                "INSERT INTO commerce.order_counters AS c (shop_id, last_number) VALUES (:shop_id, 1) "
                "ON CONFLICT (shop_id) DO UPDATE SET last_number = c.last_number + 1 "
                "RETURNING last_number"
            ),
            {"shop_id": shop_id},
        )
    ).scalar_one()
    return int(number)


class OrderService:
    def __init__(self, audit: AuditService, catalog: CatalogQueryPort, views: OrderViews) -> None:
        self.audit = audit
        self.catalog = catalog
        self.views = views

    # ================================================================== o'qish
    async def get(self, db: AsyncSession, actor: ActorContext, order_id: UUID) -> OrderOut:
        order = await self.load(db, actor, order_id)
        access.ensure_visible(actor, order)
        return await self.detail(db, actor, order)

    async def history(self, db: AsyncSession, actor: ActorContext, order_id: UUID) -> OrderHistory:
        """Kim yubordi, tasdiqladi, tayyorlashni boshladi... — `transition_log` dan, eskisi birinchi."""
        order = await self.load(db, actor, order_id)
        access.ensure_visible(actor, order)
        rows = list(
            (
                await db.execute(
                    select(TransitionLog)
                    .where(
                        TransitionLog.shop_id == order.shop_id,
                        TransitionLog.entity_type == ORDER,
                        TransitionLog.entity_id == order.id,
                    )
                    .order_by(TransitionLog.occurred_at, TransitionLog.id)
                )
            ).scalars()
        )
        principal_ids = {r.actor_id for r in rows if r.actor_id is not None}
        names: dict[UUID, str] = {}
        if principal_ids:
            found = await db.execute(
                select(Principal.id, Principal.full_name).where(Principal.id.in_(principal_ids))
            )
            names = {pid: name for pid, name in found}
        return OrderHistory(
            items=[
                OrderHistoryItem(
                    at=r.occurred_at,
                    command=r.command,
                    from_status=r.from_status,
                    to_status=r.to_status,
                    actor_type=r.actor_type,
                    actor_name=names.get(r.actor_id) if r.actor_id else None,
                    reason=r.reason,
                )
                for r in rows
            ]
        )

    async def detail(self, db: AsyncSession, actor: ActorContext, order: Order) -> OrderOut:
        assert actor.shop_id is not None
        return await self.views.detail(db, actor, order, await load_policy(db, actor.shop_id), utcnow())

    async def list_orders(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        statuses: Sequence[str],
        branch_id: UUID | None,
        assigned: str | None,
        q: str | None,
        needs_review: bool,
        sort: OrderSort,
        limit: int,
        cursor: str | None,
        number: int | None = None,
    ) -> OrderList:
        assert actor.shop_id is not None
        policy = await load_policy(db, actor.shop_id)
        now = utcnow()
        column = _SORTS[sort]
        query = select(Order).where(Order.shop_id == actor.shop_id, access.visibility(actor))
        if statuses:
            query = query.where(Order.status.in_(statuses))
        if branch_id is not None:
            query = query.where(Order.branch_id == branch_id)
        if assigned == "me":
            query = query.where(Order.assigned_membership_id == actor.membership_id)
        elif assigned == "unassigned":
            query = query.where(Order.assigned_membership_id.is_(None))
        elif assigned:
            query = query.where(Order.assigned_membership_id == self._uuid_param(assigned, "assigned"))
        if number is not None:  # aniq raqam (suhbatga bog'lash oynasi, 5b)
            query = query.where(Order.number == number)
        if q and q.strip():
            query = query.where(self._search(q.strip()))
        if needs_review:
            query = query.where(self._needs_review(policy, now))
        if cursor:
            raw = read_cursor(cursor, f"order{sort}", ("t", "id"))
            query = query.where(tuple_(column, Order.id) < (cursor_time(raw["t"]), cursor_uuid(raw["id"])))
        rows = list(
            (await db.execute(query.order_by(column.desc(), Order.id.desc()).limit(limit + 1))).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        next_cursor = None
        if has_more and page:
            next_cursor = make_cursor(f"order{sort}", t=getattr(page[-1], column.key), id=page[-1].id)
        items = await self.views.list_items(db, actor, page, policy, now)
        return OrderList(items=items, next_cursor=next_cursor, has_more=has_more)

    async def counts(self, db: AsyncSession, actor: ActorContext) -> OrderCounts:
        assert actor.shop_id is not None
        policy = await load_policy(db, actor.shop_id)
        now = utcnow()
        base = (
            select(func.count())
            .select_from(Order)
            .where(Order.shop_id == actor.shop_id, access.visibility(actor))
        )
        rows = await db.execute(
            select(Order.status, func.count())
            .where(Order.shop_id == actor.shop_id, access.visibility(actor))
            .group_by(Order.status)
        )
        by_status = {status: 0 for status in ("DRAFT", "PENDING_CONFIRMATION", "CONFIRMED", "PROCESSING")}
        by_status.update({"COMPLETED": 0, "CANCELLED": 0, "EXCEPTION": 0})
        for status, count in rows:
            by_status[status] = int(count)
        active = Order.status.notin_(access.TERMINAL)
        mine = (
            await db.execute(base.where(active, Order.assigned_membership_id == actor.membership_id))
        ).scalar_one()
        unassigned = (
            await db.execute(base.where(active, Order.assigned_membership_id.is_(None)))
        ).scalar_one()
        unconfirmed = (await db.execute(base.where(self._unconfirmed(policy, now)))).scalar_one()
        reservations = (await db.execute(base.where(self._reservation_due(now)))).scalar_one()
        return OrderCounts(
            by_status=by_status,
            total=sum(by_status.values()),
            mine=int(mine),
            unassigned=int(unassigned),
            review_unconfirmed=int(unconfirmed),
            review_reservations=int(reservations),
        )

    async def review_queue(self, db: AsyncSession, actor: ActorContext) -> OrderReviewQueue:
        """ "Ko'rib chiqish kerak" (DEC-104, DEC-134). Rejali ish va bildirishnoma — S0-06 bilan."""
        assert actor.shop_id is not None
        policy = await load_policy(db, actor.shop_id)
        now = utcnow()
        visible = (Order.shop_id == actor.shop_id, access.visibility(actor))
        unconfirmed = list(
            (
                await db.execute(
                    select(Order)
                    .where(*visible, self._unconfirmed(policy, now))
                    .order_by(Order.submitted_at, Order.id)
                    .limit(REVIEW_QUEUE_LIMIT)
                )
            ).scalars()
        )
        held = list(
            (
                await db.execute(
                    select(Order)
                    .where(*visible, self._reservation_due(now))
                    .order_by(Order.confirmed_at, Order.id)
                    .limit(REVIEW_QUEUE_LIMIT)
                )
            ).scalars()
        )
        return OrderReviewQueue(
            unconfirmed=await self.views.list_items(db, actor, unconfirmed, policy, now),
            reservations=await self.views.list_items(db, actor, held, policy, now),
            unconfirmed_after_hours=policy.unconfirmed_after_hours,
            reservation_review_hours=RESERVATION_REVIEW_HOURS,
        )

    # ================================================================== qoralama
    async def create(
        self,
        db: AsyncSession,
        actor: ActorContext,
        data: OrderCreate,
        *,
        conversation_id: UUID | None = None,
        customer_ref: UUID | None = None,
    ) -> OrderOut:
        """`conversation_id` — suhbatdan ochilgan qoralama (5b, ConversationOrdersPort): holat xabarlari
        xaridorga shu suhbat kanali orqali ketadi."""
        assert actor.shop_id is not None
        await ensure_shop_can_sell(db, actor.shop_id)  # to'xtatilgan shopda yangi buyurtma yo'q (TC-023)
        if data.branch_id is not None:
            await load_branch(db, actor, data.branch_id, pickup=data.fulfillment_method == "PICKUP")
        phone = normalize_phone(data.customer_phone, "customer_phone") if data.customer_phone else None
        seen: set[UUID] = set()
        for index, item in enumerate(data.lines):
            if item.sku_id in seen:  # bir buyurtmada bir SKU — bitta qator; 2 ta kerak bo'lsa qty = 2
                raise ValidationError("Duplicate SKU", fields=[field(f"lines[{index}].sku_id", "not_unique")])
            seen.add(item.sku_id)
        number = await next_order_number(db, actor.shop_id)
        order = Order(
            shop_id=actor.shop_id,
            number=number,
            status="DRAFT",
            source="AI" if actor.actor_type == "AI_AGENT" else "STAFF",  # DEC-100c
            conversation_id=conversation_id,
            customer_ref=customer_ref,
            branch_id=data.branch_id,
            assigned_membership_id=actor.membership_id,  # yaratgan xodim mas'ul; menejer almashtiradi
            fulfillment_method=data.fulfillment_method,
            customer_name=data.customer_name,
            customer_phone_enc=phone,
            customer_phone_hmac=search_hmac(phone) if phone else None,
            delivery_address_enc=data.delivery_address,
            customer_locale=data.customer_locale,
            customer_comment=data.customer_comment,
            total_minor=0,
            created_by=actor.membership_id,
        )
        db.add(order)
        await db.flush()
        await self._add_lines(db, actor, order, data.lines, prefix="lines")
        await self.audit.record(
            db,
            action="commerce.order.created",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"lines": len(data.lines), "source": "STAFF"},
        )
        await order_event(db, actor, order, "commerce.order.drafted")
        return await self.detail(db, actor, order)

    async def update(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int, data: OrderUpdate
    ) -> OrderOut:
        order = await self.editable(db, actor, order_id, expected_version, "EDIT")
        wanted = data.model_dump(exclude_unset=True)
        changed: list[str] = []
        if "customer_phone" in wanted:
            phone = (
                normalize_phone(wanted["customer_phone"], "customer_phone")
                if wanted["customer_phone"]
                else None
            )
            if phone != order.customer_phone_enc:
                order.customer_phone_enc = phone
                order.customer_phone_hmac = search_hmac(phone) if phone else None
                changed.append("customer_phone")
        if "delivery_address" in wanted and wanted["delivery_address"] != order.delivery_address_enc:
            order.delivery_address_enc = wanted["delivery_address"]
            changed.append("delivery_address")
        for name in ("customer_name", "customer_comment"):
            if name in wanted and wanted[name] != getattr(order, name):
                setattr(order, name, wanted[name])
                changed.append(name)
        for name in ("customer_locale", "fulfillment_method"):
            if wanted.get(name) is not None and wanted[name] != getattr(order, name):
                setattr(order, name, wanted[name])
                changed.append(name)
        if "branch_id" in wanted and wanted["branch_id"] != order.branch_id:
            await self._ensure_assignee_covers(db, order, wanted["branch_id"])
            order.branch_id = wanted["branch_id"]
            changed.append("branch_id")
        if order.branch_id is not None and {"branch_id", "fulfillment_method"} & set(changed):
            await load_branch(db, actor, order.branch_id, pickup=order.fulfillment_method == "PICKUP")
        if changed:
            await db.flush()
            await self.audit.record(
                db,
                action="commerce.order.updated",
                entity_type=ORDER,
                entity_id=order.id,
                actor=actor,
                entity_version=order.version,
                # Faqat maydon NOMLARI — telefon va manzil qiymati audit'ga tushmaydi (TC-SEC-08)
                diff={"changed_fields": sorted(changed)},
            )
        return await self.detail(db, actor, order)

    # ================================================================== qatorlar
    async def add_line(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int, data: OrderLineIn
    ) -> OrderOut:
        order = await self.editable(db, actor, order_id, expected_version, "EDIT_LINES")
        await ensure_shop_can_sell(db, order.shop_id)  # yangi qator — yangi savdo (QA N2)
        lines = await self.views.lines(db, order)
        if any(line.sku_id == data.sku_id for line in lines):
            raise ValidationError("SKU already in order", fields=[field("sku_id", "not_unique")])
        if len(lines) >= MAX_LINES:
            raise ValidationError("Too many lines", fields=[field("lines", "max_length", max=MAX_LINES)])
        await self._add_lines(db, actor, order, [data], prefix=None)
        await self._line_audit(db, actor, order, "added")
        return await self.detail(db, actor, order)

    async def update_line(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        line_id: UUID,
        expected_version: int,
        qty: int,
    ) -> OrderOut:
        order = await self.editable(db, actor, order_id, expected_version, "EDIT_LINES")
        line = await self._line(db, order, line_id)
        if qty > line.qty:  # ko'paytirish — yangi savdo; kamaytirish to'xtatilgan shopda ham mumkin (QA N2)
            await ensure_shop_can_sell(db, order.shop_id)
        if line.qty != qty:
            line.qty = qty
            recompute(line)
            await self.touch_total(db, order)
            await self._line_audit(db, actor, order, "updated")
        return await self.detail(db, actor, order)

    async def remove_line(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, line_id: UUID, expected_version: int
    ) -> OrderOut:
        order = await self.editable(db, actor, order_id, expected_version, "EDIT_LINES")
        line = await self._line(db, order, line_id)
        await db.delete(line)
        await db.flush()
        await self.touch_total(db, order)
        await self._line_audit(db, actor, order, "removed")
        return await self.detail(db, actor, order)

    # ================================================================== chegirma (DEC-110)
    async def set_discount(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        line_id: UUID,
        expected_version: int,
        pct: Decimal,
    ) -> OrderOut:
        if perm.DISCOUNT_APPLY not in actor.permissions and perm.DISCOUNT_REQUEST not in actor.permissions:
            raise ForbiddenError("Permission denied", permission=perm.DISCOUNT_REQUEST)
        order = await self.editable(db, actor, order_id, expected_version, "DISCOUNT")
        assert actor.shop_id is not None
        line = await self._line(db, order, line_id)
        policy = await load_policy(db, actor.shop_id)
        now = utcnow()
        line.discount_pct = pct
        if pct == 0:
            line.discount_requested_by = line.discount_approved_by = line.discount_approved_at = None
            outcome = "cleared"
        elif pct <= discount_limit(actor, policy):  # o'z limiti ichida — darhol
            line.discount_requested_by = line.discount_approved_by = actor.membership_id
            line.discount_approved_at = now
            outcome = "applied"
        else:  # limitdan katta — tasdiq so'rovi (menejer ≤ limit, undan ko'pi — ega)
            line.discount_requested_by = actor.membership_id
            line.discount_approved_by = line.discount_approved_at = None
            outcome = "requested"
        recompute(line)
        await self.touch_total(db, order)
        await self.audit.record(
            db,
            action=f"commerce.order.discount_{outcome}",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"line_id": line.id, "discount_pct": pct},
        )
        return await self.detail(db, actor, order)

    async def decide_discount(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        line_id: UUID,
        expected_version: int,
        *,
        approve: bool,
        note: str | None,
    ) -> OrderOut:
        order = await self.load(db, actor, order_id, for_update=True)
        check_version(order.version, expected_version)
        access.ensure_visible(actor, order)
        if order.status not in access.EDITABLE:
            raise InvalidTransitionError(
                "Order is not editable", entity=ORDER, **{"from": order.status}, command="DISCOUNT"
            )
        assert actor.shop_id is not None
        line = await self._line(db, order, line_id)
        if discount_status(line) != "PENDING":
            raise InvalidTransitionError(
                "No pending discount",
                entity="commerce.order_line",
                **{"from": discount_status(line)},
                command="DECIDE",
            )
        if approve:
            policy = await load_policy(db, actor.shop_id)
            allowed = discount_limit(actor, policy)
            if line.discount_pct > allowed:
                raise DiscountLimitExceededError(
                    "Discount above your limit",
                    requested_percent=line.discount_pct,
                    allowed_percent=allowed,
                    approver_role="OWNER",
                )
            line.discount_approved_by, line.discount_approved_at = actor.membership_id, utcnow()
        else:
            line.discount_pct = Decimal(0)
            line.discount_requested_by = None
        recompute(line)
        await self.touch_total(db, order)
        await self.audit.record(
            db,
            action="commerce.order.discount_approved" if approve else "commerce.order.discount_rejected",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            reason=note,
            diff={"line_id": line.id},
        )
        return await self.detail(db, actor, order)

    # ================================================================== biriktirish (DEC-108)
    async def take(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int
    ) -> OrderOut:
        order = await self.load(db, actor, order_id, for_update=True)
        check_version(order.version, expected_version)
        access.ensure_visible(actor, order)
        if order.status in access.TERMINAL or order.assigned_membership_id not in (None, actor.membership_id):
            raise InvalidTransitionError(
                "Order is already assigned or closed", entity=ORDER, **{"from": order.status}, command="TAKE"
            )
        if order.assigned_membership_id is None:
            order.assigned_membership_id = actor.membership_id
            await db.flush()
            await self._assign_audit(db, actor, order)
        return await self.detail(db, actor, order)

    async def assign(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        expected_version: int,
        membership_id: UUID | None,
    ) -> OrderOut:
        order = await self.load(db, actor, order_id, for_update=True)
        check_version(order.version, expected_version)
        access.ensure_visible(actor, order)
        if order.status in access.TERMINAL:
            raise InvalidTransitionError(
                "Order is closed", entity=ORDER, **{"from": order.status}, command="ASSIGN"
            )
        if membership_id is not None:
            member = (
                await db.execute(
                    select(Membership).where(
                        Membership.id == membership_id, Membership.shop_id == actor.shop_id
                    )
                )
            ).scalar_one_or_none()
            if member is None or member.status != "ACTIVE" or member.role not in _CONFIRMER_ROLES:
                raise ValidationError(
                    "Member cannot own orders", fields=[field("membership_id", "invalid_choice")]
                )
            if not await self._covers_branch(db, member, order.branch_id):
                # Filial doirasidan tashqaridagi xodim buyurtmani ko'ra olmaydi — "yo'qolib" qolardi (QA F5)
                raise ValidationError(
                    "Member does not work in this branch",
                    fields=[field("membership_id", "invalid_choice", branch_id=order.branch_id)],
                )
        if order.assigned_membership_id != membership_id:
            order.assigned_membership_id = membership_id
            await db.flush()
            await self._assign_audit(db, actor, order)
        return await self.detail(db, actor, order)

    async def _ensure_assignee_covers(self, db: AsyncSession, order: Order, branch_id: UUID | None) -> None:
        """Filial almashsa — mas'ul xodim yangi filialda ham ishlashi shart, aks holda buyurtma undan
        "yo'qoladi" (QA F5). Jim o'zgartirmaymiz: 422, avval boshqasiga biriktiriladi."""
        if order.assigned_membership_id is None or branch_id is None:
            return
        member = await db.get(Membership, order.assigned_membership_id)
        if member is not None and not await self._covers_branch(db, member, branch_id):
            raise ValidationError(
                "Assignee does not work in this branch",
                fields=[field("branch_id", "out_of_scope", membership_id=member.id)],
            )

    @staticmethod
    async def _covers_branch(db: AsyncSession, member: Membership, branch_id: UUID | None) -> bool:
        if member.branch_scope != "SELECTED" or branch_id is None:
            return True
        found = await db.scalar(
            select(MembershipBranch.branch_id).where(
                MembershipBranch.membership_id == member.id, MembershipBranch.branch_id == branch_id
            )
        )
        return found is not None

    # ================================================================== izoh va "to'landi"
    async def add_note(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, data: OrderNoteIn
    ) -> OrderNoteOut:
        order = await self.load(db, actor, order_id)
        access.ensure_own(actor, order)
        note = OrderNote(
            shop_id=order.shop_id,
            order_id=order.id,
            kind=data.kind,
            author_membership_id=actor.membership_id,
            body=data.body,
        )
        db.add(note)
        await db.flush()
        await db.refresh(note)
        # Matn audit'ga yozilmaydi — ichida telefon yoki manzil bo'lishi mumkin (26 §4)
        await self.audit.record(
            db,
            action="commerce.order.note_added",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            diff={"kind": data.kind},
        )
        return await self._note_out(db, note)

    async def note(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, note_id: UUID
    ) -> OrderNoteOut:
        order = await self.load(db, actor, order_id)
        access.ensure_visible(actor, order)
        note = (
            await db.execute(
                select(OrderNote).where(
                    OrderNote.id == note_id,
                    OrderNote.shop_id == order.shop_id,
                    OrderNote.order_id == order.id,
                )
            )
        ).scalar_one_or_none()
        if note is None:
            raise NotFoundError("Note not found")
        return await self._note_out(db, note)

    async def _note_out(self, db: AsyncSession, note: OrderNote) -> OrderNoteOut:
        names = await member_names(db, note.shop_id, [note.author_membership_id])
        return OrderNoteOut(
            id=note.id,
            kind=note.kind,
            body=note.body,
            author=member_ref(note.author_membership_id, names),
            created_at=note.created_at,
        )

    async def paid_mark(self, db: AsyncSession, actor: ActorContext, order_id: UUID, method: str) -> OrderOut:
        """ "To'landi" — xodim belgisi, to'lov holati emas; tizim tekshirmaydi (DEC-100a). Bir marta."""
        order = await self.load(db, actor, order_id, for_update=True)
        access.ensure_own(actor, order)
        if order.status in ("DRAFT", "CANCELLED") or order.paid_mark_at is not None:
            raise InvalidTransitionError(
                "Paid mark not allowed", entity=ORDER, **{"from": order.status}, command="PAID_MARK"
            )
        order.paid_mark_at, order.paid_mark_by, order.paid_mark_method = utcnow(), actor.membership_id, method
        await db.flush()
        await self.audit.record(
            db,
            action="commerce.order.paid_marked",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"method": method},
        )
        await order_event(
            db, actor, order, ORDER_EVENTS["MARK_PAID"], method=method, marked_by=actor.membership_id
        )
        return await self.detail(db, actor, order)

    # ================================================================== yordamchilar
    async def link_conversation(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order_id: UUID,
        conversation_id: UUID,
        customer_ref: UUID,
        *,
        relink: bool = False,
        expected_version: int | None = None,
    ) -> tuple[Order, UUID | None]:
        """Mavjud buyurtmani suhbatga bog'lash (5b): keyingi holat xabarlari xaridorga shu suhbat orqali.
        Yakunlangan yoki bekor qilingan buyurtma bog'lanmaydi — unga xabar ketmaydi.

        Boshqa suhbatga bog'langan buyurtma jim ko'chirilmaydi (QA 5b M3): `ORDER_LINKED_ELSEWHERE`.
        Ko'chirish — `relink=True` va buyurtma versiyasi (If-Match ma'nosida).
        Natija: (buyurtma, eski suhbat)."""
        order = await self.load(db, actor, order_id, for_update=True)
        access.ensure_own(actor, order)
        if order.status in ("COMPLETED", "CANCELLED"):
            raise InvalidTransitionError(
                "Order is closed", entity=ORDER, **{"from": order.status}, command="LINK_CONVERSATION"
            )
        previous = order.conversation_id
        if previous == conversation_id:
            return order, None
        if previous is not None:
            if not relink:
                raise OrderLinkedElsewhereError(
                    "Order is linked to another conversation", order_version=order.version
                )
            if expected_version is None:
                raise ValidationError(
                    "Order version required", fields=[field("expected_version", "required")]
                )
            check_version(order.version, expected_version)
        order.conversation_id, order.customer_ref = conversation_id, customer_ref
        await db.flush()
        await self.audit.record(
            db,
            action="commerce.order.conversation_linked",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={
                "conversation_id": {
                    "old": str(previous) if previous else None,
                    "new": str(conversation_id),
                }
            },
        )
        return order, previous

    async def for_conversation(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID
    ) -> list[Order]:
        rows = await db.execute(
            select(Order)
            .where(Order.shop_id == actor.shop_id, Order.conversation_id == conversation_id)
            .order_by(Order.created_at.desc())
            .limit(20)
        )
        return [o for o in rows.scalars() if access.hidden_reason(actor, o) is None]

    async def load(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, *, for_update: bool = False
    ) -> Order:
        query = select(Order).where(Order.id == order_id, Order.shop_id == actor.shop_id)
        order = (await db.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()
        if order is None:  # boshqa shopniki ham — 404 (TC-001)
            raise NotFoundError("Order not found")
        return order

    async def editable(
        self, db: AsyncSession, actor: ActorContext, order_id: UUID, expected_version: int, command: str
    ) -> Order:
        order = await self.load(db, actor, order_id, for_update=True)
        check_version(order.version, expected_version)
        access.ensure_visible(actor, order)
        if order.status not in access.EDITABLE:  # tasdiqlangan buyurtma o'zgarmaydi (DEC-134)
            raise InvalidTransitionError(
                "Order is not editable", entity=ORDER, **{"from": order.status}, command=command
            )
        if not access.can_edit(actor, order):
            raise ForbiddenError("Order is assigned to another operator")
        return order

    async def add_lines(
        self, db: AsyncSession, actor: ActorContext, order: Order, items: Sequence[OrderLineIn]
    ) -> None:
        """Qoralamaga qatorlar (saytdan so'rov ham): katalogdan nusxa; mavjud emas — PRODUCT_NOT_AVAILABLE."""
        await self._add_lines(db, actor, order, items, prefix="lines")

    async def _add_lines(
        self,
        db: AsyncSession,
        actor: ActorContext,
        order: Order,
        items: Sequence[OrderLineIn],
        *,
        prefix: str | None,
    ) -> None:
        if not items:
            return
        assert actor.shop_id is not None
        snapshots = await self.catalog.get_skus(db, actor.shop_id, [i.sku_id for i in items])
        problems = []
        for index, item in enumerate(items):
            snap = snapshots.get(item.sku_id)
            if snap is None:  # boshqa shop SKU'si — xuddi yo'qdek
                raise ValidationError(
                    "Unknown SKU",
                    fields=[field(f"{prefix}[{index}].sku_id" if prefix else "sku_id", "invalid")],
                )
            if not usable(snap):
                problems.append(
                    {
                        "sku_id": item.sku_id,
                        "product_status": snap.product_status,
                        "sku_status": snap.sku_status,
                    }
                )
        if problems:  # chiqarilmagan, arxivdagi yoki narxsiz mahsulot (UAT-M07)
            raise ProductNotAvailableError("Product is not available", lines=problems)
        position = (
            await db.execute(
                select(func.coalesce(func.max(OrderLine.position), -1)).where(
                    OrderLine.shop_id == order.shop_id, OrderLine.order_id == order.id
                )
            )
        ).scalar_one()
        for item in items:
            position += 1
            line = OrderLine(
                shop_id=order.shop_id,
                order_id=order.id,
                position=position,
                sku_id=item.sku_id,
                qty=item.qty,
                discount_pct=Decimal(0),
            )
            apply_snapshot(line, snapshots[item.sku_id])
            db.add(line)
        await db.flush()
        await self.touch_total(db, order)

    async def touch_total(self, db: AsyncSession, order: Order) -> None:
        """Jami qayta hisoblanadi va buyurtma versiyasi oshadi (qator o'zgarishi — agregat o'zgarishi)."""
        total = (
            await db.execute(
                select(func.coalesce(func.sum(cast(OrderLine.line_total_minor, BigInteger)), 0)).where(
                    OrderLine.shop_id == order.shop_id, OrderLine.order_id == order.id
                )
            )
        ).scalar_one()
        if int(total) > MAX_SAFE_MINOR:
            raise ValidationError("Order total too large", fields=[field("lines", "max_value")])
        order.total_minor = int(total)
        order.updated_at = utcnow()
        await db.flush()

    async def _line(self, db: AsyncSession, order: Order, line_id: UUID) -> OrderLine:
        line = (
            await db.execute(
                select(OrderLine).where(
                    OrderLine.id == line_id,
                    OrderLine.shop_id == order.shop_id,
                    OrderLine.order_id == order.id,
                )
            )
        ).scalar_one_or_none()
        if line is None:
            raise NotFoundError("Order line not found")
        return line

    async def _line_audit(self, db: AsyncSession, actor: ActorContext, order: Order, what: str) -> None:
        await self.audit.record(
            db,
            action=f"commerce.order.line_{what}",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
        )

    async def _assign_audit(self, db: AsyncSession, actor: ActorContext, order: Order) -> None:
        await self.audit.record(
            db,
            action="commerce.order.assigned",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"assigned_membership_id": order.assigned_membership_id},
        )
        await order_event(db, actor, order, "commerce.order.assigned")  # yangi mas'ulga panel signali

    @staticmethod
    def _uuid_param(value: str, name: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValidationError("Invalid filter", fields=[field(name, "invalid_format")]) from exc

    @staticmethod
    def _search(q: str) -> ColumnElement[bool]:
        """Raqam (#1042), telefon (kalitli xesh orqali — shifrlangan ustunda qidirib bo'lmaydi) yoki ism."""
        conditions: list[ColumnElement[bool]] = []
        number = _NUMBER.match(q)
        if number and len(number.group(1)) <= 12:
            conditions.append(Order.number == int(number.group(1)))
        try:
            conditions.append(Order.customer_phone_hmac == search_hmac(normalize_phone(q)))
        except ValidationError:
            pass
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(Order.customer_name.ilike(pattern, escape="\\"))
        return or_(*conditions)

    @staticmethod
    def _unconfirmed(policy: Policy, now: datetime) -> ColumnElement[bool]:
        return (Order.status == "PENDING_CONFIRMATION") & (
            Order.submitted_at <= now - timedelta(hours=policy.unconfirmed_after_hours)
        )

    @staticmethod
    def _reservation_due(now: datetime) -> ColumnElement[bool]:
        due = (
            select(Reservation.id)
            .where(
                Reservation.shop_id == Order.shop_id,
                Reservation.order_id == Order.id,
                Reservation.status.in_(OPEN_RESERVATIONS),
                Reservation.review_at <= now,
            )
            .exists()
        )
        return Order.status.in_(REVIEWABLE) & due

    def _needs_review(self, policy: Policy, now: datetime) -> ColumnElement[bool]:
        return or_(self._unconfirmed(policy, now), self._reservation_due(now))
