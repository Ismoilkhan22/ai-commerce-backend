"""platform: ai_usage.purpose ga COMMENT_CLASSIFY (Instagram izohlari kayfiyati, DEC-148)

Revision ID: platform_0016
Revises: platform_0015
Create Date: 2026-10-27 18:00:00.000000

Izoh kayfiyati tarifda alohida ko'rinadi va shop AI limitiga kiradi (DEC-119).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0016"
down_revision: str | None = "platform_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_PURPOSES = "purpose IN ('SALES_TURN', 'SUMMARY', 'CLASSIFY', 'EVAL_JUDGE', 'SANDBOX', 'EVAL')"
NEW_PURPOSES = (
    "purpose IN ('SALES_TURN', 'SUMMARY', 'CLASSIFY', 'EVAL_JUDGE', 'SANDBOX', 'EVAL', 'COMMENT_CLASSIFY')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", schema="platform", type_="check")
    op.create_check_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", NEW_PURPOSES, schema="platform")


def downgrade() -> None:
    op.execute("DELETE FROM platform.ai_usage WHERE purpose = 'COMMENT_CLASSIFY'")
    op.drop_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", schema="platform", type_="check")
    op.create_check_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", OLD_PURPOSES, schema="platform")
