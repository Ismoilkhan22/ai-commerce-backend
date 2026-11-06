"""platform.dead_letters, platform.job_runs (db/jobs.md §3–4). Shoplararo, RLS yo'q — faqat platforma."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin


class DeadLetter(IdMixin, Base):
    """8 urinishda bajarib bo'lmagan tinglovchi ishi (05 §7). Qayta yuborish xavfsiz — consumer_receipts."""

    __tablename__ = "dead_letters"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer"),
        CheckConstraint("status IN ('OPEN', 'REPLAYED', 'IGNORED')", name="status"),
        Index("ix_dead_letters_status_created_at", "status", "created_at"),
        Index("ix_dead_letters_shop_id_created_at", "shop_id", "created_at"),
        {"schema": "platform"},
    )

    event_id: Mapped[UUID] = mapped_column(nullable=False)
    source_schema: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    consumer: Mapped[str] = mapped_column(Text, nullable=False)
    shop_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, nullable=False)  # xato turi va qisqa matn — PII'siz
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="OPEN", nullable=False)
    resolved_by: Mapped[UUID | None] = mapped_column(nullable=True)  # platforma xodimi (principal)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobRun(IdMixin, Base):
    """Rejali ish jurnali (4-qaror): monitoring kelgunga qadar "ish oxirgi marta qachon ishladi?"."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'OK', 'FAILED', 'SKIPPED')", name="status"),
        Index("ix_job_runs_job_name_started_at", "job_name", "started_at"),
        Index("ix_job_runs_started_at", "started_at"),
        {"schema": "platform"},
    )

    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    affected: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
