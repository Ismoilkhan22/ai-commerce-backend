"""platform.shops, branches, shop_policies, shop_notes — db/platform.dbml (DEC-131, business/15)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, TimestampMixin, VersionMixin

SHOP_STATUSES = ("DRAFT", "PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "CLOSED")


class Shop(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "shops"
    __table_args__ = (
        UniqueConstraint("slug"),
        UniqueConstraint("tin"),
        CheckConstraint(f"status IN {SHOP_STATUSES}", name="status"),
        CheckConstraint("deployment_mode IN ('SHARED', 'DEDICATED')", name="deployment_mode"),
        CheckConstraint("signup_source IN ('PLATFORM', 'SELF')", name="signup_source"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'", name="slug_format"),
        CheckConstraint("tin ~ '^[0-9]{9}$'", name="tin_format"),
        {"schema": "platform"},
    )

    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    legal_name: Mapped[str | None] = mapped_column(Text)
    tin: Mapped[str] = mapped_column(Text)  # STIR — majburiy (DEC-131)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    default_locale: Mapped[str] = mapped_column(Text, server_default="uz")
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Tashkent")
    deployment_mode: Mapped[str] = mapped_column(Text, server_default="SHARED")
    # M21: PLATFORM — platforma admini ochgan; SELF — ega o'zi ro'yxatdan o'tgan (tekshiruvdan keyin ACTIVE)
    signup_source: Mapped[str] = mapped_column(Text, server_default="PLATFORM")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Branch(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_branches_shop_id_status", "shop_id", "status"),
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="status"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(ForeignKey("platform.shops.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    working_hours: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_pickup_point: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")


class ShopPolicy(VersionMixin, Base):
    __tablename__ = "shop_policies"
    __table_args__ = (
        CheckConstraint("quote_approval_mode IN ('ALL', 'RISKY_ONLY')", name="quote_approval_mode"),
        CheckConstraint("exchange_rate_source IN ('MANUAL', 'CBU')", name="exchange_rate_source"),
        CheckConstraint("stock_display IN ('EXACT', 'STATUS_ONLY')", name="stock_display"),
        CheckConstraint(
            "discount_limit_sales_pct BETWEEN 0 AND 100 AND discount_limit_manager_pct BETWEEN 0 AND 100",
            name="discount_limits",
        ),
        CheckConstraint("quote_ttl_hours > 0 AND low_stock_threshold >= 0", name="positive_values"),
        CheckConstraint("handoff_reminder_minutes BETWEEN 1 AND 1440", name="handoff_reminder_minutes"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform.shops.id", ondelete="RESTRICT"), primary_key=True
    )
    quote_ttl_hours: Mapped[int] = mapped_column(Integer, server_default="24")
    discount_limit_sales_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="0")
    discount_limit_manager_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="5")
    order_reminder_hours: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{24,72}")
    quote_approval_mode: Mapped[str] = mapped_column(Text, server_default="ALL")
    exchange_rate_source: Mapped[str] = mapped_column(Text, server_default="MANUAL")
    stock_display: Mapped[str] = mapped_column(Text, server_default="STATUS_ONLY")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, server_default="2")
    # Shop yetkazib beradimi: o'chiq bo'lsa sayt formasida faqat "olib ketish" (storefront.md §8)
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Operator kutayotgan suhbat eslatmasi va ish vaqti (DEC-139, 5-qaror; 5b — inbox ishlatadi)
    handoff_reminder_minutes: Mapped[int] = mapped_column(Integer, server_default="15")
    inbox_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # bo'sh — doim ish vaqti
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ShopNote(IdMixin, Base):
    """Platformaning ichki izohi — shop ko'rmaydi (business/15 §3). Faqat qo'shiladi, tahrir yo'q.

    RLS'siz: faqat platforma panelidan o'qiladi.
    """

    __tablename__ = "shop_notes"
    __table_args__ = (
        Index("ix_shop_notes_shop_id_created_at", "shop_id", "created_at"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="body_length"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(ForeignKey("platform.shops.id", ondelete="RESTRICT"))
    author_id: Mapped[UUID] = mapped_column(ForeignKey("platform.platform_staff.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignupRequest(IdMixin, Base):
    """M21: shopning o'zi ro'yxatdan o'tishi — telefon tasdig'i. Shop hali yo'q, shuning uchun RLS'siz
    (principals kabi); kod faqat xesh bilan, 10 daqiqa, 5 urinish."""

    __tablename__ = "signup_requests"
    __table_args__ = (
        Index("ix_signup_requests_phone_created_at", "phone", "created_at"),
        CheckConstraint("attempts >= 0 AND attempts <= 10", name="attempts"),
        {"schema": "platform"},
    )

    phone: Mapped[str] = mapped_column(Text)  # E.164
    code_hash: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sends: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shop_id: Mapped[UUID | None]  # yaratilgan shop (audit uchun)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
