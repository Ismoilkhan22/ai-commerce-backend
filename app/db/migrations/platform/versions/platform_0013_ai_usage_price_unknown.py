"""llm: ai_usage.price_unknown, llm_pii_refs ID/LOCATION

Revision ID: platform_0013
Revises: platform_0012
Create Date: 2026-10-27 10:00:00.000000

6b QA: F-16 — narxi noma'lum model ishlatilganda xarajat ehtiyotkor narxda hisoblanadi va belgilanadi;
F-04 — shaxsiy hujjat (JSHSHIR, pasport, uzun raqam) va joylashuv tokenlari (`ID`, `LOCATION`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "platform_0013"
down_revision: str | None = "platform_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_usage",
        sa.Column("price_unknown", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="platform",
    )
    op.drop_constraint(op.f("ck_llm_pii_refs_kind"), "llm_pii_refs", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_pii_refs_kind"),
        "llm_pii_refs",
        "kind IN ('PHONE', 'ADDRESS', 'NAME', 'EMAIL', 'CARD', 'ID', 'LOCATION')",
        schema="platform",
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform.llm_pii_refs WHERE kind IN ('ID', 'LOCATION')")
    op.drop_constraint(op.f("ck_llm_pii_refs_kind"), "llm_pii_refs", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_pii_refs_kind"),
        "llm_pii_refs",
        "kind IN ('PHONE', 'ADDRESS', 'NAME', 'EMAIL', 'CARD')",
        schema="platform",
    )
    op.drop_column("ai_usage", "price_unknown", schema="platform")
