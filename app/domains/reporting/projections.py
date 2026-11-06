"""Event'lardan read model'lar (19 §3, DEC-146). Har funksiya bitta event'ni jadvalga qo'llaydi.

Tinglovchilar (`subscribers.py`) ham, qayta qurish (`backfill.py`, sintetik event'lar) ham aynan shu kodni
chaqiradi. Idempotentlik:
- versiyali qatorlar (`order_facts`, `support_case_facts`, `stock_facts`): katta versiya g'olib, takror event
  hech narsani o'zgartirmaydi;
- qatorlar to'plami (`order_line_facts`, `quick_sale_facts`): event bir marta to'liq to'plamni yozadi —
  eskisi o'chirilib qayta yoziladi;
- xabar sanagichlari: xabar qatori `ON CONFLICT DO NOTHING`; sanagich faqat qator qo'shilganda oshadi.
Bundan tashqari tinglovchi darajasida `reporting.consumer_receipts` (bitta event — bir marta).

Shaxsiy ma'lumot yo'q: event payload'ida ham yo'q (05 §3.1), bu yerga faqat ID, kod, son va vaqt o'tadi.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reporting.common import as_dt, as_int, as_uuid, day_of, shop_zone
from app.domains.reporting.models.orm import (
    ConversationFact,
    HandoffFact,
    MessageFact,
    OrderFact,
    OrderLineFact,
    ProductDim,
    ProjectionCheckpoint,
    QuickSaleFact,
    StockFact,
    SupportCaseFact,
)
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.events.envelope import EventEnvelope

# Proyeksiya nomlari (projection_checkpoints.projection)
P_ORDERS = "order_facts"
P_QUICK_SALES = "quick_sale_facts"
P_STOCK = "stock_facts"
P_CASES = "support_case_facts"
P_MESSAGES = "message_facts"
P_HANDOFFS = "handoff_facts"
ALL_PROJECTIONS = (P_ORDERS, P_QUICK_SALES, P_STOCK, P_CASES, P_MESSAGES, P_HANDOFFS)

AI_ORIGINS = frozenset({"AI_AUTO"})
STAFF_ORIGINS = frozenset({"STAFF", "AI_APPROVED"})  # AI_APPROVED — AI taklifini odam yuborgan
SYSTEM_ORIGINS = frozenset({"NOTIFICATION", "GREETING"})


async def touch_checkpoint(db: AsyncSession, env: EventEnvelope, projection: str) -> None:
    assert env.shop_id is not None
    stmt = insert(ProjectionCheckpoint).values(
        shop_id=env.shop_id,
        projection=projection,
        last_event_id=env.event_id,
        last_occurred_at=env.occurred_at,
    )
    current = ProjectionCheckpoint
    newer = stmt.excluded.last_occurred_at >= func.coalesce(
        current.last_occurred_at, stmt.excluded.last_occurred_at
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[current.shop_id, current.projection],
            set_={
                "last_event_id": case((newer, stmt.excluded.last_event_id), else_=current.last_event_id),
                "last_occurred_at": func.greatest(current.last_occurred_at, stmt.excluded.last_occurred_at),
                "updated_at": func.now(),
            },
        )
    )


# ------------------------------------------------------------------------------------- SKU o'lchami
async def ensure_dims(
    db: AsyncSession, catalog: CatalogQueryPort, shop_id: UUID, sku_ids: set[UUID], *, refresh: bool = False
) -> dict[UUID, ProductDim]:
    """Mahsulot o'lchami: yo'qlari katalogdan bir marta o'qiladi (`refresh` — hammasi, narx yangilanadi)."""
    if not sku_ids:
        return {}
    existing = {
        row.sku_id: row
        for row in (
            await db.execute(
                select(ProductDim).where(ProductDim.shop_id == shop_id, ProductDim.sku_id.in_(sku_ids))
            )
        ).scalars()
    }
    wanted = sku_ids if refresh else sku_ids - existing.keys()
    if wanted:
        dims = await catalog.sku_report_dims(db, shop_id, list(wanted))
        rows = [
            {
                "shop_id": shop_id,
                "sku_id": d.sku_id,
                "product_id": d.product_id,
                "title": d.title,
                "sku_code": d.sku_code,
                "category_code": d.category_code or None,
                "category_name": d.category_name or None,
                "price_uzs_minor": d.price_uzs_minor,
            }
            for d in dims.values()
        ]
        if rows:
            stmt = insert(ProductDim).values(rows)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[ProductDim.shop_id, ProductDim.sku_id],
                    set_={
                        "product_id": stmt.excluded.product_id,
                        "title": stmt.excluded.title,
                        "sku_code": stmt.excluded.sku_code,
                        "category_code": stmt.excluded.category_code,
                        "category_name": stmt.excluded.category_name,
                        "price_uzs_minor": stmt.excluded.price_uzs_minor,
                        "updated_at": func.now(),
                    },
                )
            )
        existing = {
            row.sku_id: row
            for row in (
                await db.execute(
                    select(ProductDim).where(ProductDim.shop_id == shop_id, ProductDim.sku_id.in_(sku_ids))
                )
            ).scalars()
        }
    return existing


