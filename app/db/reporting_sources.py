"""ReportingSourcePort adapteri (7c): mavjud jadvallardan sintetik event'lar (reporting qayta qurish uchun).

Composition root (`app.db`): boshqa schemalarni o'qiydi, lekin domen kodini import qilmaydi. `reporting`
domeni faqat `app.shared.contracts.reporting` port'ini biladi. Qaytarilgan event'lar jonli event'lar bilan bir
xil shaklda; payload'da faqat ID, kod, son va vaqt (xaridor ismi, telefon, matn o'qilmaydi). Hamma so'rov shop
kontekstidagi tranzaksiyada (RLS) va `shop_id` bilan.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events.envelope import EventActor, EventEnvelope

_SYSTEM = EventActor(kind="SYSTEM", id=None)


def _event(
    shop_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    version: int,
    occurred_at: datetime,
    payload: dict[str, Any],
    actor: EventActor = _SYSTEM,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type=event_type,
        shop_id=shop_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        occurred_at=occurred_at,
        actor=actor,
        payload=payload,
    )


class ReportingSourceImpl:
    async def sku_costs(self, db: AsyncSession, shop_id: UUID) -> dict[UUID, int]:
        rows = await db.execute(
            text("SELECT sku_id, avg_unit_cost_uzs_minor FROM commerce.sku_costs WHERE shop_id = :s"),
            {"s": shop_id},
        )
        return {sku_id: int(cost) for sku_id, cost in rows}

    async def orders(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        orders = (
            await db.execute(
                text(
                    "SELECT id, status, source, branch_id, assigned_membership_id, total_minor, currency, "
                    "created_at, completed_at, cancelled_at, version, updated_at "
                    "FROM commerce.orders WHERE shop_id = :s ORDER BY created_at"
                ),
                {"s": shop_id},
            )
        ).mappings()
        lines: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in (
            await db.execute(
                text(
                    "SELECT l.order_id, l.sku_id, l.qty, l.line_total_minor, l.unit_cost_uzs_minor "
                    "FROM commerce.order_lines l "
                    "JOIN commerce.orders o ON o.shop_id = l.shop_id AND o.id = l.order_id "
                    "WHERE l.shop_id = :s AND o.status = 'COMPLETED' ORDER BY l.order_id, l.position, l.id"
                ),
                {"s": shop_id},
            )
        ).mappings():
            lines[row["order_id"]].append(
                {
                    "sku_id": row["sku_id"],
                    "qty": row["qty"],
                    "line_total_minor": row["line_total_minor"],
                    "unit_cost_uzs_minor": row["unit_cost_uzs_minor"],
                }
            )
        events: list[EventEnvelope] = []
        for o in orders:
            status = o["status"]
            payload: dict[str, Any] = {
                "order_id": o["id"],
                "status": status,
                "source": o["source"],
                "branch_id": o["branch_id"],
                "assigned_staff_id": o["assigned_membership_id"],
                "total_minor": o["total_minor"],
                "currency": o["currency"],
                "created_at": o["created_at"],
                "completed_at": o["completed_at"],
                "cancelled_at": o["cancelled_at"],
            }
            if status == "COMPLETED" and o["completed_at"] is not None:
                kind, at = "commerce.order.completed", o["completed_at"]
                payload["lines"] = lines.get(o["id"], [])
            elif status == "CANCELLED" and o["cancelled_at"] is not None:
                kind, at = "commerce.order.cancelled", o["cancelled_at"]
                payload["reason_code"] = "CANCELLED"
            else:
                kind, at = "commerce.order.updated", o["updated_at"]
            events.append(_event(shop_id, kind, "commerce.order", o["id"], o["version"], at, payload))
        return events

    async def quick_sales(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        sales = (
            await db.execute(
                text(
                    "SELECT id, branch_id, total_minor, sold_by, created_at FROM commerce.quick_sales "
                    "WHERE shop_id = :s ORDER BY created_at"
                ),
                {"s": shop_id},
            )
        ).mappings()
        lines: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in (
            await db.execute(
                text(
                    "SELECT quick_sale_id, sku_id, qty, line_total_minor, unit_cost_uzs_minor "
                    "FROM commerce.quick_sale_lines WHERE shop_id = :s ORDER BY quick_sale_id, id"
                ),
                {"s": shop_id},
            )
        ).mappings():
            lines[row["quick_sale_id"]].append(
                {
                    "sku_id": row["sku_id"],
                    "qty": row["qty"],
                    "line_total_minor": row["line_total_minor"],
                    "unit_cost_uzs_minor": row["unit_cost_uzs_minor"],
                }
            )
        return [
            _event(
                shop_id,
                "commerce.quick_sale.recorded",
                "commerce.quick_sale",
                s["id"],
                1,
                s["created_at"],
                {
                    "sale_id": s["id"],
                    "branch_id": s["branch_id"],
                    "total_minor": s["total_minor"],
                    "sold_by": s["sold_by"],
                    "lines": lines.get(s["id"], []),
                },
            )
            for s in sales
        ]

    async def stock(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        rows = (
            await db.execute(
                text(
                    "SELECT branch_id, sku_id, on_hand, reserved, allocated, quarantine_qty, "
                    "version, updated_at "
                    "FROM commerce.stock_balances WHERE shop_id = :s"
                ),
                {"s": shop_id},
            )
        ).mappings()
        return [
            _event(
                shop_id,
                "commerce.stock.changed",
                "commerce.stock_balance",
                r["sku_id"],
                r["version"],
                r["updated_at"],
                {
                    "branch_id": r["branch_id"],
                    "sku_id": r["sku_id"],
                    "on_hand": r["on_hand"],
                    "reserved": r["reserved"],
                    "allocated": r["allocated"],
                    "available": r["on_hand"] - r["reserved"] - r["allocated"],
                    "quarantine_qty": r["quarantine_qty"],
                    "stock_version": r["version"],
                },
            )
            for r in rows
        ]

    async def cases(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        rows = (
            await db.execute(
                text(
                    "SELECT id, type, status, source, sku_id, branch_id, within_warranty, "
                    "resolution, outcome, "
                    "reject_reason, refund_amount_minor, created_at, resolved_at, closed_at, "
                    "version, updated_at "
                    "FROM support.cases WHERE shop_id = :s ORDER BY created_at"
                ),
                {"s": shop_id},
            )
        ).mappings()
        return [
            _event(
                shop_id,
                "support.case.status_changed",
                "support.case",
                r["id"],
                r["version"],
                r["updated_at"],
                {
                    "case_id": r["id"],
                    "type": r["type"],
                    "status": r["status"],
                    "source": r["source"],
                    "sku_id": r["sku_id"],
                    "branch_id": r["branch_id"],
                    "within_warranty": r["within_warranty"],
                    "resolution": r["resolution"],
                    "outcome": r["outcome"],
                    "reject_reason": r["reject_reason"],
                    "refund_amount_minor": r["refund_amount_minor"],
                    "opened_at": r["created_at"],
                    "resolved_at": r["resolved_at"],
                    "closed_at": r["closed_at"],
                },
            )
            for r in rows
        ]

    async def conversations(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        """Xabarlar va uzatishlar. Xodim ID'si — principal (jonli event aktori bilan bir xil)."""
        events: list[EventEnvelope] = []
        messages = (
            await db.execute(
                text(
                    "SELECT m.id, m.conversation_id, m.direction, m.origin, m.occurred_at, c.channel, "
                    "mb.principal_id AS staff_principal "
                    "FROM messaging.messages m "
                    "JOIN messaging.conversations c ON c.shop_id = m.shop_id AND c.id = m.conversation_id "
                    "LEFT JOIN platform.memberships mb ON mb.id = m.author_membership_id "
                    "WHERE m.shop_id = :s AND m.delivery_status <> 'DISCARDED'"
                ),
                {"s": shop_id},
            )
        ).mappings()
        for m in messages:
            payload = {"conversation_id": m["conversation_id"], "channel": m["channel"]}
            if m["direction"] == "IN":
                events.append(
                    _event(
                        shop_id,
                        "messaging.message.received",
                        "messaging.message",
                        m["id"],
                        1,
                        m["occurred_at"],
                        payload,
                    )
                )
                continue
            actor = (
                EventActor(kind="STAFF", id=m["staff_principal"])
                if m["origin"] in ("STAFF", "AI_APPROVED") and m["staff_principal"] is not None
                else _SYSTEM
            )
            events.append(
                _event(
                    shop_id,
                    "messaging.message.queued",
                    "messaging.message",
                    m["id"],
                    1,
                    m["occurred_at"],
                    {**payload, "origin": m["origin"]},
                    actor,
                )
            )
        handoffs = (
            await db.execute(
                text(
                    "SELECT h.id, h.conversation_id, h.reason, h.created_at, h.taken_at, c.channel, "
                    "mb.principal_id AS taker "
                    "FROM messaging.handoffs h "
                    "JOIN messaging.conversations c ON c.shop_id = h.shop_id AND c.id = h.conversation_id "
                    "LEFT JOIN platform.memberships mb ON mb.id = h.taken_by "
                    "WHERE h.shop_id = :s"
                ),
                {"s": shop_id},
            )
        ).mappings()
        for h in handoffs:
            base = {"conversation_id": h["conversation_id"], "channel": h["channel"]}
            events.append(
                _event(
                    shop_id,
                    "messaging.conversation.handed_off",
                    "messaging.conversation",
                    h["conversation_id"],
                    1,
                    h["created_at"],
                    {**base, "handoff_id": h["id"], "reason_code": h["reason"]},
                )
            )
            if h["taken_at"] is not None:
                events.append(
                    _event(
                        shop_id,
                        "messaging.conversation.taken",
                        "messaging.conversation",
                        h["conversation_id"],
                        1,
                        h["taken_at"],
                        base,
                        EventActor(kind="STAFF", id=h["taker"]) if h["taker"] is not None else _SYSTEM,
                    )
                )
        events.sort(key=lambda e: e.occurred_at)
        return events
