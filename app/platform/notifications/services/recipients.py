"""Kimga: aniq xodimlar va/yoki rol + filial bo'yicha faol a'zolar (business/04: filial doirasi).

Shop konteksti o'rnatilgan tranzaksiyada chaqiriladi (`memberships` RLS).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.staff.models.orm import Membership, MembershipBranch, Principal


@dataclass(frozen=True)
class Recipient:
    membership_id: UUID
    principal_id: UUID
    role: str
    locale: str


async def resolve_members(
    db: AsyncSession,
    shop_id: UUID,
    *,
    membership_ids: Iterable[UUID | None] = (),
    roles: Iterable[str] = (),
    branch_id: UUID | None = None,
) -> list[Recipient]:
    """`roles` + `branch_id`: shu rol egalaridan filial doirasi shu filialni qamraganlari (ALL yoki SELECTED
    ro'yxatida). `branch_id` yo'q — rolning hamma egasi."""
    ids = [m for m in membership_ids if m is not None]
    role_list = list(roles)
    if not ids and not role_list:
        return []
    conditions: list[ColumnElement[bool]] = []
    if ids:
        conditions.append(Membership.id.in_(ids))
    if role_list:
        role_match: ColumnElement[bool] = Membership.role.in_(role_list)
        if branch_id is not None:
            in_branch = exists().where(
                MembershipBranch.membership_id == Membership.id, MembershipBranch.branch_id == branch_id
            )
            role_match = role_match & or_(Membership.branch_scope == "ALL", in_branch)
        conditions.append(role_match)
    rows = await db.execute(
        select(Membership.id, Membership.principal_id, Membership.role, Principal.locale)
        .join(Principal, Principal.id == Membership.principal_id)
        .where(Membership.shop_id == shop_id, Membership.status == "ACTIVE", or_(*conditions))
        .order_by(Membership.id)
    )
    return [Recipient(m_id, p_id, role, locale or "uz") for m_id, p_id, role, locale in rows]
