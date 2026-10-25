"""commerce.quick_sales, quick_sale_lines — do'kondagi sotuv (DEC-123, db/commerce.dbml).

Xaridor ma'lumoti yo'q. Bekor qilinmaydi va o'zgarmaydi: xato sotuv — tuzatish (+) bilan to'g'rilanadi.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin


class QuickSale(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "quick_sales"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_quick_sales_shop_id_branch_id_created_at", "shop_id", "branch_id", "created_at"),
        Index("ix_quick_sales_shop_id_sold_by_created_at", "shop_id", "sold_by", "created_at"),
        Index("ix_quick_sales_shop_id_created_at", "shop_id", "created_at"),
        CheckConstraint("currency = 'UZS'", name="currency"),
        CheckConstraint("total_minor >= 0", name="total_non_negative"),
        {"schema": "commerce"},
    )

    branch_id: Mapped[UUID]
    currency: Mapped[str] = mapped_column(Text, server_default="UZS")
    total_minor: Mapped[int] = mapped_column(BigInteger)
    sold_by: Mapped[UUID]  # platform.memberships.id (BL-109)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuickSaleLine(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "quick_sale_lines"
    __table_args__ = (
        UniqueConstraint("shop_id", "quick_sale_id", "sku_id"),  # ledger kaliti bilan mos
        ForeignKeyConstraint(
            ["shop_id", "quick_sale_id"],
            ["commerce.quick_sales.shop_id", "commerce.quick_sales.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("currency IN ('UZS', 'USD')", name="currency"),
        CheckConstraint("currency = 'UZS' OR exchange_rate_snapshot IS NOT NULL", name="usd_needs_rate"),
        {"schema": "commerce"},
    )

    quick_sale_id: Mapped[UUID]
    sku_id: Mapped[UUID]  # catalog.skus.id — FK'siz
    title_snapshot: Mapped[str] = mapped_column(Text)
    sku_code_snapshot: Mapped[str] = mapped_column(Text)
    qty: Mapped[int] = mapped_column(Integer)
    price_version_id: Mapped[UUID]  # catalog.price_versions.id
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(Text)
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit_price_uzs_minor: Mapped[int] = mapped_column(BigInteger)
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
