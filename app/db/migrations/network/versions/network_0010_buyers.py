"""network: xaridor akkauntlari, sessiyalar, tarix, sevimlilar (platforma darajasi, RLS yo'q)

Revision ID: network_0010
Revises: network_0009
Create Date: 2026-11-03 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "network_0010"
down_revision: str | None = "network_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_BUYER_FK = "network.buyers.id"


def upgrade() -> None:
    op.create_table(
        "buyers",
        sa.Column("phone_hash", sa.Text(), nullable=False),
        sa.Column("phone_enc", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), server_default="uz", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("locale IN ('uz', 'ru', 'en')", name=op.f("ck_buyers_locale")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyers")),
        sa.UniqueConstraint("phone_hash", name=op.f("uq_buyers_phone_hash")),
        schema="network",
    )
    op.create_table(
        "buyer_login_codes",
        sa.Column("phone_hash", sa.Text(), nullable=False),
        sa.Column("phone_enc", sa.Text(), nullable=True),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sends", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyer_login_codes")),
        schema="network",
    )
    op.create_index(
        "ix_buyer_login_codes_phone_created",
        "buyer_login_codes",
        ["phone_hash", "created_at"],
        unique=False,
        schema="network",
    )
    op.create_table(
        "buyer_sessions",
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["buyer_id"], [_BUYER_FK], name=op.f("fk_buyer_sessions_buyer_id_buyers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyer_sessions")),
        schema="network",
    )
    op.create_index("ix_buyer_sessions_buyer", "buyer_sessions", ["buyer_id"], unique=False, schema="network")
    op.create_table(
        "buyer_views",
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_id", sa.Uuid(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["buyer_id"], [_BUYER_FK], name=op.f("fk_buyer_views_buyer_id_buyers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("buyer_id", "canonical_id", name=op.f("pk_buyer_views")),
        schema="network",
    )
    op.create_table(
        "buyer_searches",
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("searched_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["buyer_id"], [_BUYER_FK], name=op.f("fk_buyer_searches_buyer_id_buyers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyer_searches")),
        schema="network",
    )
    op.create_index(
        "ix_buyer_searches_buyer_at",
        "buyer_searches",
        ["buyer_id", "searched_at"],
        unique=False,
        schema="network",
    )
    op.create_table(
        "buyer_favorites",
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_id", sa.Uuid(), nullable=False),
        sa.Column("saved_price_uzs_minor", sa.BigInteger(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["buyer_id"], [_BUYER_FK], name=op.f("fk_buyer_favorites_buyer_id_buyers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("buyer_id", "canonical_id", name=op.f("pk_buyer_favorites")),
        schema="network",
    )
    op.create_table(
        "buyer_advisor_messages",
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_buyer_advisor_messages_role")),
        sa.ForeignKeyConstraint(
            ["buyer_id"],
            [_BUYER_FK],
            name=op.f("fk_buyer_advisor_messages_buyer_id_buyers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyer_advisor_messages")),
        schema="network",
    )
    op.create_index(
        "ix_buyer_advisor_messages_buyer_at",
        "buyer_advisor_messages",
        ["buyer_id", "created_at"],
        unique=False,
        schema="network",
    )


def downgrade() -> None:
    op.drop_table("buyer_advisor_messages", schema="network")
    op.drop_table("buyer_favorites", schema="network")
    op.drop_table("buyer_searches", schema="network")
    op.drop_table("buyer_views", schema="network")
    op.drop_table("buyer_sessions", schema="network")
    op.drop_table("buyer_login_codes", schema="network")
    op.drop_table("buyers", schema="network")
