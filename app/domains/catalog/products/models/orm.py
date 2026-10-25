"""catalog.categories, products, skus, product_media — db/catalog.dbml (DEC-133)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

PRODUCT_STATUSES = ("DRAFT", "IN_REVIEW", "PUBLISHED", "HIDDEN", "ARCHIVED")
SPEC_CATEGORIES = ("CPU", "MOTHERBOARD", "GPU", "RAM", "PSU", "CASE", "CPU_COOLER", "STORAGE")
SKU_CONDITIONS = ("NEW", "USED", "REFURBISHED")


class Category(TimestampMixin, Base):
    """Platforma ma'lumotnomasi: hamma shop uchun bitta ro'yxat, shop faqat tanlaydi (DEC-133)."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{1,39}$'", name="code_format"),
        CheckConstraint(f"spec_category IN {SPEC_CATEGORIES}", name="spec_category"),
        {"schema": "catalog"},
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(ForeignKey("catalog.categories.code"))
    name_uz: Mapped[str] = mapped_column(Text)
    name_ru: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    spec_category: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Product(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_products_shop_id_status", "shop_id", "status"),
        Index("ix_products_shop_id_category_code", "shop_id", "category_code"),
        CheckConstraint(f"status IN {PRODUCT_STATUSES}", name="status"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 300", name="title_length"),
        {"schema": "catalog"},
    )

    category_code: Mapped[str] = mapped_column(ForeignKey("catalog.categories.code", ondelete="RESTRICT"))
    brand: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None]  # platform.memberships.id


class Sku(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "skus"
    __table_args__ = (
        UniqueConstraint("shop_id", "sku_code"),  # BL-011
        UniqueConstraint("shop_id", "id"),
        Index("ix_skus_shop_id_product_id", "shop_id", "product_id"),
        # Katta-kichik harfsiz qidiruv uchun (yagonalik — service'da, tranzaksiya qulfi bilan)
        Index("ix_skus_shop_id_sku_code_lower", "shop_id", text("lower(sku_code)")),
        ForeignKeyConstraint(
            ["shop_id", "product_id"],
            ["catalog.products.shop_id", "catalog.products.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"condition IN {SKU_CONDITIONS}", name="condition"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status"),
        CheckConstraint("warranty_months >= 0", name="warranty_months"),
        CheckConstraint("char_length(sku_code) BETWEEN 1 AND 64", name="sku_code_length"),
        {"schema": "catalog"},
    )

    product_id: Mapped[UUID]
    sku_code: Mapped[str] = mapped_column(Text)
    variant_name: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(Text, server_default="NEW")
    mpn: Mapped[str | None] = mapped_column(Text)
    mpn_normalized: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    # Xodim bog'lanishni qo'lda uzgan — avtomatika qayta bog'lamaydi, xodim o'zi bog'laguncha
    spec_autolink_blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ProductMedia(IdMixin, ShopScopedMixin, Base):
    """Mahsulot rasmlari. Fayl `platform.stored_files` da — FK'siz (boshqa schema)."""

    __tablename__ = "product_media"
    __table_args__ = (
        UniqueConstraint("shop_id", "file_id"),  # bitta fayl — bitta mahsulot rasmi
        Index("ix_product_media_shop_id_product_id_position", "shop_id", "product_id", "position"),
        ForeignKeyConstraint(
            ["shop_id", "product_id"], ["catalog.products.shop_id", "catalog.products.id"], ondelete="CASCADE"
        ),
        {"schema": "catalog"},
    )

    product_id: Mapped[UUID]
    file_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
