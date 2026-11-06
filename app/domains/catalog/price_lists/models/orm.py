"""catalog.price_list_runs, price_list_items — yetkazib beruvchi narx ro'yxati (DEC-149, 1-qism).

Ega fayl yuklaydi (XLSX, CSV, PDF yoki surat) → AI qatorlarni o'qiydi va shop SKU'lariga moslaydi →
ega ustama va yaxlitlashni tanlaydi, qatorlarni tekshiradi → "N ta narxni yangilash" — oddiy narx
o'zgarishi (`PricingService.apply_price`: versiya, audit, `catalog.price.changed`). AI narx qo'ymaydi.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

RUN_STATUSES = ("READING", "READY", "APPLIED", "FAILED", "CANCELLED")
SOURCE_FORMATS = ("XLSX", "CSV", "PDF", "IMAGE")
MATCH_METHODS = ("CODE", "AI", "MANUAL", "NONE")
ITEM_RESULTS = ("APPLIED", "UNCHANGED", "SKIPPED", "ERROR")
CURRENCIES = ("UZS", "USD")


class PriceListRun(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "price_list_runs"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_price_list_runs_shop_id_created_at", "shop_id", "created_at"),
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        CheckConstraint(f"source_format IN {SOURCE_FORMATS}", name="source_format"),
        CheckConstraint("markup_percent >= 0 AND markup_percent <= 500", name="markup_percent"),
        CheckConstraint("uzs_round_minor IN (100, 10000, 100000, 1000000)", name="uzs_round_minor"),
        {"schema": "catalog"},
    )

    file_id: Mapped[UUID]  # platform.stored_files (PRICE_LIST, yopiq)
    status: Mapped[str] = mapped_column(Text, server_default="READING")
    source_format: Mapped[str] = mapped_column(Text)
    supplier_name: Mapped[str | None] = mapped_column(Text)
    markup_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default=text("0"))
    # So'mdagi taklif narxi shunga yaxlitlanadi (tiyinda): 1 so'm, 100, 1 000 yoki 10 000 so'm
    uzs_round_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("100000"))
    item_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    matched_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    applied_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None]  # platform.memberships.id
    applied_by: Mapped[UUID | None]
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceListItem(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint("shop_id", "run_id", "line_no"),
        ForeignKeyConstraint(
            ["shop_id", "run_id"],
            ["catalog.price_list_runs.shop_id", "catalog.price_list_runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["shop_id", "sku_id"], ["catalog.skus.shop_id", "catalog.skus.id"]),
        CheckConstraint(f"currency IN {CURRENCIES}", name="currency"),
        CheckConstraint(f"match_method IN {MATCH_METHODS}", name="match_method"),
        CheckConstraint(f"result IS NULL OR result IN {ITEM_RESULTS}", name="result"),
        CheckConstraint("supplier_price_minor > 0", name="supplier_price_minor"),
        {"schema": "catalog"},
    )

    run_id: Mapped[UUID]
    line_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)  # yetkazib beruvchi kodi yoki MPN
    supplier_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(Text)
    sku_id: Mapped[UUID | None]
    match_method: Mapped[str] = mapped_column(Text, server_default="NONE")
    proposed_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    proposed_currency: Mapped[str | None] = mapped_column(Text)
    manual_price: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))  # ega o'zi yozgan
    selected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    result: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
