"""commerce event'lari (05 §8.2) — biznes o'zgarishi bilan bitta tranzaksiyada `commerce.outbox_events` ga.

Payload'da faqat ID, holat va summa: xaridor ismi, telefoni, manzili, izohi YO'Q (05 §3.1).
Qoldiq — absolyut qiymat (`available` va boshqalar), delta emas: event qayta kelsa ikki marta qo'shilmaydi.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.inventory.models.orm import StockBalance, StockLedger
from app.domains.commerce.orders.models.orm import Order, Reservation
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

SCHEMA = "commerce"
ORDER = "commerce.order"
RESERVATION = "commerce.reservation"
STOCK_BALANCE = "commerce.stock_balance"
# Qoldiq qatori (filial × SKU) uchun barqaror agregat ID; tartib — shu qator versiyasi (QA 5a F4)
_STOCK_NS = uuid5(NAMESPACE_URL, "urn:cos:commerce:stock_balance")

# Bekor qilish / muammo sababi — kod (erkin matn event'ga tushmaydi, PII bo'lishi mumkin; 05 §8.2)
CANCEL_REASON_CODES: dict[str, str] = {"CANCEL": "STAFF_CANCELLED", "EXPIRE": "EXPIRED"}
EXCEPTION_REASON_CODE = "STAFF_REPORTED"


def stock_aggregate_id(branch_id: UUID, sku_id: UUID) -> UUID:
    """`uuid5(ns, "{branch_id}:{sku_id}")` — har filial × SKU qatoriga bitta, deterministik."""
    return uuid5(_STOCK_NS, f"{branch_id}:{sku_id}")


# Buyruq → event (FSM-08). EXPIRE — bekor qilishning bir turi (sabab kodi bilan)
ORDER_EVENTS: dict[str, str] = {
    "SUBMIT": "commerce.order.submitted",
    "CONFIRM": "commerce.order.confirmed",
    "START_PROCESSING": "commerce.order.processing",
    "RESOLVE_EXCEPTION": "commerce.order.processing",
    "COMPLETE": "commerce.order.completed",
    "CANCEL": "commerce.order.cancelled",
    "EXPIRE": "commerce.order.cancelled",
    "RAISE_EXCEPTION": "commerce.order.exception",
    "MARK_READY": "commerce.order.ready",
    "MARK_PAID": "commerce.order.paid_marked",
}


def order_payload(order: Order, **extra: Any) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "number": order.number,
        "status": order.status,
        "total_minor": order.total_minor,
        "currency": order.currency,
        "source": order.source,
        "branch_id": order.branch_id,
        "assigned_staff_id": order.assigned_membership_id,
        "fulfillment_method": order.fulfillment_method,
        # Suhbatdan kelgan buyurtma (5b): xaridorga holat xabari shu suhbat kanali orqali (S4-06)
        "conversation_id": order.conversation_id,
        "customer_locale": order.customer_locale,  # xaridorga xabar tili (QA 5b M1) — til kodi, PII emas
        **extra,
    }


async def order_event(
    db: AsyncSession, actor: ActorContext, order: Order, event_type: str, **extra: Any
) -> None:
    await db.flush()  # `aggregate_version` — shu o'zgarishdan KEYINGI versiya (05 §6, QA 5a F4)
    await write_outbox(
        db,
        schema=SCHEMA,
        event_type=event_type,
        actor=actor,
        shop_id=order.shop_id,
        aggregate_type=ORDER,
        aggregate_id=order.id,
        aggregate_version=order.version,
        payload=order_payload(order, **extra),
    )


async def reservation_event(
    db: AsyncSession, actor: ActorContext, order: Order, reservations: Sequence[Reservation], action: str
) -> None:
    """`commerce.reservation.created|released|expired` — har band uchun bitta event, o'z agregati va versiyasi
    bilan (`commerce.reservation`; buyurtma versiyasi bilan to'qnashmaydi — QA 5a F4)."""
    if not reservations:
        return
    await db.flush()
    for r in reservations:
        await write_outbox(
            db,
            schema=SCHEMA,
            event_type=f"commerce.reservation.{action}",
            actor=actor,
            shop_id=order.shop_id,
            aggregate_type=RESERVATION,
            aggregate_id=r.id,
            aggregate_version=r.version,
            payload={
                "reservation_id": r.id,
                "order_id": order.id,
                "sku_id": r.sku_id,
                "branch_id": r.branch_id,
                "qty": r.qty,
                "status": r.status,
            },
        )


async def stock_changed(
    db: AsyncSession,
    actor: ActorContext,
    entries: Sequence[StockLedger],
    balances: dict[tuple[UUID, UUID], StockBalance],
) -> None:
    """Har o'zgargan qoldiq qatori uchun bitta event — oxirgi (absolyut) holat bilan."""
    latest: dict[tuple[UUID, UUID], StockLedger] = {}
    for entry in entries:
        latest[(entry.branch_id, entry.sku_id)] = entry
    for key, entry in sorted(latest.items()):
        balance = balances.get(key)
        if balance is None:
            continue
        await write_outbox(
            db,
            schema=SCHEMA,
            event_type="commerce.stock.changed",
            actor=actor,
            shop_id=balance.shop_id,
            aggregate_type=STOCK_BALANCE,
            aggregate_id=stock_aggregate_id(balance.branch_id, balance.sku_id),
            aggregate_version=balance.version,
            payload={
                "sku_id": balance.sku_id,
                "branch_id": balance.branch_id,
                "on_hand": balance.on_hand,
                "reserved": balance.reserved,
                "allocated": balance.allocated,
                "available": balance.on_hand - balance.reserved - balance.allocated,
                "stock_version": balance.version,
                "reason": entry.reason,
            },
        )