def _cost_total(qty: int, unit_cost: int | None) -> int | None:
    return None if unit_cost is None else qty * unit_cost


# ---------------------------------------------------------------------------------- buyurtmalar
async def apply_order(
    db: AsyncSession, catalog: CatalogQueryPort, env: EventEnvelope, zone: ZoneInfo
) -> None:
    assert env.shop_id is not None
    p = env.payload
    shop_id, order_id = env.shop_id, env.aggregate_id
    created_at = as_dt(p.get("created_at")) or env.occurred_at
    completed_at = as_dt(p.get("completed_at")) or (
        env.occurred_at if env.event_type == "commerce.order.completed" else None
    )
    cancelled_at = as_dt(p.get("cancelled_at")) or (
        env.occurred_at if env.event_type == "commerce.order.cancelled" else None
    )
    stmt = insert(OrderFact).values(
        shop_id=shop_id,
        order_id=order_id,
        status=str(p["status"]),
        source=str(p.get("source") or "STAFF"),
        branch_id=as_uuid(p.get("branch_id")),
        assigned_staff_id=as_uuid(p.get("assigned_staff_id")),
        total_minor=int(p.get("total_minor") or 0),
        currency=str(p.get("currency") or "UZS"),
        created_at=created_at,
        created_day=day_of(created_at, zone),
        completed_at=completed_at,
        completed_day=day_of(completed_at, zone) if completed_at else None,
        cancelled_at=cancelled_at,
        cancelled_day=day_of(cancelled_at, zone) if cancelled_at else None,
        cancel_reason_code=p.get("reason_code") if cancelled_at else None,
        aggregate_version=env.aggregate_version,
    )
    fact = OrderFact
    ex = stmt.excluded
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[fact.shop_id, fact.order_id],
            set_={
                "status": ex.status,
                "source": ex.source,
                "branch_id": ex.branch_id,
                "assigned_staff_id": ex.assigned_staff_id,
                "total_minor": ex.total_minor,
                "currency": ex.currency,
                # Vaqt belgilari bir marta qo'yiladi; keyingi event'lar ularni yo'qotmaydi
                "completed_at": func.coalesce(fact.completed_at, ex.completed_at),
                "completed_day": func.coalesce(fact.completed_day, ex.completed_day),
                "cancelled_at": func.coalesce(fact.cancelled_at, ex.cancelled_at),
                "cancelled_day": func.coalesce(fact.cancelled_day, ex.cancelled_day),
                "cancel_reason_code": func.coalesce(fact.cancel_reason_code, ex.cancel_reason_code),
                "aggregate_version": ex.aggregate_version,
                "updated_at": func.now(),
            },
            where=fact.aggregate_version < ex.aggregate_version,
        )
    )
    if env.event_type == "commerce.order.drafted" or p.get("created_at") is not None:
        # Qoralama event'i boshqa event'lardan keyin kelsa ham yaratilish vaqti to'g'ri bo'lsin
        await db.execute(
            update(fact)
            .where(fact.shop_id == shop_id, fact.order_id == order_id, fact.created_at > created_at)
            .values(created_at=created_at, created_day=day_of(created_at, zone))
        )
    if env.event_type == "commerce.order.completed" or (p.get("status") == "COMPLETED" and "lines" in p):
        await _replace_order_lines(db, catalog, env, zone, completed_at or env.occurred_at)
    await touch_checkpoint(db, env, P_ORDERS)


