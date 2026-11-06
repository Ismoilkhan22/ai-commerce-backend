"""platform.plans, subscriptions, invoices — M26 tariflar va to'lov (Stage 2).

To'lov tizimdan tashqarida (DEC-100): hisob-faktura chiqariladi, platforma admini "to'landi" deb belgilaydi.
Avtomatik yechib olish yo'q — kutilmagan to'lov olinmaydi (BL-083). Narxlar founder qarori bilan kiritiladi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, VersionMixin

SUBSCRIPTION_STATUSES = ("TRIAL", "ACTIVE", "PAST_DUE", "CANCELLED")
INVOICE_STATUSES = ("ISSUED", "PAID", "VOID")


class Plan(Base):
    """Tarif: limitlar (`branches`, `staff`, `skus`, `ai_replies`) va oylik narx (so'm, tiyinda)."""

    __tablename__ = "plans"
    __table_args__ = ({"schema": "platform"},)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    monthly_price_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)  # None — narx hali belgilanmagan
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Subscription(VersionMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(f"status IN {SUBSCRIPTION_STATUSES}", name="status"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="TRIAL")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pending_plan_code: Mapped[str | None] = mapped_column(Text)  # keyingi davrdan (BL-083: sana aniq)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Invoice(IdMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("number"),
        # Bir davrga bitta amaldagi hisob; bekor qilingani (VOID) o'rniga yangisi chiqishi mumkin (QA #4)
        Index(
            "uq_invoices_shop_period_live",
            "shop_id",
            "period_start",
            unique=True,
            postgresql_where=text("status <> 'VOID'"),
        ),
        Index("ix_invoices_status_due_at", "status", "due_at"),
        CheckConstraint(f"status IN {INVOICE_STATUSES}", name="status"),
        CheckConstraint("amount_uzs_minor >= 0", name="amount"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID]
    number: Mapped[str] = mapped_column(Text)
    plan_code: Mapped[str] = mapped_column(Text)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_uzs_minor: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, server_default="ISSUED")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
