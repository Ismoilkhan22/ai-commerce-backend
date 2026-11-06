"""messaging: yuborish boshlangan vaqt va bo'laklar progressi (QA 5b M5, L8)

Revision ID: messaging_0003
Revises: messaging_0002
Create Date: 2026-10-26

- `messages.sending_started_at` — "osilib qolgan" yuborishni (06 §6) yaratilgan vaqtdan emas, SENDING ga
  o'tgan vaqtdan hisoblash uchun: uzoq qayta urinishdagi xabar yuborilayotgan paytda UNKNOWN bo'lib qolmaydi.
- `messages.parts_sent` — uzun matn bo'laklarga bo'linganda nechtasi ketgani: qayta urinish birinchi
  bo'lakdan emas, to'xtagan joydan davom etadi (xaridor bir bo'lakni ikki marta olmaydi).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "messaging_0003"
down_revision: str | None = "messaging_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("parts_sent", sa.Integer(), server_default="0", nullable=False),
        schema="messaging",
    )
    op.add_column(
        "messages",
        sa.Column("sending_started_at", sa.DateTime(timezone=True), nullable=True),
        schema="messaging",
    )
    op.create_check_constraint(
        op.f("ck_messages_parts_sent_nonnegative"), "messages", "parts_sent >= 0", schema="messaging"
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_messages_parts_sent_nonnegative"), "messages", schema="messaging", type_="check"
    )
    op.drop_column("messages", "sending_started_at", schema="messaging")
    op.drop_column("messages", "parts_sent", schema="messaging")
