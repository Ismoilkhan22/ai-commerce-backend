"""platform.transition_log — holat o'tishlari jurnali (04 §6). Append-only, oyma-oy partition."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.ids import uuid7


class TransitionLog(Base):
    __tablename__ = "transition_log"
    __table_args__ = (
        Index("ix_transition_log_entity", "shop_id", "entity_type", "entity_id", "occurred_at"),
        {"schema": "platform", "postgresql_partition_by": "RANGE (occurred_at)"},
    )

    # Partition kaliti PK ichida bo'lishi shart (PostgreSQL)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    shop_id: Mapped[UUID | None]
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[UUID]
    command: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID | None]
    reason: Mapped[str | None] = mapped_column(Text)
    forced: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    trace_id: Mapped[str | None] = mapped_column(Text)
