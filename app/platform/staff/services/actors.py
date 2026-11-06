"""Fon vazifasi xodim nomidan ishlaganda (katalog importi, 5c): kim boshlagan bo'lsa — o'sha a'zolik.

Ruxsatlar xuddi so'rovdagidek BAZADAN o'qiladi (10 §3): vazifa navbatda turgan paytda xodim o'chirilgan yoki
roli o'zgargan bo'lsa — yangi holat amal qiladi. Faol bo'lmagan a'zolik — `None` (vazifa to'xtaydi).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.staff.models.orm import Membership, MembershipBranch, Principal
from app.platform.staff.permissions import PermissionRegistry
from app.shared.types.actor import ActorContext


async def staff_actor(
    db: AsyncSession, shop_id: UUID, membership_id: UUID, permissions: PermissionRegistry
) -> ActorContext | None:
    row = (
        await db.execute(
            select(Membership, Principal)
            .join(Principal, Principal.id == Membership.principal_id)
            .where(Membership.id == membership_id, Membership.shop_id == shop_id)
        )
    ).one_or_none()
    if row is None or row[0].status != "ACTIVE":
        return None
    membership, principal = row
    branch_ids: frozenset[UUID] | None = None
    if membership.branch_scope == "SELECTED":
        branch_ids = frozenset(
            (
                await db.execute(
                    select(MembershipBranch.branch_id).where(MembershipBranch.membership_id == membership.id)
                )
            ).scalars()
        )
    return ActorContext(
        actor_type="STAFF",
        actor_id=principal.id,
        shop_id=shop_id,
        surface="worker",
        roles=frozenset({membership.role}),
        permissions=permissions.for_role(membership.role),
        branch_ids=branch_ids,
        locale=principal.locale,
        membership_id=membership.id,
    )
