"""`write_outbox` — event'ni biznes o'zgarishi bilan BITTA tranzaksiyada yozish (05 §4, ADR-033).

    await write_outbox(
        db, schema="commerce", event_type="commerce.order.confirmed", actor=actor,
        shop_id=order.shop_id, aggregate_type="commerce.order", aggregate_id=order.id,
        aggregate_version=order.version, payload={"order_id": order.id, ...},
    )

COMMIT bo'lmasa event ham yo'q; COMMIT bo'lsa — `app.workers.outbox_worker` uni albatta tarqatadi.
Service hech qachon arq'ga o'zi vazifa qo'ymaydi.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.clock import utcnow
from app.shared.db.ids import uuid7
from app.shared.events.envelope import ActorKind, EventActor, EventEnvelope
from app.shared.events.models import outbox_table
from app.shared.events.pii import check_payload
from app.shared.serialization import to_json_compatible
from app.shared.tracing.context import get_request_id, get_trace_id
from app.shared.types.actor import ActorContext

_ACTOR_KINDS: dict[str, ActorKind] = {
    "STAFF": "STAFF",
    "PLATFORM": "PLATFORM_ADMIN",
    "SYSTEM": "SYSTEM",
    "AI_AGENT": "AI",
    "CUSTOMER": "CUSTOMER",
}


def event_actor(actor: ActorContext) -> EventActor:
    return EventActor(kind=_ACTOR_KINDS.get(actor.actor_type, "SYSTEM"), id=actor.actor_id)


def _traceparent() -> str | None:
    """Trace HTTP → outbox → arq bo'ylab davom etadi (W3C, 09)."""
    trace_id = get_trace_id()
    return f"00-{trace_id}-{secrets.token_hex(8)}-01" if trace_id else None


async def write_outbox(
    db: AsyncSession,
    *,
    schema: str,
    event_type: str,
    actor: ActorContext,
    shop_id: UUID | None,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    payload: dict[str, Any],
    causation_id: UUID | None = None,
) -> EventEnvelope:
    payload = to_json_compatible(payload)
    check_payload(payload)
    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=event_type,
        shop_id=shop_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        occurred_at=utcnow(),
        actor=event_actor(actor),
        traceparent=_traceparent(),
        correlation_id=get_request_id(),
        causation_id=causation_id,
        payload=payload,
    )
    await db.execute(
        insert(outbox_table(schema)).values(
            event_id=envelope.event_id,
            event_type=event_type,
            shop_id=shop_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            envelope=envelope.model_dump(mode="json"),
            occurred_at=envelope.occurred_at,
        )
    )
    return envelope
