"""catalog: import faylini worker'da bir marta o'qish — PARSING holati va import_source_rows (5c QA F1)

Revision ID: catalog_0006
Revises: catalog_0005
Create Date: 2026-10-26 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "catalog_0006"
down_revision: str | None = "catalog_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'UPLOADED', 'MAPPED', 'VALIDATING', 'VALIDATED', 'COMMITTING', 'STOCK_PENDING', 'COMPLETED', "
    "'FAILED', 'EXPIRED', 'CANCELLED'"
)
_NEW = "'PARSING', " + _OLD


def upgrade() -> None:
    op.drop_constraint(op.f("ck_import_batches_status"), "import_batches", schema="catalog", type_="check")
    op.create_check_constraint(
        op.f("ck_import_batches_status"), "import_batches", f"status IN ({_NEW})", schema="catalog"
    )
    op.create_table(
        "import_source_rows",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("cells", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id", "batch_id"],
            ["catalog.import_batches.shop_id", "catalog.import_batches.id"],
            name="fk_import_source_rows_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("shop_id", "batch_id", "row_number", name=op.f("pk_import_source_rows")),
        schema="catalog",
    )
    shop = "NULLIF(current_setting('app.shop_id', true), '')::uuid"
    op.execute("ALTER TABLE catalog.import_source_rows ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog.import_source_rows FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY shop_isolation ON catalog.import_source_rows "
        f"USING (shop_id = {shop}) WITH CHECK (shop_id = {shop})"
    )


def downgrade() -> None:
    op.drop_table("import_source_rows", schema="catalog")
    op.execute("UPDATE catalog.import_batches SET status = 'FAILED' WHERE status = 'PARSING'")
    op.drop_constraint(op.f("ck_import_batches_status"), "import_batches", schema="catalog", type_="check")
    op.create_check_constraint(
        op.f("ck_import_batches_status"), "import_batches", f"status IN ({_OLD})", schema="catalog"
    )
