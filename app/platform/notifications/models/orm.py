"""platform.notifications, staff_tasks, staff_notification_settings, staff_telegram_links, telegram_link_codes
(db/notifications.dbml, DEC-139).

`shop_message_templates` — shop o'zgartirgan xaridor matnlari (5b, DEC-139 1-qaror); standart matnlar kodda.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, VersionMixin

RECIPIENT_TYPES = ("CUSTOMER", "STAFF")
NOTIFICATION_STATUSES = ("PENDING", "SCHEDULED", "SENT", "FAILED", "SUPPRESSED")
PRIORITIES = ("HIGH", "NORMAL", "LOW")
TASK_STATUSES = ("OPEN", "DONE", "RESOLVED", "CANCELLED")


class Notification(IdMixin, ShopScopedMixin, Base):
    """Har qabul qiluvchiga bitta qator (2-qaror). Xodim uchun panelda doim bor; `status` — platforma
    botiga yetkazish (FSM-12). Bir hodisa — bitta xabar: `dedup_key` unikal (BL-060)."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "dedup_key"),
        CheckConstraint(f"recipient_type IN {RECIPIENT_TYPES}", name="recipient_type"),
        CheckConstraint(f"status IN {NOTIFICATION_STATUSES}", name="status"),
        CheckConstraint(f"priority IN {PRIORITIES}", name="priority"),
        CheckConstraint(
            "recipient_type <> 'STAFF' OR recipient_membership_id IS NOT NULL", name="staff_recipient"
        ),
        ForeignKeyConstraint(["shop_id"], ["platform.shops.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["shop_id", "recipient_membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_notifications_recipient_created", "shop_id", "recipient_membership_id", "created_at"),
        Index(
            "ix_notifications_unread",
            "shop_id",
            "recipient_membership_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        Index(
            "ix_notifications_scheduled",
            "status",
            "scheduled_at",
            postgresql_where=text("status = 'SCHEDULED'"),
        ),
        {"schema": "platform"},
    )

    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_type: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    conversation_id: Mapped[UUID | None] = mapped_column(nullable=True)  # xaridor — 5b
    priority: Mapped[str] = mapped_column(Text, server_default="NORMAL", nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    aggregate_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )  # telefon va manzil YO'Q
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StaffTask(IdMixin, ShopScopedMixin, VersionMixin, Base):
    """ "Kimdir biror narsa qilishi kerak" (20 §9). Domen yaratadi va sabab yo'qolganda o'zi yopadi
    (`RESOLVED`); xodim "bajarildi" deydi (`DONE`). `dedup_key` — rejali ish ikki marta ishlasa ham bitta."""

    __tablename__ = "staff_tasks"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "dedup_key"),
        CheckConstraint(f"status IN {TASK_STATUSES}", name="status"),
        CheckConstraint(f"priority IN {PRIORITIES}", name="priority"),
        CheckConstraint(
            "assignee_membership_id IS NOT NULL OR assignee_role IS NOT NULL", name="has_assignee"
        ),
        ForeignKeyConstraint(["shop_id"], ["platform.shops.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["shop_id", "assignee_membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["shop_id", "branch_id"],
            ["platform.branches.shop_id", "platform.branches.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_staff_tasks_assignee", "shop_id", "status", "assignee_membership_id"),
        Index("ix_staff_tasks_role", "shop_id", "status", "assignee_role", "branch_id"),
        Index("ix_staff_tasks_subject", "shop_id", "subject_type", "subject_id"),
        {"schema": "platform"},
    )

    type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(nullable=True)
    assignee_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    assignee_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(Text, server_default="NORMAL", nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )  # ekran uchun: order_number, hours — PII yo'q
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="OPEN", nullable=False)
    resolved_by: Mapped[UUID | None] = mapped_column(nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StaffNotificationSettings(ShopScopedMixin, VersionMixin, Base):
    """Xodimning o'z sozlamasi. Yozuv yo'q — standart: tinch soat yo'q, bot yoqilgan."""

    __tablename__ = "staff_notification_settings"
    __table_args__ = (
        UniqueConstraint("shop_id", "membership_id"),
        ForeignKeyConstraint(
            ["shop_id", "membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            ondelete="CASCADE",
            name="fk_staff_notification_settings_membership",  # avtomatik nom 63 belgidan uzun
        ),
        {"schema": "platform"},
    )

    membership_id: Mapped[UUID] = mapped_column(primary_key=True)
    quiet_from: Mapped[time | None] = mapped_column(Time, nullable=True)  # shop vaqti
    quiet_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    muted_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StaffTelegramLink(Base):
    """Xodim ↔ platforma boti (DEC-129). Odam bo'yicha (bot hamma shop uchun bitta).

    RLS'siz (`principals` kabi identity jadval): bot webhook'i kodni xeshi bo'yicha topadi, yetkazish ishi
    esa qabul qiluvchining ulanishini o'qiydi — ikkalasida ham "joriy odam" konteksti yo'q. Faqat service
    kodi orqali.
    """

    __tablename__ = "staff_telegram_links"
    __table_args__ = (
        Index(
            "uq_staff_telegram_links_telegram_user_id",
            "telegram_user_id",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
        {"schema": "platform"},
    )

    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform.principals.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)


class TelegramLinkCode(IdMixin, Base):
    """Bir martalik bog'lash kodi (10 daqiqa). Kodning o'zi saqlanmaydi — faqat SHA-256 xeshi."""

    __tablename__ = "telegram_link_codes"
    __table_args__ = (
        UniqueConstraint("code_hash"),
        Index("ix_telegram_link_codes_principal_created", "principal_id", "created_at"),
        {"schema": "platform"},
    )

    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform.principals.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShopMessageTemplate(IdMixin, ShopScopedMixin, Base):
    """Shop o'zgartirgan xaridor matni (db/notifications.md §1). Har tahrir — yangi versiya; kalit + til uchun
    bittasi faol. Platforma standart matnlari bazada emas — kodda (`customer_templates.py`)."""

    __tablename__ = "shop_message_templates"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "template_key", "locale", "version"),
        Index(
            "uq_shop_message_templates_active",
            "shop_id",
            "template_key",
            "locale",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("template_key LIKE 'customer.%'", name="customer_key"),
        CheckConstraint("locale IN ('uz', 'ru', 'en')", name="locale"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 1000", name="body_length"),
        CheckConstraint("version > 0", name="version_positive"),
        ForeignKeyConstraint(["shop_id"], ["platform.shops.id"], ondelete="RESTRICT"),
        {"schema": "platform"},
    )

    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)  # platform.memberships.id (ega)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
