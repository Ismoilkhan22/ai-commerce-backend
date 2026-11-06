"""storefront: outbox_events, consumer_receipts — transactional outbox (5-modul, 5a; db/jobs.md §1–2)

Revision ID: storefront_0003
Revises: storefront_0002
Create Date: 2026-10-26

Har outbox schemasida bir xil ikki jadval (`app.shared.events.models`). RLS yo'q: worker shoplararo poll
qiladi, envelope'da PII yo'q (05 §3.1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "storefront_0003"
down_revision: str | None = "storefront_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "storefront"


def _outbox_tables() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=True),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'DEAD')", name=op.f("ck_outbox_events_status")
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["next_attempt_at", "event_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id", "aggregate_version"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_events_published",
        "outbox_events",
        ["published_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "consumer_receipts",
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("consumer", "event_id", name="pk_consumer_receipts"),
        schema=SCHEMA,
    )
    op.create_index("ix_consumer_receipts_applied_at", "consumer_receipts", ["applied_at"], schema=SCHEMA)


def upgrade() -> None:
    _outbox_tables()


def downgrade() -> None:
    op.drop_table("consumer_receipts", schema=SCHEMA)
    op.drop_table("outbox_events", schema=SCHEMA)
