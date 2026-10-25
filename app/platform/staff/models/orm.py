"""platform.principals, memberships, membership_branches, invitations, platform_staff,
platform_staff_invitations
— db/platform.dbml §foydalanuvchilar_va_rollar (DEC-131)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, TimestampMixin, VersionMixin

ROLES = ("OWNER", "MANAGER", "SALES", "WAREHOUSE")  # Stage 1 (DEC-131)
MEMBERSHIP_STATUSES = ("INVITED", "ACTIVE", "DISABLED")
PLATFORM_ROLES = ("PLATFORM_ADMIN", "PLATFORM_SUPPORT", "SPEC_EDITOR")
PLATFORM_STAFF_STATUSES = ("INVITED", "ACTIVE", "DISABLED")


class Principal(IdMixin, TimestampMixin, VersionMixin, Base):
    """Tizimga kiradigan odam. Shopga bog'liq emas — a'zolik orqali (hozircha bitta shop)."""

    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint("phone"),
        UniqueConstraint("email"),
        CheckConstraint("status IN ('ACTIVE', 'BLOCKED')", name="status"),
        CheckConstraint("phone ~ '^\\+[0-9]{10,15}$'", name="phone_e164"),
        {"schema": "platform"},
    )

    phone: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)  # Argon2id; taklif qabul qilinguncha NULL
    locale: Mapped[str] = mapped_column(Text, server_default="uz")
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(IdMixin, TimestampMixin, VersionMixin, Base):
    """Odam ↔ shop: rol, holat, filial doirasi. Bitta xodim — bitta rol (DEC-131)."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("principal_id"),  # hozircha bir odam — bitta shop (DEC-131)
        UniqueConstraint("shop_id", "principal_id"),
        UniqueConstraint("shop_id", "id"),
        CheckConstraint(f"role IN {ROLES}", name="role"),
        CheckConstraint(f"status IN {MEMBERSHIP_STATUSES}", name="status"),
        CheckConstraint("branch_scope IN ('ALL', 'SELECTED')", name="branch_scope"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(ForeignKey("platform.shops.id", ondelete="RESTRICT"))
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("platform.principals.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="INVITED")
    branch_scope: Mapped[str] = mapped_column(Text, server_default="ALL")
    invited_by: Mapped[UUID | None] = mapped_column(ForeignKey("platform.memberships.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MembershipBranch(Base):
    """Xodim qaysi filiallarda ishlaydi (branch_scope = SELECTED)."""

    __tablename__ = "membership_branches"
    __table_args__ = (
        PrimaryKeyConstraint("membership_id", "branch_id"),
        # (shop_id, …) juftligi — xodimni boshqa shopning filialiga biriktirib bo'lmaydi
        ForeignKeyConstraint(
            ["shop_id", "membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["shop_id", "branch_id"],
            ["platform.branches.shop_id", "platform.branches.id"],
            ondelete="RESTRICT",
        ),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    branch_id: Mapped[UUID]


class Invitation(IdMixin, Base):
    """Bir martalik havola: xodim taklifi yoki parolni tiklash. Tokenning o'zi emas — hash'i saqlanadi."""

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index("ix_invitations_shop_id_membership_id", "shop_id", "membership_id"),
        ForeignKeyConstraint(
            ["shop_id", "membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("purpose IN ('INVITE', 'PASSWORD_RESET')", name="purpose"),
        CheckConstraint("channel IN ('LINK', 'SMS', 'TELEGRAM')", name="channel"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, server_default="LINK")  # DEC-131: ega o'zi yuboradi
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformStaff(IdMixin, TimestampMixin, VersionMixin, Base):
    """Platforma jamoasi. Shop xodimi emas — shop ma'lumotini odatiy holatda ko'rmaydi.

    Panel orqali taklif qilinganda INVITED, havolani qabul qilgach ACTIVE (business/15 §5).
    """

    __tablename__ = "platform_staff"
    __table_args__ = (
        UniqueConstraint("principal_id"),
        CheckConstraint(f"role IN {PLATFORM_ROLES}", name="role"),
        CheckConstraint(f"status IN {PLATFORM_STAFF_STATUSES}", name="status"),
        {"schema": "platform"},
    )

    principal_id: Mapped[UUID] = mapped_column(ForeignKey("platform.principals.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    invited_by: Mapped[UUID | None] = mapped_column(ForeignKey("platform.platform_staff.id"))


class PlatformStaffInvitation(IdMixin, Base):
    """Platforma jamoasiga bir martalik havola: taklif yoki parol tiklash. Faqat token hash'i saqlanadi.

    `invitations` dan alohida: u shop a'zoligiga bog'langan va RLS ostida.
    """

    __tablename__ = "platform_staff_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index("ix_platform_staff_invitations_platform_staff_id", "platform_staff_id"),
        CheckConstraint("purpose IN ('INVITE', 'PASSWORD_RESET')", name="purpose"),
        {"schema": "platform"},
    )

    platform_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform.platform_staff.id", ondelete="CASCADE")
    )
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None]  # platform_staff.id; CLI yoki seed bo'lsa NULL
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
