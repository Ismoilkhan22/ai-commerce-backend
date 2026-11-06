"""storefront: sites, pages — shop sayti sozlamalari va ma'lumot sahifalari (4-modul, DEC-135)

Revision ID: storefront_0002
Revises: storefront_0001
Create Date: 2026-10-26

Jadvallar ORM modelidan; qo'lda: RLS (10 §4) — shop konteksti bo'yicha, FORCE. DBML bu ikki jadvalni
ommaviy ma'lumot deb RLS'siz qoldirgan, lekin sayt o'qishi baribir shop kontekstini o'rnatadi — himoya
qatlami qo'shimcha (panel boshqa shop sozlamasiga tegolmaydi).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "storefront_0002"
down_revision: str | None = "storefront_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("logo_file_id", sa.Uuid(), nullable=True),
        sa.Column("accent_color", sa.Text(), server_default="#7C3AED", nullable=False),
        sa.Column("theme_mode", sa.Text(), server_default="LIGHT", nullable=False),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("seo_description", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("instagram_username", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'LIVE', 'PAUSED')", name=op.f("ck_sites_status")),
        sa.CheckConstraint("theme_mode IN ('LIGHT', 'DARK')", name=op.f("ck_sites_theme_mode")),
        sa.CheckConstraint("accent_color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_sites_accent_color")),
        sa.PrimaryKeyConstraint("shop_id", name=op.f("pk_sites")),
        schema="storefront",
    )
    op.create_table(
        "pages",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('ABOUT', 'DELIVERY_PAYMENT', 'WARRANTY_RETURNS')", name=op.f("ck_pages_kind")
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["storefront.sites.shop_id"],
            name=op.f("fk_pages_shop_id_sites"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("shop_id", "id", name=op.f("uq_pages_shop_id_id")),
        sa.UniqueConstraint("shop_id", "kind", name=op.f("uq_pages_shop_id_kind")),
        schema="storefront",
    )

    # --- Qo'lda: RLS (10 §4) ---------------------------------------------------------------------
    shop = "NULLIF(current_setting('app.shop_id', true), '')::uuid"
    for table in ("sites", "pages"):
        op.execute(f"ALTER TABLE storefront.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE storefront.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY shop_isolation ON storefront.{table} "
            f"USING (shop_id = {shop}) WITH CHECK (shop_id = {shop})"
        )


def downgrade() -> None:
    op.drop_table("pages", schema="storefront")
    op.drop_table("sites", schema="storefront")
