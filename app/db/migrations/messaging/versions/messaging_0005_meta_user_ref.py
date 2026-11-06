"""messaging: Meta ma'lumot o'chirish so'rovi — kanal akkauntini Facebook foydalanuvchi ID'si bo'yicha topish

Revision ID: messaging_0005
Revises: messaging_0004
Create Date: 2026-11-02

`channel_accounts` RLS'ga uchinchi identity varianti: `app.meta_user_ref` = `settings->>'meta_user_id'`
(faqat INSTAGRAM; OAuth bilan ulanganda yoziladi). Deauthorize / data deletion callback'ida shop noma'lum.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "messaging_0005"
down_revision: str | None = "messaging_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHOP = "NULLIF(current_setting('app.shop_id', true), '')::uuid"
ACCOUNT_REF = "NULLIF(current_setting('app.channel_account_ref', true), '')"
EXTERNAL_REF = "NULLIF(current_setting('app.channel_external_ref', true), '')"
META_USER_REF = "NULLIF(current_setting('app.meta_user_ref', true), '')"


def _policy(extra: str) -> None:
    op.execute("DROP POLICY channel_accounts_isolation ON messaging.channel_accounts")
    op.execute(
        "CREATE POLICY channel_accounts_isolation ON messaging.channel_accounts "
        f"USING (shop_id = {SHOP} OR account_ref = {ACCOUNT_REF} "
        f"OR channel || ':' || external_account_id = {EXTERNAL_REF}{extra}) "
        f"WITH CHECK (shop_id = {SHOP})"
    )


def upgrade() -> None:
    _policy(f" OR (channel = 'INSTAGRAM' AND settings ->> 'meta_user_id' = {META_USER_REF})")


def downgrade() -> None:
    _policy("")
