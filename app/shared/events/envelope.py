"""Event envelope (K-08, 05 §3): event'ning to'liq ko'rinishi — outbox'da `envelope jsonb`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ActorKind = Literal["STAFF", "AI", "SYSTEM", "CUSTOMER", "PLATFORM_ADMIN"]


class EventActor(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ActorKind
    id: UUID | None = None


class EventEnvelope(BaseModel):
    """`payload` — faqat ID va minimal fakt (05 §3.1): ism, telefon, manzil, matn, token yo'q."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    event_type: str
    schema_version: int = 1
    shop_id: UUID | None
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    actor: EventActor
    traceparent: str | None = None
    correlation_id: str | None = None
    causation_id: UUID | None = None
    payload: dict[str, Any]
