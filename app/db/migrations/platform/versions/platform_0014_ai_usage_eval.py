"""llm: ai_usage — eval xarajati (purpose EVAL, shop_id NULL)

Revision ID: platform_0014
Revises: platform_0013
Create Date: 2026-10-27 12:00:00.000000

6c: baholash yugurishining xarajati `ai_usage` ga shop_id'siz yoziladi (platforma xarajati, shop limitiga
kirmaydi). RLS: shop konteksti bo'lmagan tranzaksiya (platforma/worker) faqat shop_id'siz qatorlarni ko'radi
va yozadi; shop konteksti — faqat o'z qatorlarini (eval qatorlari shopga ko'rinmaydi).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0014"
down_revision: str | None = "platform_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHOP = "NULLIF(current_setting('app.shop_id', true), '')::uuid"
OLD_PURPOSES = "purpose IN ('SALES_TURN', 'SUMMARY', 'CLASSIFY', 'EVAL_JUDGE', 'SANDBOX')"
NEW_PURPOSES = "purpose IN ('SALES_TURN', 'SUMMARY', 'CLASSIFY', 'EVAL_JUDGE', 'SANDBOX', 'EVAL')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", schema="platform", type_="check")
    op.create_check_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", NEW_PURPOSES, schema="platform")
    rule = f"shop_id = {SHOP} OR (shop_id IS NULL AND {SHOP} IS NULL)"
    op.execute("DROP POLICY shop_isolation ON platform.ai_usage")
    op.execute(f"CREATE POLICY shop_isolation ON platform.ai_usage USING ({rule}) WITH CHECK ({rule})")


def downgrade() -> None:
    op.execute("DELETE FROM platform.ai_usage WHERE shop_id IS NULL OR purpose = 'EVAL'")
    op.execute("DROP POLICY shop_isolation ON platform.ai_usage")
    op.execute(
        "CREATE POLICY shop_isolation ON platform.ai_usage "
        f"USING (shop_id = {SHOP}) WITH CHECK (shop_id = {SHOP})"
    )
    op.drop_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", schema="platform", type_="check")
    op.create_check_constraint(op.f("ck_ai_usage_purpose"), "ai_usage", OLD_PURPOSES, schema="platform")