async def _replace_order_lines(
    db: AsyncSession, catalog: CatalogQueryPort, env: EventEnvelope, zone: ZoneInfo, completed_at: datetime
) -> None:
    assert env.shop_id is not None
    if env.payload.get("lines") is None:
        return  # eski (legacy) event'da `lines` yo'q: mavjud qator faktlarini o'chirmaymiz
    lines = list(env.payload["lines"])
    await db.execute(
        delete(OrderLineFact).where(
            OrderLineFact.shop_id == env.shop_id, OrderLineFact.order_id == env.aggregate_id
        )
    )
    if not lines:
        return
    dims = await ensure_dims(
        db, catalog, env.shop_id, {u for u in (as_uuid(x["sku_id"]) for x in lines) if u}
    )
    rows = []
    for index, line in enumerate(lines):
        sku_id = as_uuid(line["sku_id"])
        assert sku_id is not None
        qty = int(line["qty"])
        unit_cost = as_int(line.get("unit_cost_uzs_minor"))
        dim = dims.get(sku_id)
        rows.append(
            {
                "shop_id": env.shop_id,
                "order_id": env.aggregate_id,
                "line_no": index,
                "sku_id": sku_id,
                "product_id": dim.product_id if dim else None,
                "category_code": dim.category_code if dim else None,
                "branch_id": as_uuid(env.payload.get("branch_id")),
                "source": str(env.payload.get("source") or "STAFF"),
                "completed_at": completed_at,
                "completed_day": day_of(completed_at, zone),
                "qty": qty,
                "line_total_minor": int(line["line_total_minor"]),
                "unit_cost_uzs_minor": unit_cost,
                "cost_total_minor": _cost_total(qty, unit_cost),
            }
        )
    await db.execute(insert(OrderLineFact).values(rows))


# --------------------------------------------------------------------------------------- tez sotuv
async def apply_quick_sale(
    db: AsyncSession, catalog: CatalogQueryPort, env: EventEnvelope, zone: ZoneInfo
) -> None:
    assert env.shop_id is not None
    p = env.payload
    recorded_at = as_dt(p.get("recorded_at")) or env.occurred_at
    lines = list(p.get("lines") or [])
    await db.execute(
        delete(QuickSaleFact).where(
            QuickSaleFact.shop_id == env.shop_id, QuickSaleFact.sale_id == env.aggregate_id
        )
    )
    dims = await ensure_dims(
        db, catalog, env.shop_id, {u for u in (as_uuid(x["sku_id"]) for x in lines) if u}
    )
    rows = []
    for index, line in enumerate(lines):
        sku_id = as_uuid(line["sku_id"])
        assert sku_id is not None
        qty = int(line["qty"])
        unit_cost = as_int(line.get("unit_cost_uzs_minor"))
        dim = dims.get(sku_id)
        branch_id = as_uuid(p["branch_id"])
        assert branch_id is not None
        rows.append(
            {
                "shop_id": env.shop_id,
                "sale_id": env.aggregate_id,
                "line_no": index,
                "sku_id": sku_id,
                "product_id": dim.product_id if dim else None,
                "category_code": dim.category_code if dim else None,
                "branch_id": branch_id,
                "sold_by_staff_id": as_uuid(p.get("sold_by")),
                "recorded_at": recorded_at,
                "recorded_day": day_of(recorded_at, zone),
                "qty": qty,
                "line_total_minor": int(line["line_total_minor"]),
                "unit_cost_uzs_minor": unit_cost,
                "cost_total_minor": _cost_total(qty, unit_cost),
            }
        )
    if rows:
        await db.execute(insert(QuickSaleFact).values(rows))
    await touch_checkpoint(db, env, P_QUICK_SALES)


# ------------------------------------------------------------------------------------------ ombor
async def apply_stock(db: AsyncSession, env: EventEnvelope) -> None:
    assert env.shop_id is not None
    p = env.payload
    stmt = insert(StockFact).values(
        shop_id=env.shop_id,
        branch_id=as_uuid(p["branch_id"]),
        sku_id=as_uuid(p["sku_id"]),
        on_hand=int(p["on_hand"]),
        reserved=int(p["reserved"]),
        allocated=int(p["allocated"]),
        available=int(p["available"]),
        quarantine_qty=int(p.get("quarantine_qty") or 0),
        stock_version=int(p.get("stock_version") or env.aggregate_version),
    )
    fact = StockFact
    ex = stmt.excluded
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[fact.shop_id, fact.branch_id, fact.sku_id],
            set_={
                "on_hand": ex.on_hand,
                "reserved": ex.reserved,
                "allocated": ex.allocated,
                "available": ex.available,
                "quarantine_qty": ex.quarantine_qty,
                "stock_version": ex.stock_version,
                "updated_at": func.now(),
            },
            where=fact.stock_version < ex.stock_version,
        )
    )
    await touch_checkpoint(db, env, P_STOCK)


