"""network: baseline — schema env va alembic_version jadvali (Stage 2)

Revision ID: network_0001
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence

revision: str = "network_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
