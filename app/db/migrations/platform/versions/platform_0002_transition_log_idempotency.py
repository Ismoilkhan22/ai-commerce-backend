"""platform: transition_log (append-only, partition) va idempotency_keys (S0-07)

Revision ID: platform_0002
Revises: platform_0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from datetime import date

from alembic import op

from app.db.schemas import RUNTIME_ROLE
from app.shared.db.partitions import default_partition_sql, month_starts, monthly_partition_sql

revision: str = "platform_0002"
down_revision: str | None = "platform_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIRST_MONTH = date(2026, 10, 1)
INITIAL_MONTHS = 6


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.transition_log (
            id           uuid        NOT NULL,
            occurred_at  timestamptz NOT NULL DEFAULT now(),
            shop_id      uuid,
            entity_type  text        NOT NULL,
            entity_id    uuid        NOT NULL,
            command      text        NOT NULL,
            from_status  text        NOT NULL,
            to_status    text        NOT NULL,
            actor_type   text        NOT NULL
                CONSTRAINT ck_transition_log_actor_type
                CHECK (actor_type IN ('STAFF', 'AI_AGENT', 'CUSTOMER', 'SYSTEM', 'PLATFORM')),
            actor_id     uuid,
            reason       text,
            forced       boolean     NOT NULL DEFAULT false,
            trace_id     text,
            CONSTRAINT pk_transition_log PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_transition_log_entity "
        "ON platform.transition_log (shop_id, entity_type, entity_id, occurred_at)"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON platform.transition_log FROM {RUNTIME_ROLE}")
    statements = [
        stmt
        for month in month_starts(FIRST_MONTH, INITIAL_MONTHS)
        for stmt in monthly_partition_sql("platform", "transition_log", month, append_only_role=RUNTIME_ROLE)
    ]
    statements += default_partition_sql("platform", "transition_log", append_only_role=RUNTIME_ROLE)
    for statement in statements:
        op.execute(statement)

    op.execute(
        """
        CREATE TABLE platform.idempotency_keys (
            shop_id          uuid        NOT NULL,
            operation        text        NOT NULL,
            key              text        NOT NULL,
            request_hash     text        NOT NULL,
            response_status  integer,
            response_body    jsonb,
            created_at       timestamptz NOT NULL DEFAULT now(),
            expires_at       timestamptz NOT NULL,
            CONSTRAINT pk_idempotency_keys PRIMARY KEY (shop_id, operation, key)
        )
        """
    )
    op.execute("CREATE INDEX ix_idempotency_keys_expires_at ON platform.idempotency_keys (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE platform.idempotency_keys")
    op.execute("DROP TABLE platform.transition_log")  # partition'lar ham o'chadi
