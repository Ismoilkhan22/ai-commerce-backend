"""platform: outbox, dead-letter, ish jurnali, xodim xabarnomalari va vazifalari, platforma boti (5-modul, 5a)

Revision ID: platform_0009
Revises: platform_0008
Create Date: 2026-10-26

Jadvallar ORM modelidan (db/jobs.dbml, db/notifications.dbml — DEC-138, DEC-139, founder ko'rib chiqishi
kutilmoqda). Qo'lda:
- RLS (10 §4): notifications, staff_tasks, staff_notification_settings — shop konteksti bo'yicha, FORCE.
  outbox/receipts/dead_letters/job_runs — RLS'siz (shoplararo, PII'siz); staff_telegram_links va
  telegram_link_codes — RLS'siz identity jadvallar (principals kabi), faqat service kodi orqali.
- `platform.ensure_monthly_partitions(months)` — TD-01: ilova rolida DDL yo'q, shuning uchun app_migrator
  egaligidagi SECURITY DEFINER funksiya (DEC-138, 3-qaror). Faqat partition yaratadi.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "platform_0009"
down_revision: str | None = "platform_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform"

PARTITION_FUNCTION = """
CREATE OR REPLACE FUNCTION platform.ensure_monthly_partitions(p_months integer)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    t record;
    month_start date;
    child text;
    created integer := 0;
    first_month date := date_trunc('month', now())::date;
BEGIN
    IF p_months < 1 OR p_months > 36 THEN
        RAISE EXCEPTION 'p_months must be between 1 and 36';
    END IF;
    FOR t IN SELECT * FROM (VALUES ('platform', 'transition_log'), ('audit', 'audit_entries')) AS v(s, n) LOOP
        FOR i IN 0..p_months LOOP
            month_start := (first_month + make_interval(months => i))::date;
            child := format('%s_y%sm%s', t.n, to_char(month_start, 'YYYY'), to_char(month_start, 'MM'));
            IF to_regclass(format('%I.%I', t.s, child)) IS NULL THEN
                EXECUTE format(
                    'CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
                    t.s, child, t.s, t.n, month_start, (month_start + interval '1 month')::date
                );
                -- Jurnal faqat to'ldiriladi: ilova roli o'zgartira olmaydi (07 §5.3)
                EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %I.%I FROM app_runtime', t.s, child);
                created := created + 1;
            END IF;
        END LOOP;
    END LOOP;
    RETURN created;
