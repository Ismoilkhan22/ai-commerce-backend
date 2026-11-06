"""Realtime signal tarqatish (08 §6.3): event COMMIT bo'lgandan keyin — kimga signal ketishi BAZADAN.

Inline tinglovchi (05 §5.1): arzon, faqat signal. Kimga:
- `notification.created` — qabul qiluvchining o'ziga;
- `task.created` / `task.closed` — biriktirilgan xodim, rol egalari (filial bo'yicha), ega va menejer;
- `order.changed` — biriktirilgan operator, ega va menejer (filial), omborchi (tasdiqlangandan keyin —
  va undan CHIQIB ketganda ham, masalan tasdiqlangan buyurtma bekor qilinsa: ro'yxatidan o'chadi),
  "tasdiq kutilmoqda" navbatiga kirgan yoki undan chiqqan buyurtma — operatorlar navbati;
- `stock.changed` — qoldiqni ko'radigan rollar (filial bo'yicha);
- `conversation.changed` / `message.created` (5b) — mas'ul operator (va avvalgisi, suhbat undan olinsa),
  ega va menejer; biriktirilmagan yoki "operator kerak" suhbat — operatorlar navbati.
Signalda faqat tur, resurs ID'si va versiyasi — matn, ism, telefon YO'Q (TC-SEC-08).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.platform.notifications.services.recipients import resolve_members
from app.shared.events.envelope import EventEnvelope
from app.shared.events.registry import EventContext, subscriber
from app.shared.realtime import RealtimeBroker
from app.shared.tracing.context import trace_id_from_traceparent

SUPERVISORS = ("OWNER", "MANAGER")
STOCK_ROLES = ("OWNER", "MANAGER", "WAREHOUSE", "SALES")
WAREHOUSE_STATUSES = frozenset({"CONFIRMED", "PROCESSING", "EXCEPTION", "COMPLETED"})


def _uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


def _message(
    envelope: EventEnvelope, kind: str, type_: str, resource_id: Any, **extra: Any
) -> dict[str, Any]:
    return {
        "type": type_,
        "shop_id": str(envelope.shop_id),
        "resource": {"kind": kind, "id": str(resource_id), "version": envelope.aggregate_version, **extra},
        "trace_id": trace_id_from_traceparent(envelope.traceparent),
    }


async def _route(ctx: EventContext) -> tuple[list[UUID], dict[str, Any] | None]:
    env, db = ctx.envelope, ctx.session
    assert env.shop_id is not None
    p, t = env.payload, env.event_type
    if t == "platform.notification.created":
        target = _uuid(p.get("recipient_membership_id"))
        return ([target] if target else []), _message(
            env, "notification", "notification.created", p["notification_id"]
        )
    if t in ("platform.task.created", "platform.task.closed"):
        branch = _uuid(p.get("branch_id"))
        role = p.get("assignee_role")
        members = await resolve_members(
            db,
            env.shop_id,
            membership_ids=[_uuid(p.get("assignee_membership_id"))],
            roles=[*SUPERVISORS, *([role] if role else [])],
            branch_id=branch,
        )
        kind = "task.created" if t.endswith("created") else "task.closed"
        return [m.membership_id for m in members], _message(env, "task", kind, p["task_id"])
    if t.startswith("commerce.order."):
        branch = _uuid(p.get("branch_id"))
        status, assigned = p.get("status"), _uuid(p.get("assigned_staff_id"))
        from_status = p.get("from_status")
        roles = list(SUPERVISORS)
        # Omborchi ko'radigan holatga kirdi YOKI undan chiqdi — ikkalasida signal (QA 5a F7)
        if status in WAREHOUSE_STATUSES or from_status in WAREHOUSE_STATUSES:
            roles.append("WAREHOUSE")
        # Biriktirilmagan navbat — operatorlar o'ziga oladi; olingan yoki tasdiqlangani navbatdan chiqadi
        queue_changed = from_status == "PENDING_CONFIRMATION" or t == "commerce.order.assigned"
        if (status == "PENDING_CONFIRMATION" and assigned is None) or queue_changed:
            roles.append("SALES")
        members = await resolve_members(
            db, env.shop_id, membership_ids=[assigned], roles=roles, branch_id=branch
        )
        return [m.membership_id for m in members], _message(env, "order", "order.changed", p["order_id"])
    if t.startswith("messaging."):
        conversation = _uuid(p.get("conversation_id"))
        if conversation is None:
            return [], None
        assigned, previous = _uuid(p.get("assignee_membership_id")), _uuid(p.get("previous_assignee_id"))
        roles = list(SUPERVISORS)
        if (
            assigned is None
            or p.get("status") == "HUMAN_NEEDED"
            or previous is not None
            or p.get("left_queue")
        ):
            # navbatdagi suhbat yoki navbatdan olingan — hamma operator ro'yxati yangilanadi (QA 5b L2)
            roles.append("SALES")
        members = await resolve_members(db, env.shop_id, membership_ids=[assigned, previous], roles=roles)
        targets = [m.membership_id for m in members]
        if t.startswith("messaging.message."):
            return targets, _message(
                env, "message", "message.created", env.aggregate_id, conversation_id=str(conversation)
            )
        return targets, _message(env, "conversation", "conversation.changed", conversation)
    if t == "catalog.import.changed":  # import ekrani: kim boshlagan / tasdiqlagan, ega va menejer
        members = await resolve_members(
            db,
            env.shop_id,
            membership_ids=[_uuid(p.get("created_by")), _uuid(p.get("committed_by"))],
            roles=SUPERVISORS,
        )
        return [m.membership_id for m in members], _message(env, "import", "import.changed", p["batch_id"])
    if t == "commerce.stock.changed":
        branch = _uuid(p.get("branch_id"))
        members = await resolve_members(db, env.shop_id, roles=STOCK_ROLES, branch_id=branch)
        return [m.membership_id for m in members], _message(
            env, "stock", "stock.changed", p["sku_id"], branch_id=str(branch) if branch else None
        )
    return [], None


@subscriber(
    "platform.realtime_fanout",
    "platform.notification.created",
    "platform.task.created",
    "platform.task.closed",
    "commerce.order.*",
    "commerce.stock.changed",
    "messaging.conversation.*",
    "messaging.message.*",
    "catalog.import.changed",
    schema="platform",
    inline=True,
)
async def realtime_fanout(ctx: EventContext) -> None:
    if ctx.envelope.shop_id is None:
        return
    targets, message = await _route(ctx)
    if message is None:
        return
    broker: RealtimeBroker = ctx.services.realtime
    for membership_id in dict.fromkeys(targets):  # takrorsiz, tartib saqlanadi
        await broker.publish(membership_id, message)
