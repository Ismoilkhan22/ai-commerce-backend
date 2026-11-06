"""commerce: import tuzatishi — absolyut maqsad qoldiq (5c QA F3)

Farq tasdiq paytida joriy qoldiqdan hisoblanadi; bir xil SKU+filial uchun yangi import eski kutilayotgan
import tuzatishini almashtiradi.

Revision ID: commerce_0006
Revises: commerce_0005
Create Date: 2026-10-26 20:12:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "commerce_0006"
down_revision: str | None = "commerce_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stock_adjustments", sa.Column("target_on_hand", sa.Integer(), nullable=True), schema="commerce"
    )
    op.create_check_constraint(
        op.f("ck_stock_adjustments_target_on_hand"),
        "stock_adjustments",
        "target_on_hand IS NULL OR (target_on_hand >= 0 AND kind = 'ADJUSTMENT')",
        schema="commerce",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_stock_adjustments_target_on_hand"), "stock_adjustments", schema="commerce", type_="check"
    )
    op.drop_column("stock_adjustments", "target_on_hand", schema="commerce")
