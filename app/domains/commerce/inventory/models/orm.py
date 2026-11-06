"""commerce.stock_balances, stock_ledger, stock_receipts, stock_adjustments — db/commerce.dbml (S1-05).

Filial va SKU boshqa schemada (`platform`, `catalog`) — faqat uuid, FK'siz (07 §6.3). Daftar faqat
qo'shiladi: ilova roliga UPDATE/DELETE berilmaydi (migratsiyada REVOKE).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, VersionMixin

LEDGER_REASONS = (
    "RECEIPT",
    "ADJUSTMENT",
    "OFFLINE_SALE",
    "RESERVE",
    "ALLOCATE",
    "RELEASE",
    "SALE",
    "QUARANTINE_IN",
    "RETURN_QUARANTINE",
    "RESTOCK",
    "WRITE_OFF",
)
LEDGER_REF_TYPES = ("RECEIPT", "ADJUSTMENT", "QUICK_SALE", "RESERVATION", "SUPPORT_CASE")
ADJUSTMENT_KINDS = ("ADJUSTMENT", "QUARANTINE_IN", "RESTOCK", "WRITE_OFF")
ADJUSTMENT_STATUSES = ("PENDING", "APPROVED", "REJECTED")

_BALANCE_FK = [
    "commerce.stock_balances.shop_id",
    "commerce.stock_balances.branch_id",
    "commerce.stock_balances.sku_id",
]


class StockBalance(VersionMixin, Base):
    """Filial × SKU hozirgi sonlari. Sotuvga mavjud (on_hand − reserved − allocated) saqlanmaydi."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        Index("ix_stock_balances_shop_id_sku_id", "shop_id", "sku_id"),
        CheckConstraint(
            "on_hand >= 0 AND reserved >= 0 AND allocated >= 0 AND quarantine_qty >= 0", name="non_negative"
        ),
        # Oxirgi himoya: sotuvga mavjud hech qachon manfiy emas (BL-019). Asosiysi — qulf va tekshiruv
        CheckConstraint("reserved + allocated <= on_hand", name="available_non_negative"),
        {"schema": "commerce"},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    sku_id: Mapped[UUID] = mapped_column(primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, server_default="0")
    allocated: Mapped[int] = mapped_column(Integer, server_default="0")
    quarantine_qty: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved - self.allocated


class StockLedger(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "stock_ledger"
    __table_args__ = (
        # Bir hujjat bir SKU'ni bir sabab bilan faqat bir marta o'zgartiradi (TC-030, BL-021)
        UniqueConstraint("shop_id", "reason", "ref_type", "ref_id", "sku_id", name="uq_stock_ledger_once"),
        Index(
            "ix_stock_ledger_shop_id_branch_id_sku_id_created_at",
            "shop_id",
            "branch_id",
            "sku_id",
            "created_at",
        ),
        Index("ix_stock_ledger_shop_id_created_at", "shop_id", "created_at"),
        ForeignKeyConstraint(
            ["shop_id", "branch_id", "sku_id"],
            _BALANCE_FK,
            ondelete="RESTRICT",
            name="fk_stock_ledger_balance",
        ),
        CheckConstraint(f"reason IN {LEDGER_REASONS}", name="reason"),
        CheckConstraint(f"ref_type IN {LEDGER_REF_TYPES}", name="ref_type"),
        {"schema": "commerce"},
    )

    branch_id: Mapped[UUID]
    sku_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    delta_on_hand: Mapped[int] = mapped_column(Integer, server_default="0")
    delta_reserved: Mapped[int] = mapped_column(Integer, server_default="0")
    delta_allocated: Mapped[int] = mapped_column(Integer, server_default="0")
    delta_quarantine: Mapped[int] = mapped_column(Integer, server_default="0")
    on_hand_after: Mapped[int] = mapped_column(Integer)
    reserved_after: Mapped[int] = mapped_column(Integer)
    allocated_after: Mapped[int] = mapped_column(Integer)
    quarantine_after: Mapped[int] = mapped_column(Integer)
    ref_type: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[UUID]
    actor_membership_id: Mapped[UUID | None]  # platform.memberships.id; NULL — tizim amali (Stage 2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockReceipt(IdMixin, ShopScopedMixin, Base):
    """Kirim hujjati (sarlavha). Qatorlari — daftarda (`RECEIPT`, shu id). O'zgarmaydi."""

    __tablename__ = "stock_receipts"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_stock_receipts_shop_id_branch_id_created_at", "shop_id", "branch_id", "created_at"),
        Index("ix_stock_receipts_shop_id_created_at", "shop_id", "created_at"),
        # Importdan: bitta filialga bo'lak boshiga bitta kirim (100 qatorgacha) — takror himoyasi natija
        # jadvalida (import_stock_results), shuning uchun unikal emas
        Index(
            "ix_stock_receipts_import",
            "shop_id",
            "import_batch_id",
            "branch_id",
            postgresql_where=text("import_batch_id IS NOT NULL"),
        ),
        {"schema": "commerce"},
    )

    branch_id: Mapped[UUID]
    note: Mapped[str | None] = mapped_column(Text)
    received_by: Mapped[UUID]  # platform.memberships.id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    import_batch_id: Mapped[UUID | None]  # catalog.import_batches.id — importdan (bitta filialga bitta kirim)


