"""catalog: QA tuzatishlari — kutubxona yagonaligi, rasm fayli bitta joyda, qo'lda uzilgan bog'lanish

Revision ID: catalog_0003
Revises: catalog_0002
Create Date: 2026-10-25

- `reference_hardware_specs.brand_normalized` — brend katta-kichik harf va belgilarsiz ("QA Race" =
  "qa race"). Yagonalik endi shu ustun bo'yicha va faqat eskirmagan (RETIRED emas) modellar orasida:
  eskirgan model shu modelni qayta kiritishga to'sqinlik qilmaydi. MPN yagonaligi ham shunday.
- `skus.spec_autolink_blocked` — xodim bog'lanishni qo'lda uzgan: avtomatika uni qayta bog'lamaydi,
  xodim o'zi bog'laguncha.
- `product_media (shop_id, file_id)` yagona — bitta fayl faqat bitta mahsulot rasmida (birida o'chirilsa,
  boshqasida buzilmasin).
- `skus (shop_id, lower(sku_code))` indeksi — SKU kodi katta-kichik harfsiz tekshiriladi ("ABC-1" = "abc-1").
  Unikal emas: yagonalikni service tranzaksiya qulfi bilan ta'minlaydi (eski ma'lumotda faqat harfi
  farq qiladigan juftlar bo'lishi mumkin — ularni migratsiya o'chirmaydi).
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "catalog_0003"
down_revision: str | None = "catalog_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOT_ALNUM = re.compile(r"[\W_]+", re.UNICODE)  # app.domains.catalog.pc_specs.normalize bilan bir xil


def _normalize(value: str | None) -> str:
    return _NOT_ALNUM.sub("", (value or "").upper())


def upgrade() -> None:
    op.add_column(
        "reference_hardware_specs", sa.Column("brand_normalized", sa.Text(), nullable=True), schema="catalog"
    )
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, brand FROM catalog.reference_hardware_specs")).all()
    for spec_id, brand in rows:
        conn.execute(
            sa.text("UPDATE catalog.reference_hardware_specs SET brand_normalized = :b WHERE id = :id"),
            {"b": _normalize(brand), "id": spec_id},
        )
    op.alter_column("reference_hardware_specs", "brand_normalized", nullable=False, schema="catalog")
    op.drop_constraint(
        op.f("uq_reference_hardware_specs_model"),
        "reference_hardware_specs",
        schema="catalog",
        type_="unique",
    )
    op.create_index(
        "uq_reference_hardware_specs_model",
        "reference_hardware_specs",
        ["category", "brand_normalized", "model_normalized", "variant_key"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("status <> 'RETIRED'"),
    )
    op.drop_index(
        "uq_reference_hardware_specs_mpn_normalized", table_name="reference_hardware_specs", schema="catalog"
    )
    op.create_index(
        "uq_reference_hardware_specs_mpn_normalized",
        "reference_hardware_specs",
        ["mpn_normalized"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("mpn_normalized IS NOT NULL AND status <> 'RETIRED'"),
    )

    op.add_column(
        "skus",
        sa.Column("spec_autolink_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="catalog",
    )
    op.create_unique_constraint(
        op.f("uq_product_media_shop_id_file_id"), "product_media", ["shop_id", "file_id"], schema="catalog"
    )
    op.create_index(
        "ix_skus_shop_id_sku_code_lower", "skus", ["shop_id", sa.text("lower(sku_code)")], schema="catalog"
    )


def downgrade() -> None:
    op.drop_index("ix_skus_shop_id_sku_code_lower", table_name="skus", schema="catalog")
    op.drop_constraint(
        op.f("uq_product_media_shop_id_file_id"), "product_media", schema="catalog", type_="unique"
    )
    op.drop_column("skus", "spec_autolink_blocked", schema="catalog")
    op.drop_index(
        "uq_reference_hardware_specs_mpn_normalized", table_name="reference_hardware_specs", schema="catalog"
    )
    op.create_index(
        "uq_reference_hardware_specs_mpn_normalized",
        "reference_hardware_specs",
        ["mpn_normalized"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("mpn_normalized IS NOT NULL"),
    )
    op.drop_index(
        "uq_reference_hardware_specs_model", table_name="reference_hardware_specs", schema="catalog"
    )
    op.create_unique_constraint(
        op.f("uq_reference_hardware_specs_model"),
        "reference_hardware_specs",
        ["category", "brand", "model_normalized", "variant_key"],
        schema="catalog",
    )
    op.drop_column("reference_hardware_specs", "brand_normalized", schema="catalog")
