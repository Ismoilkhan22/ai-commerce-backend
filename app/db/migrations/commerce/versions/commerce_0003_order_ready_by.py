"""commerce: kim "olib ketishga tayyor" ni bosgani (QA 2-tur U3)

Revision ID: commerce_0003
Revises: commerce_0002
Create Date: 2026-10-26

`orders.ready_by` — boshqa `*_by` ustunlari kabi a'zolik ID'si (FK'siz, platform schemasida).
Eski buyurtmalarda bo'sh qoladi: kim bosgani yozilmagan edi.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "commerce_0003"
down_revision: str | None = "commerce_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("ready_by", sa.Uuid(), nullable=True), schema="commerce")


def downgrade() -> None:
    op.drop_column("orders", "ready_by", schema="commerce")
