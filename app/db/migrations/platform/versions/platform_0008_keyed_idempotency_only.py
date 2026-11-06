"""platform: idempotency_keys — faqat kalitli barmoq izi (QA M04 F2, 2-tur)

Kalitsiz SHA-256 bilan yozilgan eski qatorlar o'chiriladi: ular vaqtinchalik (24 soat) edi, lekin o'chirilmasa
bazani o'qigan odam tana ichidagi telefonni oflayn tanlab topa oladi. CHECK — endi faqat `h1:` (HMAC).

Revision ID: platform_0008
Revises: platform_0007
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0008"
down_revision: str | None = "platform_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYED = "request_hash LIKE 'h1:%'"


def upgrade() -> None:
    op.execute(f"DELETE FROM platform.idempotency_keys WHERE NOT ({_KEYED})")  # noqa: S608 — doimiy matn
    op.create_check_constraint(
        op.f("ck_idempotency_keys_request_hash_keyed"), "idempotency_keys", _KEYED, schema="platform"
    )


def downgrade() -> None:
    # O'chirilgan qatorlar tiklanmaydi (vaqtinchalik edi)
    op.drop_constraint(
        op.f("ck_idempotency_keys_request_hash_keyed"), "idempotency_keys", schema="platform", type_="check"
    )
