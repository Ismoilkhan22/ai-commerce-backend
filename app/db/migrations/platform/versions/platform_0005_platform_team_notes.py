"""platform: platform team invitations and internal shop notes (business/15 §3, §5)

Revision ID: platform_0005
Revises: platform_0004
Create Date: 2026-10-24

db/platform.dbml dagi 2026-10-24 taklifi (founder tasdiqladi):
- platform_staff: INVITED holati, invited_by, updated_at, version (rolni ikki admin bir vaqtda o'zgartirsa);
- platform_staff_invitations: jamoaga bir martalik havolalar (taklif, parol tiklash) — faqat hash;
- shop_notes: platformaning ichki izohi, faqat qo'shiladi. RLS yo'q — faqat platforma panelidan o'qiladi.
Mavjud platform_staff qatorlari ACTIVE bo'lib qoladi.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "platform_0005"
down_revision: str | None = "platform_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("platform_staff", sa.Column("invited_by", sa.Uuid(), nullable=True), schema="platform")
    op.add_column(
        "platform_staff",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="platform",
    )
    # Mavjud qatorlar uchun 1, keyin standart qiymat olib tashlanadi (model bilan bir xil: version ilovada)
    op.add_column(
        "platform_staff",
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        schema="platform",
    )
    op.alter_column("platform_staff", "version", server_default=None, schema="platform")
    op.create_foreign_key(
        op.f("fk_platform_staff_invited_by_platform_staff"),
        "platform_staff",
        "platform_staff",
        ["invited_by"],
        ["id"],
        source_schema="platform",
        referent_schema="platform",
    )
    op.drop_constraint(op.f("ck_platform_staff_status"), "platform_staff", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_platform_staff_status"),
        "platform_staff",
        "status IN ('INVITED', 'ACTIVE', 'DISABLED')",
        schema="platform",
    )

    op.create_table(
        "platform_staff_invitations",
        sa.Column("platform_staff_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('INVITE', 'PASSWORD_RESET')", name=op.f("ck_platform_staff_invitations_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["platform_staff_id"],
            ["platform.platform_staff.id"],
            name=op.f("fk_platform_staff_invitations_platform_staff_id_platform_staff"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_staff_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_platform_staff_invitations_token_hash")),
        schema="platform",
    )
    op.create_index(
        "ix_platform_staff_invitations_platform_staff_id",
        "platform_staff_invitations",
        ["platform_staff_id"],
        unique=False,
        schema="platform",
    )

    op.create_table(
        "shop_notes",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name=op.f("ck_shop_notes_body_length")),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["platform.shops.id"], name=op.f("fk_shop_notes_shop_id_shops"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["platform.platform_staff.id"],
            name=op.f("fk_shop_notes_author_id_platform_staff"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_notes")),
        schema="platform",
    )
    op.create_index(
        "ix_shop_notes_shop_id_created_at",
        "shop_notes",
        ["shop_id", "created_at"],
        unique=False,
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index("ix_shop_notes_shop_id_created_at", table_name="shop_notes", schema="platform")
    op.drop_table("shop_notes", schema="platform")
    op.drop_index(
        "ix_platform_staff_invitations_platform_staff_id",
        table_name="platform_staff_invitations",
        schema="platform",
    )
    op.drop_table("platform_staff_invitations", schema="platform")
    # Taklif qilingan (hali qabul qilinmagan) a'zolar eski CHECK'ga sig'maydi — o'chirilgan deb belgilanadi
    op.execute("UPDATE platform.platform_staff SET status = 'DISABLED' WHERE status = 'INVITED'")
    op.drop_constraint(op.f("ck_platform_staff_status"), "platform_staff", schema="platform", type_="check")
    op.create_check_constraint(
        op.f("ck_platform_staff_status"),
        "platform_staff",
        "status IN ('ACTIVE', 'DISABLED')",
        schema="platform",
    )
    op.drop_constraint(
        op.f("fk_platform_staff_invited_by_platform_staff"),
        "platform_staff",
        schema="platform",
        type_="foreignkey",
    )
    op.drop_column("platform_staff", "version", schema="platform")
    op.drop_column("platform_staff", "updated_at", schema="platform")
    op.drop_column("platform_staff", "invited_by", schema="platform")
