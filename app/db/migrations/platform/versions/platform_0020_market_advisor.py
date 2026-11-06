"""platform: ai_usage.purpose ga MARKET_ADVISOR (Stage 3, M34 — global AI maslahatchi, platforma xarajati)

Revision ID: platform_0020
Revises: platform_0019
Create Date: 2026-11-03 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0020"
down_revision: str | None = "platform_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "SALES_TURN",
    "SUMMARY",
    "CLASSIFY",
    "EVAL_JUDGE",
    "SANDBOX",
    "EVAL",
    "COMMENT_CLASSIFY",
    "PRICE_LIST_READ",
    "VOICE_TRANSCRIBE",
    "CARD_DRAFT",
)
NEW = (*OLD, "MARKET_ADVISOR")


def _check(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_usage_purpose"), "ai_usage", f"purpose IN {values}", schema="platform"
    )


def upgrade() -> None:
    _check(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM platform.ai_usage WHERE purpose = 'MARKET_ADVISOR'")
    _check(OLD)