END
$fn$
"""


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
    op.create_table(
        "dead_letters",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_schema", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('OPEN', 'REPLAYED', 'IGNORED')", name=op.f("ck_dead_letters_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dead_letters")),
        sa.UniqueConstraint("event_id", "consumer", name=op.f("uq_dead_letters_event_id_consumer")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_dead_letters_status_created_at", "dead_letters", ["status", "created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_dead_letters_shop_id_created_at", "dead_letters", ["shop_id", "created_at"], schema=SCHEMA
    )
    op.create_table(
        "job_runs",
        sa.Column("job_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("affected", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'OK', 'FAILED', 'SKIPPED')", name=op.f("ck_job_runs_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        schema=SCHEMA,
    )
    op.create_index("ix_job_runs_job_name_started_at", "job_runs", ["job_name", "started_at"], schema=SCHEMA)
    op.create_index("ix_job_runs_started_at", "job_runs", ["started_at"], schema=SCHEMA)

    op.create_table(
        "notifications",
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("recipient_type", sa.Text(), nullable=False),
        sa.Column("recipient_membership_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.Text(), server_default="NORMAL", nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_reason", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "recipient_type IN ('CUSTOMER', 'STAFF')", name=op.f("ck_notifications_recipient_type")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SCHEDULED', 'SENT', 'FAILED', 'SUPPRESSED')",
            name=op.f("ck_notifications_status"),
        ),
        sa.CheckConstraint("priority IN ('HIGH', 'NORMAL', 'LOW')", name=op.f("ck_notifications_priority")),
        sa.CheckConstraint(
            "recipient_type <> 'STAFF' OR recipient_membership_id IS NOT NULL",
            name=op.f("ck_notifications_staff_recipient"),
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["platform.shops.id"],
            name=op.f("fk_notifications_shop_id_shops"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "recipient_membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            name=op.f("fk_notifications_shop_id_recipient_membership_id_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("shop_id", "dedup_key", name=op.f("uq_notifications_shop_id_dedup_key")),
        sa.UniqueConstraint("shop_id", "id", name=op.f("uq_notifications_shop_id_id")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["shop_id", "recipient_membership_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["shop_id", "recipient_membership_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index(
        "ix_notifications_scheduled",
        "notifications",
        ["status", "scheduled_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )
    op.create_table(
        "staff_tasks",
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_membership_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_role", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), server_default="NORMAL", nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'DONE', 'RESOLVED', 'CANCELLED')", name=op.f("ck_staff_tasks_status")
        ),
        sa.CheckConstraint("priority IN ('HIGH', 'NORMAL', 'LOW')", name=op.f("ck_staff_tasks_priority")),
        sa.CheckConstraint(
            "assignee_membership_id IS NOT NULL OR assignee_role IS NOT NULL",
            name=op.f("ck_staff_tasks_has_assignee"),
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["platform.shops.id"], name=op.f("fk_staff_tasks_shop_id_shops"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "assignee_membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            name=op.f("fk_staff_tasks_shop_id_assignee_membership_id_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "branch_id"],
            ["platform.branches.shop_id", "platform.branches.id"],
            name=op.f("fk_staff_tasks_shop_id_branch_id_branches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_tasks")),
        sa.UniqueConstraint("shop_id", "dedup_key", name=op.f("uq_staff_tasks_shop_id_dedup_key")),
        sa.UniqueConstraint("shop_id", "id", name=op.f("uq_staff_tasks_shop_id_id")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_staff_tasks_assignee",
        "staff_tasks",
        ["shop_id", "status", "assignee_membership_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_staff_tasks_role",
        "staff_tasks",
        ["shop_id", "status", "assignee_role", "branch_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_staff_tasks_subject", "staff_tasks", ["shop_id", "subject_type", "subject_id"], schema=SCHEMA
    )
    op.create_table(
        "staff_notification_settings",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("quiet_from", sa.Time(), nullable=True),
        sa.Column("quiet_to", sa.Time(), nullable=True),
        sa.Column("telegram_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("muted_types", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id", "membership_id"],
            ["platform.memberships.shop_id", "platform.memberships.id"],
            name="fk_staff_notification_settings_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("membership_id", name=op.f("pk_staff_notification_settings")),
        sa.UniqueConstraint(
            "shop_id", "membership_id", name=op.f("uq_staff_notification_settings_shop_id_membership_id")
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "staff_telegram_links",
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["platform.principals.id"],
            name=op.f("fk_staff_telegram_links_principal_id_principals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("principal_id", name=op.f("pk_staff_telegram_links")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_staff_telegram_links_telegram_user_id",
        "staff_telegram_links",
        ["telegram_user_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )
    op.create_table(
        "telegram_link_codes",
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["platform.principals.id"],
            name=op.f("fk_telegram_link_codes_principal_id_principals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_link_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_telegram_link_codes_code_hash")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_telegram_link_codes_principal_created",
        "telegram_link_codes",
        ["principal_id", "created_at"],
        schema=SCHEMA,
    )

    op.add_column(
        "shop_policies",
        sa.Column("handoff_reminder_minutes", sa.Integer(), server_default="15", nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "shop_policies",
        sa.Column("inbox_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_shop_policies_handoff_reminder_minutes"),
        "shop_policies",
        "handoff_reminder_minutes BETWEEN 1 AND 1440",
        schema=SCHEMA,
    )

    # --- Qo'lda: RLS (10 §4) ---------------------------------------------------------------------
    shop = "NULLIF(current_setting('app.shop_id', true), '')::uuid"
    for table in ("notifications", "staff_tasks", "staff_notification_settings"):
        op.execute(f"ALTER TABLE platform.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE platform.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY shop_isolation ON platform.{table} "
            f"USING (shop_id = {shop}) WITH CHECK (shop_id = {shop})"
        )

    # --- Qo'lda: TD-01 partitsiya funksiyasi (SECURITY DEFINER, app_migrator egasi) ---------------
    op.execute(PARTITION_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION platform.ensure_monthly_partitions(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.ensure_monthly_partitions(integer) TO app_runtime")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform.ensure_monthly_partitions(integer)")
    op.drop_constraint(op.f("ck_shop_policies_handoff_reminder_minutes"), "shop_policies", schema=SCHEMA)
    op.drop_column("shop_policies", "inbox_hours", schema=SCHEMA)
    op.drop_column("shop_policies", "handoff_reminder_minutes", schema=SCHEMA)
    for table in (
        "telegram_link_codes",
        "staff_telegram_links",
        "staff_notification_settings",
        "staff_tasks",
        "notifications",
        "job_runs",
        "dead_letters",
        "consumer_receipts",
        "outbox_events",
    ):
        op.drop_table(table, schema=SCHEMA)
