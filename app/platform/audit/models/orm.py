"""audit.audit_entries — append-only o'zgarishlar tarixi (07 §4.2, M20). Oyma-oy partition."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.ids import uuid7


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entries_shop_time", "shop_id", "occurred_at"),
        Index("ix_audit_entries_entity", "shop_id", "entity_type", "entity_id"),
        {"schema": "audit", "postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    shop_id: Mapped[UUID | None]  # platforma amallarida NULL
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID | None]
    action: Mapped[str] = mapped_column(Text)  # "commerce.order.confirmed"
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[UUID | None]
    entity_version: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # PII'siz
    trace_id: Mapped[str | None] = mapped_column(Text)
