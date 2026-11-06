"""platform: hisob tuzatishlari (QA #4, #7) — bekor qilingan hisob o'rniga yangisi; raqam ketma-ketligi

Revision ID: platform_0022
Revises: platform_0021
Create Date: 2026-11-03 21:00:00.000000

- `uq_invoices_shop_id_period_start` o'rniga qisman noyob indeks (`status <> 'VOID'`).
- `platform.invoice_number_seq` — raqam `count(*)+1` emas (parallel ishda takrorlanmasin).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0022"
down_revision: str | None = "platform_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_invoices_shop_id_period_start", "invoices", schema="platform", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_invoices_shop_period_live ON platform.invoices (shop_id, period_start) "
        "WHERE status <> 'VOID'"
    )
    op.execute("CREATE SEQUENCE IF NOT EXISTS platform.invoice_number_seq")
    op.execute(
        "SELECT setval('platform.invoice_number_seq', "
        "GREATEST((SELECT count(*) FROM platform.invoices), 0) + 1, false)"
    )
    op.execute("GRANT USAGE, SELECT ON SEQUENCE platform.invoice_number_seq TO app_runtime")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS platform.invoice_number_seq")
    op.execute("DROP INDEX platform.uq_invoices_shop_period_live")
    op.create_unique_constraint(
        "uq_invoices_shop_id_period_start", "invoices", ["shop_id", "period_start"], schema="platform"
    )
