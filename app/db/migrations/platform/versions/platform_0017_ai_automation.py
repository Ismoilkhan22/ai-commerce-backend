"""platform: DEC-149 AI avtomatlashtirish — fayl maqsadi PRICE_LIST va AI xarajat maqsadlari

Revision ID: platform_0017
Revises: platform_0016
Create Date: 2026-11-02 12:00:00.000000

- `stored_files.purpose` ga PRICE_LIST (yetkazib beruvchi narx ro'yxati: XLSX, CSV, PDF yoki rasm; yopiq).
- `ai_usage.purpose` ga PRICE_LIST_READ, VOICE_TRANSCRIBE, CARD_DRAFT — tarifda alohida ko'rinadi va shop AI
  limitiga kiradi (DEC-119).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0017"
down_revision: str | None = "platform_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILES_OLD = (
    "PRODUCT_IMAGE",
    "STOCK_EVIDENCE",
    "IMPORT_FILE",
    "EXPORT_FILE",
    "SITE_LOGO",
    "CHAT_ATTACHMENT",
    "SUPPORT_EVIDENCE",
)
FILES_NEW = (*FILES_OLD, "PRICE_LIST")
USAGE_OLD = ("SALES_TURN", "SUMMARY", "CLASSIFY", "EVAL_JUDGE", "SANDBOX", "EVAL", "COMMENT_CLASSIFY")
USAGE_NEW = (*USAGE_OLD, "PRICE_LIST_READ", "VOICE_TRANSCRIBE", "CARD_DRAFT")


def _check(table: str, values: tuple[str, ...]) -> None:
    name = op.f(f"ck_{table}_purpose")
    op.drop_constraint(name, table, schema="platform", type_="check")
    op.create_check_constraint(name, table, f"purpose IN {values}", schema="platform")


def upgrade() -> None:
    _check("stored_files", FILES_NEW)
    _check("ai_usage", USAGE_NEW)


def downgrade() -> None:
    op.execute(
        "DELETE FROM platform.ai_usage WHERE purpose IN ('PRICE_LIST_READ', 'VOICE_TRANSCRIBE', 'CARD_DRAFT')"
    )
    _check("ai_usage", USAGE_OLD)
    _check("stored_files", FILES_OLD)