# ---------------------------------------------------------------------------------- kafolat/qaytarish
async def apply_case(db: AsyncSession, env: EventEnvelope, zone: ZoneInfo) -> None:
    assert env.shop_id is not None
    p = env.payload
    status = str(p["status"])
    opened_at = as_dt(p.get("opened_at")) or env.occurred_at
    resolved_at = as_dt(p.get("resolved_at")) or (env.occurred_at if status == "RESOLVED" else None)
    closed_at = as_dt(p.get("closed_at")) or (env.occurred_at if status == "CLOSED" else None)
    stmt = insert(SupportCaseFact).values(
        shop_id=env.shop_id,
        case_id=env.aggregate_id,
        type=str(p.get("type") or "WARRANTY"),
        source=p.get("source"),
        status=status,
        sku_id=as_uuid(p.get("sku_id")),
        branch_id=as_uuid(p.get("branch_id")),
        within_warranty=p.get("within_warranty"),
        resolution=p.get("resolution"),
        outcome=p.get("outcome"),
        reject_reason=p.get("reject_reason"),
        refund_amount_minor=as_int(p.get("refund_amount_minor")),
        opened_at=opened_at,
        opened_day=day_of(opened_at, zone),
        resolved_at=resolved_at,
        resolved_day=day_of(resolved_at, zone) if resolved_at else None,
        closed_at=closed_at,
        aggregate_version=env.aggregate_version,
    )
    fact = SupportCaseFact
    ex = stmt.excluded
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[fact.shop_id, fact.case_id],
            set_={
                "type": ex.type,
                "source": ex.source,
                "status": ex.status,
                "sku_id": ex.sku_id,
                "branch_id": ex.branch_id,
                "within_warranty": ex.within_warranty,
                "resolution": ex.resolution,
                "outcome": ex.outcome,
                "reject_reason": ex.reject_reason,
                "refund_amount_minor": func.coalesce(ex.refund_amount_minor, fact.refund_amount_minor),
                "resolved_at": func.coalesce(fact.resolved_at, ex.resolved_at),
                "resolved_day": func.coalesce(fact.resolved_day, ex.resolved_day),
                "closed_at": func.coalesce(fact.closed_at, ex.closed_at),
                "aggregate_version": ex.aggregate_version,
            },
            where=fact.aggregate_version < ex.aggregate_version,
        )
    )
    if env.event_type == "support.case.opened":  # ochilish vaqti: eng erta event
        await db.execute(
            update(fact)
            .where(fact.shop_id == env.shop_id, fact.case_id == env.aggregate_id, fact.opened_at > opened_at)
            .values(opened_at=opened_at, opened_day=day_of(opened_at, zone))
        )
    await touch_checkpoint(db, env, P_CASES)


# ------------------------------------------------------------------------------- suhbat va operatorlar
def _author(env: EventEnvelope) -> tuple[str, str, UUID | None] | None:
    """(yo'nalish, muallif, xodim) yoki None — hisobga olinmaydigan event (yetkazish tasdig'i va h.k.)."""
    if env.event_type == "messaging.message.received":
        return "IN", "CUSTOMER", None
    origin = env.payload.get("origin")
    if origin is None:  # `message.sent` yetkazilgach (tizim aktori) — `queued` allaqachon hisoblangan
        return None
    if origin in AI_ORIGINS:
        return "OUT", "AI", None
    if origin in STAFF_ORIGINS:
        return "OUT", "STAFF", env.actor.id if env.actor.kind == "STAFF" else None
    if origin in SYSTEM_ORIGINS:
        return "OUT", "SYSTEM", None
    return None


