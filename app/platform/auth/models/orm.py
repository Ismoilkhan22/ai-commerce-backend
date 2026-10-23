"""platform.sessions — refresh token sessiyalari (ADR-023, db/platform.dbml).

Har yangilanishda yangi qator (shu `family_id` bilan), eskisi `ROTATED`. Eski token qayta
ishlatilsa — butun oila bekor (`REUSE_DETECTED`). Access token bazaga yozilmaydi.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin


class AuthSession(IdMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("refresh_token_hash"),
        Index("ix_sessions_principal_id_revoked_at", "principal_id", "revoked_at"),
        Index("ix_sessions_family_id", "family_id"),
        CheckConstraint("audience IN ('shop', 'platform')", name="audience"),
        {"schema": "platform"},
    )

    principal_id: Mapped[UUID] = mapped_column(ForeignKey("platform.principals.id", ondelete="CASCADE"))
    shop_id: Mapped[UUID | None] = mapped_column(ForeignKey("platform.shops.id"))
    audience: Mapped[str] = mapped_column(Text)  # shop paneli yoki platforma paneli
    family_id: Mapped[UUID]
    refresh_token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
