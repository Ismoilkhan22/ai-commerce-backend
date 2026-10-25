"""Texnik ma'lumotlar kutubxonasi (platforma) va shop SKU bog'lanishlari — db/catalog.dbml (DEC-011, DEC-120).

`reference_hardware_specs` va `..._versions` — shop_id yo'q: platforma panelidan yoziladi, shoplar o'qiydi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
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

from app.domains.catalog.products.models.orm import SPEC_CATEGORIES
from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin


class ReferenceHardwareSpec(IdMixin, TimestampMixin, Base):
    __tablename__ = "reference_hardware_specs"
    __table_args__ = (
        # Nomlar qo'lda: avtomatik nom PostgreSQL'ning 63 belgilik chegarasidan uzun.
        # Yagonalik faqat eskirmagan modellar orasida: eskirgan model qayta kiritishga to'sqinlik qilmaydi
        Index(
            "uq_reference_hardware_specs_model",
            "category",
            "brand_normalized",
            "model_normalized",
            "variant_key",
            unique=True,
            postgresql_where=text("status <> 'RETIRED'"),
        ),
        Index(
            "uq_reference_hardware_specs_mpn_normalized",
            "mpn_normalized",
            unique=True,
            postgresql_where=text("mpn_normalized IS NOT NULL AND status <> 'RETIRED'"),
        ),
        CheckConstraint(f"category IN {SPEC_CATEGORIES}", name="category"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED', 'RETIRED')", name="status"),
        {"schema": "catalog"},
    )

    category: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(Text)
    brand_normalized: Mapped[str] = mapped_column(Text)  # "QA Race" = "qa race" (yagonalik shu bo'yicha)
    model_name: Mapped[str] = mapped_column(Text)
    model_normalized: Mapped[str] = mapped_column(Text)
    variant_key: Mapped[str] = mapped_column(Text, server_default="")
    mpn: Mapped[str | None] = mapped_column(Text)
    mpn_normalized: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    # Tasdiqlangan ma'lumot versiyasi (optimistik qulf emas — har tasdiqda oshadi)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by: Mapped[UUID | None]  # platform.principals.id
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReferenceHardwareSpecVersion(Base):
    """Ikki ko'z (engineering/17 §10): har yangi spec va o'zgarish avval PENDING, boshqa odam tasdiqlaydi."""

    __tablename__ = "reference_hardware_spec_versions"
    __table_args__ = (
        Index("ix_reference_hardware_spec_versions_status_proposed_at", "status", "proposed_at"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="status"),
        {"schema": "catalog"},
    )

    spec_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "catalog.reference_hardware_specs.id",
            ondelete="CASCADE",
            name="fk_reference_hardware_spec_versions_spec_id",
        ),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(Text)
    variant_key: Mapped[str] = mapped_column(Text, server_default="")
    mpn: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    proposed_by: Mapped[UUID]  # platform.principals.id
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class SkuSpecLink(Base):
    __tablename__ = "sku_spec_links"
    __table_args__ = (
        Index("ix_sku_spec_links_spec_id", "spec_id"),
        ForeignKeyConstraint(
            ["shop_id", "sku_id"], ["catalog.skus.shop_id", "catalog.skus.id"], ondelete="CASCADE"
        ),
        CheckConstraint("method IN ('AUTO_MPN', 'AUTO_MODEL', 'MANUAL')", name="method"),
        {"schema": "catalog"},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    sku_id: Mapped[UUID] = mapped_column(primary_key=True)
    spec_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.reference_hardware_specs.id", ondelete="RESTRICT")
    )
    method: Mapped[str] = mapped_column(Text)
    linked_by: Mapped[UUID | None]  # platform.memberships.id — MANUAL bo'lsa
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpecRequest(IdMixin, ShopScopedMixin, Base):
    """Shopning "yangi model qo'shing" so'rovi → platforma navbati (DEC-120)."""

    __tablename__ = "spec_requests"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_spec_requests_status_created_at", "status", "created_at"),
        Index("ix_spec_requests_shop_id_status", "shop_id", "status"),
        ForeignKeyConstraint(
            ["shop_id", "sku_id"], ["catalog.skus.shop_id", "catalog.skus.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"category IN {SPEC_CATEGORIES}", name="category"),
        CheckConstraint("status IN ('OPEN', 'RESOLVED', 'REJECTED')", name="status"),
        {"schema": "catalog"},
    )

    sku_id: Mapped[UUID | None]
    category: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(Text)
    mpn: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="OPEN")
    resolved_spec_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalog.reference_hardware_specs.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[UUID | None]  # platform.memberships.id
    resolved_by: Mapped[UUID | None]  # platform.principals.id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
