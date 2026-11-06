"""Taklif versiyasini kim tahrirladi va kim tekshiruvga yubordi (QA 6a F1, DEC-109).

O'zi tuzgan, qatorlarini tahrirlagan yoki tekshiruvga yuborgan xodim shu versiyani tasdiqlay olmaydi.
`created_by` — versiyani yaratgan (qaytargan / qayta ishlagan) xodim, shuning uchun alohida ustunlar kerak.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "commerce_0008"
down_revision: str | None = "commerce_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quote_revisions", sa.Column("edited_by", postgresql.UUID(), nullable=True), schema="commerce"
    )
    op.add_column(
        "quote_revisions", sa.Column("submitted_by", postgresql.UUID(), nullable=True), schema="commerce"
    )
    # Mavjud versiyalar: yaratgan xodim — tahrirlagan va yuborgan deb hisoblanadi
    op.execute(
        "UPDATE commerce.quote_revisions SET edited_by = created_by, "
        "submitted_by = CASE WHEN submitted_at IS NOT NULL THEN created_by END"
    )


def downgrade() -> None:
    op.drop_column("quote_revisions", "submitted_by", schema="commerce")
    op.drop_column("quote_revisions", "edited_by", schema="commerce")
