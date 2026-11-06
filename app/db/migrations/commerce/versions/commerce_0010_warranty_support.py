"""commerce: kafolat murojaatlari uchun (7b-modul, DEC-145) — db/support.md §5

- `stock_ledger.reason` ga `WARRANTY_REPLACEMENT` (kafolat bo'yicha yangi dona berildi, qoldiq -qty,
  `ref_type = SUPPORT_CASE` allaqachon bor);
- `stock_adjustments.support_case_id` (FK'siz, ixtiyoriy) — karantindagi donani RESTOCK / WRITE_OFF
  qilganda qaysi murojaatdan kelgani; indeks `(shop_id, support_case_id)`.

Revision ID: commerce_0010
Revises: commerce_0009
Create Date: 2026-10-27 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "commerce_0010"
down_revision: str | None = "commerce_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "reason IN ('RECEIPT', 'ADJUSTMENT', 'OFFLINE_SALE', 'RESERVE', 'ALLOCATE', 'RELEASE', 'SALE', "
    "'QUARANTINE_IN', 'RETURN_QUARANTINE', 'RESTOCK', 'WRITE_OFF')"
)
NEW = (
    "reason IN ('RECEIPT', 'ADJUSTMENT', 'OFFLINE_SALE', 'RESERVE', 'ALLOCATE', 'RELEASE', 'SALE', "
    "'QUARANTINE_IN', 'RETURN_QUARANTINE', 'RESTOCK', 'WRITE_OFF', 'WARRANTY_REPLACEMENT')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_stock_ledger_reason"), "stock_ledger", schema="commerce", type_="check")
    op.create_check_constraint(op.f("ck_stock_ledger_reason"), "stock_ledger", NEW, schema="commerce")
    op.add_column(
        "stock_adjustments", sa.Column("support_case_id", sa.Uuid(), nullable=True), schema="commerce"
    )
    op.create_index(
        "ix_stock_adjustments_shop_id_support_case_id",
        "stock_adjustments",
        ["shop_id", "support_case_id"],
        schema="commerce",
    )


def downgrade() -> None:
    op.drop_index("ix_stock_adjustments_shop_id_support_case_id", "stock_adjustments", schema="commerce")
    op.drop_column("stock_adjustments", "support_case_id", schema="commerce")
    op.drop_constraint(op.f("ck_stock_ledger_reason"), "stock_ledger", schema="commerce", type_="check")
    op.create_check_constraint(op.f("ck_stock_ledger_reason"), "stock_ledger", OLD, schema="commerce")
