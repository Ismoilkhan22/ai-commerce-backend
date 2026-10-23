"""audit: audit_entries (append-only, oyma-oy partition) (S0-07)

Revision ID: audit_0002
Revises: audit_0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from datetime import date

from alembic import op

from app.db.schemas import RUNTIME_ROLE
from app.shared.db.partitions import default_partition_sql, month_starts, monthly_partition_sql

revision: str = "audit_0002"
down_revision: str | None = "audit_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIRST_MONTH = date(2026, 10, 1)
INITIAL_MONTHS = 6


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit.audit_entries (
            id              uuid        NOT NULL,
            occurred_at     timestamptz NOT NULL DEFAULT now(),
            shop_id         uuid,
            actor_type      text        NOT NULL
                CONSTRAINT ck_audit_entries_actor_type
                CHECK (actor_type IN ('STAFF', 'AI_AGENT', 'CUSTOMER', 'SYSTEM', 'PLATFORM')),
            actor_id        uuid,
            action          text        NOT NULL,
            entity_type     text        NOT NULL,
            entity_id       uuid,
            entity_version  bigint,
            reason          text,
            diff            jsonb,
            trace_id        text,
            CONSTRAINT pk_audit_entries PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
        """
    )
    op.execute("CREATE INDEX ix_audit_entries_shop_time ON audit.audit_entries (shop_id, occurred_at)")
    op.execute(
        "CREATE INDEX ix_audit_entries_entity ON audit.audit_entries (shop_id, entity_type, entity_id)"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit.audit_entries FROM {RUNTIME_ROLE}")
    for month in month_starts(FIRST_MONTH, INITIAL_MONTHS):
        op.execute(monthly_partition_sql("audit", "audit_entries", month, append_only_role=RUNTIME_ROLE))
    op.execute(default_partition_sql("audit", "audit_entries", append_only_role=RUNTIME_ROLE))


def downgrade() -> None:
    op.execute("DROP TABLE audit.audit_entries")