async def _conversation_row(
    db: AsyncSession,
    shop_id: UUID,
    conversation_id: UUID,
    channel: str | None,
    moment: datetime,
    zone: ZoneInfo,
) -> ConversationFact:
    stmt = insert(ConversationFact).values(
        shop_id=shop_id,
        conversation_id=conversation_id,
        channel=channel,
        started_at=moment,
        started_day=day_of(moment, zone),
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ConversationFact.shop_id, ConversationFact.conversation_id],
            set_={
                "started_day": case(
                    (stmt.excluded.started_at < ConversationFact.started_at, stmt.excluded.started_day),
                    else_=ConversationFact.started_day,
                ),
                "started_at": func.least(ConversationFact.started_at, stmt.excluded.started_at),
                "channel": func.coalesce(ConversationFact.channel, stmt.excluded.channel),
            },
        )
    )
    row = (
        await db.execute(
            select(ConversationFact)
            .where(ConversationFact.shop_id == shop_id, ConversationFact.conversation_id == conversation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return row


async def apply_message(db: AsyncSession, env: EventEnvelope, zone: ZoneInfo) -> None:
    assert env.shop_id is not None
    parsed = _author(env)
    if parsed is None:
        return
    direction, author, staff_id = parsed
    p = env.payload
    conversation_id = as_uuid(p["conversation_id"])
    assert conversation_id is not None
    moment = env.occurred_at
    inserted = await db.scalar(
        insert(MessageFact)
        .values(
            shop_id=env.shop_id,
            message_id=env.aggregate_id,
            conversation_id=conversation_id,
            direction=direction,
            author=author,
            staff_id=staff_id,
            occurred_at=moment,
            day=day_of(moment, zone),
            hour=moment.astimezone(zone).hour,
        )
        .on_conflict_do_nothing()
        .returning(MessageFact.message_id)
    )
    if inserted is None:  # takror event: sanagichlar tegmaydi (idempotent)
        await touch_checkpoint(db, env, P_MESSAGES)
        return
    row = await _conversation_row(db, env.shop_id, conversation_id, p.get("channel"), moment, zone)
    row.last_message_at = max(filter(None, (row.last_message_at, moment)))
    if direction == "IN":
        row.inbound_count += 1
        row.pending_inbound_since = row.pending_inbound_since or moment
    elif author in ("AI", "STAFF"):
        if row.pending_inbound_since is not None:
            seconds = max(0, int((moment - row.pending_inbound_since).total_seconds()))
            await db.execute(
                update(MessageFact)
                .where(MessageFact.shop_id == env.shop_id, MessageFact.message_id == env.aggregate_id)
                .values(response_seconds=seconds)
            )
            row.pending_inbound_since = None
        if author == "AI":
            row.ai_reply_count += 1
        else:
            row.staff_reply_count += 1
    await touch_checkpoint(db, env, P_MESSAGES)


async def apply_handoff(db: AsyncSession, env: EventEnvelope, zone: ZoneInfo) -> None:
    assert env.shop_id is not None
    p = env.payload
    conversation_id = as_uuid(p["conversation_id"])
    assert conversation_id is not None
    if env.event_type == "messaging.conversation.handed_off":
        handoff_id = as_uuid(p.get("handoff_id"))
        if handoff_id is None:
            return
        inserted = await db.scalar(
            insert(HandoffFact)
            .values(
                shop_id=env.shop_id,
                handoff_id=handoff_id,
                conversation_id=conversation_id,
                reason=str(p.get("reason_code") or "UNKNOWN"),
                opened_at=env.occurred_at,
                opened_day=day_of(env.occurred_at, zone),
            )
            .on_conflict_do_nothing()
            .returning(HandoffFact.handoff_id)
        )
        if inserted is not None:
            row = await _conversation_row(
                db, env.shop_id, conversation_id, p.get("channel"), env.occurred_at, zone
            )
            row.handoff_count += 1
    elif env.event_type == "messaging.conversation.taken":
        # Suhbatdagi ochiq uzatish olinadi (takror event: ochiq qolmagan — hech narsa o'zgarmaydi)
        await db.execute(
            update(HandoffFact)
            .where(
                HandoffFact.shop_id == env.shop_id,
                HandoffFact.conversation_id == conversation_id,
                HandoffFact.status == "OPEN",
                HandoffFact.opened_at <= env.occurred_at,
            )
            .values(
                status="TAKEN",
                taken_at=env.occurred_at,
                taken_by_staff_id=env.actor.id if env.actor.kind == "STAFF" else None,
            )
        )
    await touch_checkpoint(db, env, P_HANDOFFS)


# ---------------------------------------------------------------------------------------- yo'naltirish
async def apply_event(db: AsyncSession, catalog: CatalogQueryPort, env: EventEnvelope) -> None:
    """Bitta event → tegishli proyeksiya. Tinglovchilar va qayta qurish shu yerdan o'tadi."""
    if env.shop_id is None:
        return
    kind = env.event_type
    if kind.startswith("commerce.order."):
        if "status" in env.payload:
            await apply_order(db, catalog, env, await shop_zone(db, env.shop_id))
    elif kind == "commerce.quick_sale.recorded":
        await apply_quick_sale(db, catalog, env, await shop_zone(db, env.shop_id))
    elif kind == "commerce.stock.changed":
        await apply_stock(db, env)
    elif kind.startswith("support.case.") and kind != "support.case.ready_notice":
        await apply_case(db, env, await shop_zone(db, env.shop_id))
    elif kind in ("messaging.message.received", "messaging.message.queued", "messaging.message.sent"):
        await apply_message(db, env, await shop_zone(db, env.shop_id))
    elif kind in ("messaging.conversation.handed_off", "messaging.conversation.taken"):
        await apply_handoff(db, env, await shop_zone(db, env.shop_id))