class StockAdjustment(IdMixin, ShopScopedMixin, VersionMixin, Base):
    """Qo'lda tuzatish: omborchi so'raydi → ega/menejer tasdiqlaydi; ega/menejer o'zi tuzatsa — darhol
    APPROVED (DEC-134)."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_stock_adjustments_shop_id_status_requested_at", "shop_id", "status", "requested_at"),
        Index(
            "ix_stock_adjustments_shop_id_branch_id_sku_id_requested_at",
            "shop_id",
            "branch_id",
            "sku_id",
            "requested_at",
        ),
        ForeignKeyConstraint(
            ["shop_id", "branch_id", "sku_id"],
            _BALANCE_FK,
            ondelete="RESTRICT",
            name="fk_stock_adjustments_balance",
        ),
        CheckConstraint(f"kind IN {ADJUSTMENT_KINDS}", name="kind"),
        CheckConstraint(f"status IN {ADJUSTMENT_STATUSES}", name="status"),
        CheckConstraint(
            "(kind = 'ADJUSTMENT' AND delta <> 0) OR (kind <> 'ADJUSTMENT' AND delta > 0)", name="delta"
        ),
        CheckConstraint("char_length(reason) >= 3", name="reason_length"),  # BL-022: sababsiz tuzatish yo'q
        CheckConstraint(
            "target_on_hand IS NULL OR (target_on_hand >= 0 AND kind = 'ADJUSTMENT')", name="target_on_hand"
        ),
        Index(
            "uq_stock_adjustments_import",
            "shop_id",
            "import_batch_id",
            "branch_id",
            "sku_id",
            unique=True,
            postgresql_where=text("import_batch_id IS NOT NULL"),
        ),
        {"schema": "commerce"},
    )

    branch_id: Mapped[UUID]
    sku_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text, server_default="ADJUSTMENT")
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    evidence_file_id: Mapped[UUID | None]  # platform.stored_files.id (STOCK_EVIDENCE, yopiq)
    status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    requested_by: Mapped[UUID]  # platform.memberships.id
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[UUID | None]
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    on_hand_before: Mapped[int | None] = mapped_column(Integer)
    on_hand_after: Mapped[int | None] = mapped_column(Integer)
    import_batch_id: Mapped[UUID | None]  # catalog.import_batches.id — import farqi (DEC-140, 1-qaror)
    # Import tuzatishi — fayldagi ABSOLYUT qoldiq (QA F3): farq tasdiq paytida joriy qoldiqdan hisoblanadi
    target_on_hand: Mapped[int | None] = mapped_column(Integer)


IMPORT_STOCK_RESULTS = ("APPLIED", "NO_CHANGE", "PENDING_APPROVAL", "ERROR")


class ImportStockResult(ShopScopedMixin, Base):
    """Katalog importining har qoldiq qatori natijasi (db/catalog_import.md §5). Asosiy kalit — takror
    himoyasi: event qayta kelsa qator qayta qo'llanmaydi (TC-IMP-09)."""

    __tablename__ = "import_stock_results"
    __table_args__ = (
        PrimaryKeyConstraint("shop_id", "batch_id", "sku_id", "branch_id"),
        CheckConstraint(f"result IN {IMPORT_STOCK_RESULTS}", name="result"),
        {"schema": "commerce"},
    )

    batch_id: Mapped[UUID]  # catalog.import_batches.id — FK'siz (boshqa schema)
    sku_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    result: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    receipt_id: Mapped[UUID | None]
    adjustment_id: Mapped[UUID | None]
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
