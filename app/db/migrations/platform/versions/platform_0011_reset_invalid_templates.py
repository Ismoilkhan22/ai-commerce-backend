"""platform: noto'g'ri saqlangan xaridor matnlarini o'chirish (QA 5b H1)

Revision ID: platform_0011
Revises: platform_0010
Create Date: 2026-10-26

Eski tekshiruv `{0}`, `{a.b}`, `{a:>999}` va yolg'iz qavslarni o'tkazib yuborgan edi. Endi bunday matn
saqlanmaydi; avval saqlanganlari faolsizlantiriladi (`is_active = false`) — shop standart matnga qaytadi.
Jadvalda FORCE RLS: har shop o'z kontekstida tekshiriladi. Qaytarish (downgrade) ma'lumotni tiklamaydi.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.platform.notifications.customer_templates import CUSTOMER_TEMPLATES, TemplateBodyError, check_body

revision: str = "platform_0011"
down_revision: str | None = "platform_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    shop_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM platform.shops"))]
    for shop_id in shop_ids:
        bind.execute(sa.text("SELECT set_config('app.shop_id', :shop, true)"), {"shop": str(shop_id)})
        rows = bind.execute(
            sa.text(
                "SELECT id, template_key, body FROM platform.shop_message_templates "
                "WHERE shop_id = :shop AND is_active"
            ),
            {"shop": shop_id},
        ).all()
        for row_id, key, body in rows:
            try:
                if key not in CUSTOMER_TEMPLATES:
                    raise TemplateBodyError("unknown_template", [])
                check_body(key, body)
            except TemplateBodyError:
                bind.execute(
                    sa.text("UPDATE platform.shop_message_templates SET is_active = false WHERE id = :id"),
                    {"id": row_id},
                )
    bind.execute(sa.text("SELECT set_config('app.shop_id', '', true)"))


def downgrade() -> None:
    pass  # faolsizlantirilgan matnlar tiklanmaydi (ular xato edi)
