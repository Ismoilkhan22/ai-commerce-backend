"""Umumiy ustunlar (07 §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.shared.db.ids import uuid7


class IdMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ShopScopedMixin:
    """Har shop jadvali (K-01). Indekslar `shop_id` dan boshlanadi; RLS siyosati shu ustunga (10 §4)."""

    shop_id: Mapped[UUID] = mapped_column(nullable=False, index=True)


class VersionMixin:
    """Optimistic lock: `If-Match` va `VERSION_CONFLICT` (12 §4).

    `version` faqat avtomatik oshadi: har UPDATE `WHERE version = <o'qilgan>` bilan ketadi.
    Qator boshqa tranzaksiyada o'zgargan bo'lsa — `StaleDataError` → 409 VERSION_CONFLICT.
    Qo'lda oshirish TAQIQ.
    """

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.version}  # type: ignore[attr-defined]
