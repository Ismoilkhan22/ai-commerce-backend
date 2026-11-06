"""platform: stored_files.purpose ga SUPPORT_EVIDENCE (7b-modul, kafolat murojaati rasmi, DEC-145)

Revision ID: platform_0015
Revises: platform_0014
Create Date: 2026-10-27 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0015"
down_revision: str | None = "platform_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES_OLD = (
    "PRODUCT_IMAGE",
    "STOCK_EVIDENCE",
    "IMPORT_FILE",
    "EXPORT_FILE",
    "SITE_LOGO",
    "CHAT_ATTACHMENT",
)
PURPOSES_NEW = (*PURPOSES_OLD, "SUPPORT_EVIDENCE")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_stored_files_purpose"), "stored_files", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_stored_files_purpose"), "stored_files", f"purpose IN {PURPOSES_NEW}", schema="platform"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_stored_files_purpose"), "stored_files", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_stored_files_purpose"), "stored_files", f"purpose IN {PURPOSES_OLD}", schema="platform"
    )
