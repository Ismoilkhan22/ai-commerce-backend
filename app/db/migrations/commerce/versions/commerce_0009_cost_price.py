"""commerce: tannarx — o'rtacha tortilgan sotib olish narxi (7a-modul, DEC-146) — db/commerce_cost_price.md

Yangi: `stock_receipt_costs`, `sku_costs`, `sku_cost_changes` (RLS FORCE). Mavjud: `order_lines`,
`quick_sale_lines`, `stock_adjustments` ga NULL `unit_cost_uzs_minor` (sotuv paytidagi nusxa).
Kirim tannarxi va tarix faqat qo'shiladi: ilova roliga UPDATE/DELETE berilmaydi.

Revision ID: commerce_0009
Revises: commerce_0008
Create Date: 2026-10-27 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.schemas import RUNTIME_ROLE

RLS_TABLES = ("stock_receipt_costs", "sku_costs", "sku_cost_changes")
APPEND_ONLY = ("stock_receipt_costs", "sku_cost_changes")
REASONS = "('RECEIPT', 'LATE_ENTRY', 'MANUAL_SET', 'IMPORT')"

revision: str = "commerce_0009"
down_revision: str | None = "commerce_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_receipt_costs",
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("sku_id", sa.Uuid(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_cost_minor", sa.BigInteger(), nullable=False),
        sa.Column("cost_currency", sa.Text(), nullable=False),
        sa.Column("exchange_rate_id", sa.Uuid(), nullable=True),
        sa.Column("exchange_rate_snapshot", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("unit_cost_uzs_minor", sa.BigInteger(), nullable=False),
        sa.Column("late_entry", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("entered_by", sa.Uuid(), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("qty > 0", name=op.f("ck_stock_receipt_costs_qty_positive")),
        sa.CheckConstraint(
            "unit_cost_minor > 0 AND unit_cost_uzs_minor > 0",
            name=op.f("ck_stock_receipt_costs_cost_positive"),
        ),
        sa.CheckConstraint("cost_currency IN ('UZS', 'USD')", name=op.f("ck_stock_receipt_costs_currency")),
        sa.CheckConstraint(
            "cost_currency = 'UZS' OR exchange_rate_snapshot IS NOT NULL",
            name=op.f("ck_stock_receipt_costs_usd_needs_rate"),
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "receipt_id"],
            ["commerce.stock_receipts.shop_id", "commerce.stock_receipts.id"],
            name=op.f("fk_stock_receipt_costs_shop_id_receipt_id_stock_receipts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_receipt_costs")),
        sa.UniqueConstraint("shop_id", "id", name=op.f("uq_stock_receipt_costs_shop_id_id")),
        sa.UniqueConstraint(
            "shop_id", "receipt_id", "sku_id", name=op.f("uq_stock_receipt_costs_shop_id_receipt_id_sku_id")
        ),
        schema="commerce",
    )
    op.create_index(
        "ix_stock_receipt_costs_shop_id_sku_id_entered_at",
        "stock_receipt_costs",
        ["shop_id", "sku_id", "entered_at"],
        schema="commerce",
    )
    op.create_table(
        "sku_costs",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sku_id", sa.Uuid(), nullable=False),
        sa.Column("avg_unit_cost_uzs_minor", sa.BigInteger(), nullable=False),
        sa.Column("basis_qty", sa.Integer(), nullable=False),
        sa.Column("cost_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("last_reason", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("avg_unit_cost_uzs_minor > 0", name=op.f("ck_sku_costs_cost_positive")),
        sa.CheckConstraint("basis_qty >= 0", name=op.f("ck_sku_costs_basis_non_negative")),
        sa.CheckConstraint(f"last_reason IN {REASONS}", name=op.f("ck_sku_costs_last_reason")),
        sa.PrimaryKeyConstraint("shop_id", "sku_id", name=op.f("pk_sku_costs")),
        schema="commerce",
    )
    op.create_table(
        "sku_cost_changes",
        sa.Column("sku_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("avg_before_uzs_minor", sa.BigInteger(), nullable=True),
        sa.Column("avg_after_uzs_minor", sa.BigInteger(), nullable=False),
        sa.Column("basis_qty", sa.Integer(), nullable=False),
        sa.Column("incoming_qty", sa.Integer(), nullable=True),
        sa.Column("incoming_unit_cost_uzs_minor", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(f"reason IN {REASONS}", name=op.f("ck_sku_cost_changes_reason")),
        sa.CheckConstraint(
            "reason <> 'MANUAL_SET' OR (note IS NOT NULL AND char_length(note) >= 3)",
            name=op.f("ck_sku_cost_changes_manual_needs_note"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sku_cost_changes")),
        sa.UniqueConstraint("shop_id", "id", name=op.f("uq_sku_cost_changes_shop_id_id")),
        schema="commerce",
    )
    op.create_index(
        "ix_sku_cost_changes_shop_id_sku_id_created_at",
        "sku_cost_changes",
        ["shop_id", "sku_id", "created_at"],
        schema="commerce",
    )
    for table in ("order_lines", "quick_sale_lines", "stock_adjustments"):
        op.add_column(
            table, sa.Column("unit_cost_uzs_minor", sa.BigInteger(), nullable=True), schema="commerce"
        )

    # --- Qo'lda: RLS (10 §4) ------------------------------------------------------------------
    shop = "NULLIF(current_setting('app.shop_id', true), '')::uuid"
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE commerce.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE commerce.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY shop_isolation ON commerce.{table} "
            f"USING (shop_id = {shop}) WITH CHECK (shop_id = {shop})"
        )
    for table in APPEND_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON commerce.{table} FROM {RUNTIME_ROLE}")
    op.execute(f"REVOKE DELETE, TRUNCATE ON commerce.sku_costs FROM {RUNTIME_ROLE}")


def downgrade() -> None:
    for table in ("stock_adjustments", "quick_sale_lines", "order_lines"):
        op.drop_column(table, "unit_cost_uzs_minor", schema="commerce")
    op.drop_table("sku_cost_changes", schema="commerce")
    op.drop_table("sku_costs", schema="commerce")
    op.drop_table("stock_receipt_costs", schema="commerce")
