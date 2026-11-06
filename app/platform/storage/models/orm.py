"""platform.stored_files — fayl haqida yozuv (db/catalog.dbml "Fayllar", S0-08). Baytlar — FileStorage'da."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin

FILE_PURPOSES = (
    "PRODUCT_IMAGE",
    "STOCK_EVIDENCE",
    "IMPORT_FILE",
    "EXPORT_FILE",
    "SITE_LOGO",
    "CHAT_ATTACHMENT",  # 5b: suhbat rasmi (xaridor yuborgan yoki operator biriktirgan), yopiq
    "SUPPORT_EVIDENCE",  # 7b: kafolat murojaati rasmi (nuqson, chek), yopiq
    "PRICE_LIST",  # DEC-149: yetkazib beruvchi narx ro'yxati (XLSX, CSV, PDF yoki rasm), yopiq
)


class StoredFile(IdMixin, Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        UniqueConstraint("object_key"),
        UniqueConstraint("shop_id", "id"),
        Index("ix_stored_files_shop_id_purpose_status", "shop_id", "purpose", "status"),
        CheckConstraint(f"purpose IN {FILE_PURPOSES}", name="purpose"),
        CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="status"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(ForeignKey("platform.shops.id", ondelete="RESTRICT"))
    purpose: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    original_name: Mapped[str | None] = mapped_column(Text)  # faqat ko'rsatish uchun, logga yozilmaydi
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    uploaded_by: Mapped[UUID | None]  # platform.memberships.id
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
