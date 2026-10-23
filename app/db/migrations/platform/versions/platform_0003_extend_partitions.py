"""platform: transition_log partition'larini 2028-12 gacha uzaytirish (kod tekshiruvi, TD-01)

Revision ID: platform_0003
Revises: platform_0002
Create Date: 2026-10-23

Rejali partition yaratish ishi (TD-01) qurilgunga qadar kamida 12 oy zaxira bo'lishi uchun.
"""

from collections.abc import Sequence
from datetime import date

from alembic import op

from app.db.schemas import RUNTIME_ROLE
from app.shared.db.partitions import month_starts, monthly_partition_sql

revision: str = "platform_0003"
down_revision: str | None = "platform_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIRST_MONTH = date(2027, 4, 1)  # 0002 2027-03 gacha yaratgan
MONTHS = 21  # 2027-04 … 2028-12


def upgrade() -> None:
    for month in month_starts(FIRST_MONTH, MONTHS):
        for statement in monthly_partition_sql(
            "platform", "transition_log", month, append_only_role=RUNTIME_ROLE
        ):
            op.execute(statement)


def downgrade() -> None:
    for month in month_starts(FIRST_MONTH, MONTHS):
        op.execute(f"DROP TABLE IF EXISTS platform.transition_log_y{month.year}m{month.month:02d}")
