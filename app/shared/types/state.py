"""Holat o'tishi qoidasi (04 §3, ADR-034). Har qoida — `business/05` dagi bitta strelka."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.shared.types.actor import ActorType


class StateMachineRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_type: str = Field(pattern=r"^[a-z_]+\.[a-z_]+$")  # "commerce.order"
    command: str = Field(pattern=r"^[A-Z][A-Z_]*$")  # "CONFIRM"
    from_status: str = Field(pattern=r"^[A-Z][A-Z_]*$")
    to_status: str = Field(pattern=r"^[A-Z][A-Z_]*$")
    # Kim TURI bajara oladi. Aniq rol (operator / menejer) — ruxsat qatlamida (10).
    actors: frozenset[ActorType]
    requires_reason: bool = False
    business_ref: str  # "FSM-08"
