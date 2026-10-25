"""commerce bo'limlari uchun umumiy API turlari."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class MemberRef(BaseModel):
    """Xodim — kim yaratdi, kim tasdiqladi, kimga biriktirilgan."""

    membership_id: UUID
    full_name: str | None


def member_ref(membership_id: UUID | None, names: dict[UUID, str]) -> MemberRef | None:
    if membership_id is None:
        return None
    return MemberRef(membership_id=membership_id, full_name=names.get(membership_id))
