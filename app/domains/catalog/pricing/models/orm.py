"""catalog.price_versions, current_prices, exchange_rates — db/catalog.dbml (DEC-121, DEC-133).

Narx va kurs tarixi o'zgarmaydi: ilova roliga UPDATE/DELETE berilmaydi (migratsiyada REVOKE).
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
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, VersionMixin


class PriceVersion(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "price_versions"
    __table_args__ = (
        UniqueConstraint("shop_id", "sku_id", "id"),
        Index("ix_price_versions_shop_id_sku_id_created_at", "shop_id", "sku_id", "created_at"),
        ForeignKeyConstraint(
            ["shop_id", "sku_id"], ["catalog.skus.shop_id", "catalog.skus.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("amount_minor > 0", name="amount_positive"),  # BL-015
        CheckConstraint("currency IN ('UZS', 'USD')", name="currency"),
        CheckConstraint("source IN ('MANUAL', 'IMPORT')", name="source"),
        {"schema": "catalog"},
    )

    sku_id: Mapped[UUID]
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="MANUAL")
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None]  # platform.memberships.id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CurrentPrice(VersionMixin, Base):
    """Har SKU'ning joriy narxi — price_versions'dagi bitta qatorga ko'rsatkich (CAS, `version`)."""

    __tablename__ = "current_prices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "sku_id"], ["catalog.skus.shop_id", "catalog.skus.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["shop_id", "sku_id", "price_version_id"],
            ["catalog.price_versions.shop_id", "catalog.price_versions.sku_id", "catalog.price_versions.id"],
            ondelete="RESTRICT",
            name="fk_current_prices_price_version",  # avtomatik nom 63 belgidan uzun
        ),
        {"schema": "catalog"},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    sku_id: Mapped[UUID] = mapped_column(primary_key=True)
    price_version_id: Mapped[UUID]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExchangeRate(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        Index("ix_exchange_rates_shop_id_effective_at", "shop_id", "effective_at"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base = 'USD' AND quote = 'UZS'", name="pair"),  # Stage 1 da faqat USD → UZS
        CheckConstraint("source IN ('MANUAL', 'CBU')", name="source"),
        {"schema": "catalog"},
    )

    base: Mapped[str] = mapped_column(Text, server_default="USD")
    quote: Mapped[str] = mapped_column(Text, server_default="UZS")
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(Text, server_default="MANUAL")
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
