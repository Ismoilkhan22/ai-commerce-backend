"""Buyurtmaga kim tegadi — rol ruxsatidan keyingi ikkinchi qatlam (10 §6.8, DEC-108).

- **Operator (SALES)** — "own": o'ziga biriktirilgan buyurtmalar va biriktirilmagan navbat (o'ziga oladi).
  Boshqa operatorning buyurtmasi — `FORBIDDEN` (o'z shopida); boshqa shop buyurtmasi — `NOT_FOUND`.
- **Omborchi (WAREHOUSE)** — filial doirasida, faqat tasdiqlangandan keyingi buyurtmalar (tayyorlash uchun).
- **Menejer va ega** — filial doirasida hammasi. Filiali hali tanlanmagan buyurtma — hammaga ochiq.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_, true

from app.domains.commerce.orders.models.orm import Order
from app.domains.commerce.permissions import ORDER_CREATE
from app.shared.errors.base import ForbiddenError
from app.shared.types.actor import ActorContext

TERMINAL = frozenset({"COMPLETED", "CANCELLED"})
EDITABLE = frozenset({"DRAFT", "PENDING_CONFIRMATION"})  # tasdiqlangandan keyin o'zgarmaydi (DEC-134)
WAREHOUSE_VISIBLE = ("CONFIRMED", "PROCESSING", "EXCEPTION", "COMPLETED")


def is_sales(actor: ActorContext) -> bool:
    return "SALES" in actor.roles and not ({"OWNER", "MANAGER"} & actor.roles)


def is_warehouse(actor: ActorContext) -> bool:
    return "WAREHOUSE" in actor.roles and not ({"OWNER", "MANAGER", "SALES"} & actor.roles)


def visibility(actor: ActorContext) -> ColumnElement[bool]:
    """Ro'yxat filtri — `can_see` bilan aynan bir xil qoida."""
    conditions: list[ColumnElement[bool]] = []
    if is_sales(actor):
        conditions.append(
            or_(Order.assigned_membership_id == actor.membership_id, Order.assigned_membership_id.is_(None))
        )
    if is_warehouse(actor):
        conditions.append(Order.status.in_(WAREHOUSE_VISIBLE))
    if actor.branch_ids is not None:
        conditions.append(or_(Order.branch_id.in_(actor.branch_ids), Order.branch_id.is_(None)))
    return and_(*conditions) if conditions else true()


def hidden_reason(actor: ActorContext, order: Order) -> str | None:
    """Nega ko'rinmaydi: `other_operator`, `not_confirmed` (omborchi), `other_branch`; ko'rinsa — None."""
    if is_sales(actor) and order.assigned_membership_id not in (None, actor.membership_id):
        return "other_operator"
    if is_warehouse(actor) and order.status not in WAREHOUSE_VISIBLE:
        return "not_confirmed"
    if (
        actor.branch_ids is not None
        and order.branch_id is not None
        and order.branch_id not in actor.branch_ids
    ):
        return "other_branch"
    return None


def can_see(actor: ActorContext, order: Order) -> bool:
    return hidden_reason(actor, order) is None


def ensure_visible(actor: ActorContext, order: Order) -> None:
    # `details.reason` — klient aniq sababni ko'rsatadi ("hali tasdiqlanmagan", QA U4); o'z shopi ichida
    if (reason := hidden_reason(actor, order)) is not None:
        raise ForbiddenError("Order is not available to you", reason=reason)


def is_own(actor: ActorContext, order: Order) -> bool:
    """Operator uchun — faqat o'ziga biriktirilgani. Menejer, ega va omborchi uchun cheklov yo'q."""
    return not is_sales(actor) or order.assigned_membership_id == actor.membership_id


def ensure_own(actor: ActorContext, order: Order) -> None:
    ensure_visible(actor, order)
    if not is_own(actor, order):
        raise ForbiddenError("Order is not assigned to you", reason="not_assigned")


def can_edit(actor: ActorContext, order: Order) -> bool:
    """Qoralama va tasdiq kutilayotganini tahrirlash: operator — o'ziniki yoki biriktirilmagani."""
    return (
        order.status in EDITABLE
        and ORDER_CREATE in actor.permissions
        and can_see(actor, order)
        and (not is_sales(actor) or order.assigned_membership_id in (None, actor.membership_id))
    )
