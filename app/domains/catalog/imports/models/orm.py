"""catalog.import_batches, import_mappings, import_rows, import_stock_rows — db/catalog_import.dbml."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

IMPORT_STATUSES = (
    "PARSING",
    "UPLOADED",
    "MAPPED",
    "VALIDATING",
    "VALIDATED",
    "COMMITTING",
    "STOCK_PENDING",
    "COMPLETED",
    "FAILED",
    "EXPIRED",
    "CANCELLED",
)
ACTIVE_STATUSES = ("VALIDATING", "COMMITTING", "STOCK_PENDING")  # shopda bittadan ko'p bo'lmaydi
# STOCK_ONLY — omborchi importi: faqat mavjud SKU qoldig'i, katalogga tegilmaydi (DEC-140, 2-qaror)
CONFLICT_POLICIES = ("CREATE_ONLY", "UPDATE_EXISTING", "UPDATE_PRICE_ONLY", "STOCK_ONLY")
FILE_FORMATS = ("XLSX", "CSV")
ROW_ACTIONS = ("CREATE", "UPDATE", "SKIP", "ERROR")
ROW_RESULTS = ("CREATED", "UPDATED", "SKIPPED", "ERROR")
SPEC_MATCHES = ("MPN", "MODEL", "MULTIPLE", "NONE", "NOT_APPLICABLE")


class ImportMapping(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Shopning saqlangan ustun moslash shabloni — keyingi importda avtomatik taklif."""

    __tablename__ = "import_mappings"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "name"),
        CheckConstraint(f"conflict_policy IN {CONFLICT_POLICIES}", name="conflict_policy"),
        {"schema": "catalog"},
    )

    name: Mapped[str] = mapped_column(Text)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB)
    conflict_policy: Mapped[str] = mapped_column(Text, server_default="UPDATE_EXISTING")
    created_by: Mapped[UUID]  # platform.memberships.id


class ImportBatch(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Bitta import jarayoni (18 §10). Faylning o'zi — `platform.stored_files` (IMPORT_FILE, yopiq)."""

    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_import_batches_shop_id_created_at", "shop_id", "created_at"),
        # Shopda bitta faol import (18 §3, 4-qoida): ikkinchisi — 409 IMPORT_ALREADY_RUNNING
        Index(
            "uq_import_batches_one_active",
            "shop_id",
            unique=True,
            postgresql_where=text(f"status IN {ACTIVE_STATUSES}"),
        ),
        ForeignKeyConstraint(
            ["shop_id", "mapping_id"],
            ["catalog.import_mappings.shop_id", "catalog.import_mappings.id"],
            ondelete="RESTRICT",  # shablonlar o'chirilmaydi
            name="fk_import_batches_mapping",
        ),
        CheckConstraint(f"status IN {IMPORT_STATUSES}", name="status"),
        CheckConstraint(f"conflict_policy IN {CONFLICT_POLICIES}", name="conflict_policy"),
        CheckConstraint(f"file_format IN {FILE_FORMATS}", name="file_format"),
        {"schema": "catalog"},
    )

    file_id: Mapped[UUID]  # platform.stored_files.id — FK'siz (boshqa schema)
    original_filename: Mapped[str] = mapped_column(Text)
    file_format: Mapped[str] = mapped_column(Text)
    sheet_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="UPLOADED")
    conflict_policy: Mapped[str] = mapped_column(Text, server_default="UPDATE_EXISTING")
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mapping_id: Mapped[UUID | None]
    detected_columns: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    default_branch_id: Mapped[UUID | None]  # platform.branches.id
    has_stock_rows: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    total_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    processed_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID]  # platform.memberships.id
    committed_by: Mapped[UUID | None]
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(ShopScopedMixin, Base):
    """Sinov va yozish natijasi har qator uchun. Xatolar CSV'si shu jadvaldan. 30 kun saqlanadi."""

    __tablename__ = "import_rows"
    __table_args__ = (
        PrimaryKeyConstraint("shop_id", "batch_id", "row_number"),
        Index("ix_import_rows_sku_code", "shop_id", "batch_id", "sku_code_normalized"),
        Index("ix_import_rows_action", "shop_id", "batch_id", "action"),
        ForeignKeyConstraint(
            ["shop_id", "batch_id"],
            ["catalog.import_batches.shop_id", "catalog.import_batches.id"],
            ondelete="CASCADE",
            name="fk_import_rows_batch",
        ),
        CheckConstraint(f"action IN {ROW_ACTIONS}", name="action"),
        CheckConstraint(f"result IN {ROW_RESULTS}", name="result"),
        CheckConstraint(f"spec_match IN {SPEC_MATCHES}", name="spec_match"),
        {"schema": "catalog"},
    )

    batch_id: Mapped[UUID]
    row_number: Mapped[int] = mapped_column(Integer)
    sku_code_normalized: Mapped[str | None] = mapped_column(Text)
    row_values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(Text)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    spec_match: Mapped[str] = mapped_column(Text, server_default="NOT_APPLICABLE")
    spec_id: Mapped[UUID | None]
    selected: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    result: Mapped[str | None] = mapped_column(Text)
    product_id: Mapped[UUID | None]
    sku_id: Mapped[UUID | None]
    image_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class ImportSourceRow(ShopScopedMixin, Base):
    """Faylning o'qilgan qatorlari (QA F1): fayl worker'da BIR marta o'qiladi, sinov bo'laklari shu
    jadvaldan oladi — har bo'lakda faylni qayta ochish yo'q. Import qatorlari bilan birga 30 kun saqlanadi."""

    __tablename__ = "import_source_rows"
    __table_args__ = (
        PrimaryKeyConstraint("shop_id", "batch_id", "row_number"),
        ForeignKeyConstraint(
            ["shop_id", "batch_id"],
            ["catalog.import_batches.shop_id", "catalog.import_batches.id"],
            ondelete="CASCADE",
            name="fk_import_source_rows_batch",
        ),
        {"schema": "catalog"},
    )

    batch_id: Mapped[UUID]
    row_number: Mapped[int] = mapped_column(Integer)
    cells: Mapped[list[str | None]] = mapped_column(JSONB)


class ImportStockRow(ShopScopedMixin, Base):
    """Qoldiq "kutish zali": catalog yozadi, commerce `ImportStockSource` orqali o'qib, o'zi qo'llaydi."""

    __tablename__ = "import_stock_rows"
    __table_args__ = (
        PrimaryKeyConstraint("shop_id", "batch_id", "sku_id", "branch_id"),
        ForeignKeyConstraint(
            ["shop_id", "batch_id"],
            ["catalog.import_batches.shop_id", "catalog.import_batches.id"],
            ondelete="CASCADE",
            name="fk_import_stock_rows_batch",
        ),
        CheckConstraint("quantity >= 0", name="quantity"),
        {"schema": "catalog"},
    )

    batch_id: Mapped[UUID]
    sku_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    quantity: Mapped[int] = mapped_column(Integer)
    row_number: Mapped[int] = mapped_column(Integer)
