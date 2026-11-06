"""sales_ai: agent_settings.special_order — omborda yo'q tovarni buyurtma asosida olib kelish (DEC-149)

Revision ID: sales_ai_0004
Revises: sales_ai_0003
Create Date: 2026-11-02 21:30:00.000000

`{"enabled": bool, "lead_time": "2–5 kun"}`; bo'sh — o'chiq (AI faqat bor variantlarni taklif qiladi).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "sales_ai_0004"
down_revision: str | None = "sales_ai_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_settings",
        sa.Column(
            "special_order",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="sales_ai",
    )


def downgrade() -> None:
    op.drop_column("agent_settings", "special_order", schema="sales_ai")
