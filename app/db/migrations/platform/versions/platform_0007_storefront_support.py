"""platform: sayt uchun — shop_policies.delivery_enabled, fayl turi SITE_LOGO (4-modul, storefront.md §8)

Revision ID: platform_0007
Revises: platform_0006
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "platform_0007"
down_revision: str | None = "platform_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "purpose IN ('PRODUCT_IMAGE', 'STOCK_EVIDENCE', 'IMPORT_FILE', 'EXPORT_FILE')"
_NEW = "purpose IN ('PRODUCT_IMAGE', 'STOCK_EVIDENCE', 'IMPORT_FILE', 'EXPORT_FILE', 'SITE_LOGO')"


def upgrade() -> None:
    op.add_column(
        "shop_policies",
        sa.Column("delivery_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema="platform",
    )
    op.drop_constraint(op.f("ck_stored_files_purpose"), "stored_files", schema="platform", type_="check")
    op.create_check_constraint(op.f("ck_stored_files_purpose"), "stored_files", _NEW, schema="platform")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_stored_files_purpose"), "stored_files", schema="platform", type_="check")
    op.create_check_constraint(op.f("ck_stored_files_purpose"), "stored_files", _OLD, schema="platform")
    op.drop_column("shop_policies", "delivery_enabled", schema="platform")
