"""Xodimlar: taklif, rol va filiallar, o'chirish, parolni tiklash havolasi (business/04, DEC-131).

Oxirgi faol egani o'chirish yoki rolini o'zgartirish — bazadagi trigger to'xtatadi (UAT-M02);
bu yerda trigger xatosi `LAST_OWNER_REQUIRED` ga aylantiriladi.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.config import AuthConfig
from app.platform.auth.models.orm import AuthSession
from app.platform.shops.models.orm import Branch, Shop
from app.platform.staff.models.orm import Membership, MembershipBranch, Principal
from app.platform.staff.schemas import AccessUpdate, InviteIn, InviteOut, LinkOut, MemberOut
from app.platform.staff.services.links import issue_link, revoke_links
from app.platform.staff.state_machine import ENTITY as MEMBERSHIP
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.errors.base import (
    InvalidTransitionError,
    LastOwnerRequiredError,
    NotFoundError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext


async def flush_guarding_owner(db: AsyncSession) -> None:
    try:
        await db.flush()
    except DBAPIError as exc:
        if "LAST_OWNER_REQUIRED" in str(exc.orig):
            raise LastOwnerRequiredError("Shop must keep at least one active owner") from exc
        raise


class StaffService:
    def __init__(self, use: UseService, audit: AuditService, config: AuthConfig) -> None:
        self.use = use
        self.audit = audit
        self.config = config

    async def list_members(self, db: AsyncSession, actor: ActorContext) -> list[MemberOut]:
        rows = (
            await db.execute(
                select(Membership, Principal)
                .join(Principal, Principal.id == Membership.principal_id)
                .where(Membership.shop_id == actor.shop_id)
                .order_by(Membership.created_at)
            )
        ).all()
        return [await self._out(db, m, p) for m, p in rows]

    async def invite(self, db: AsyncSession, actor: ActorContext, data: InviteIn) -> InviteOut:
        assert actor.shop_id is not None
        phone = normalize_phone(data.phone)
        principal = (await db.execute(select(Principal).where(Principal.phone == phone))).scalar_one_or_none()
        if principal is not None:
            # Hozircha bir odam — bitta shop (DEC-131); platforma jamoasi shop xodimi bo'lmaydi
            raise ValidationError(
                "Phone already registered", fields=[{"field": "phone", "code": "not_unique", "params": {}}]
            )
        branch_ids = await self._checked_branches(db, actor.shop_id, data.branch_scope, data.branch_ids)
        shop = await db.get(Shop, actor.shop_id)
        assert shop is not None
        principal = Principal(phone=phone, full_name=data.full_name.strip(), locale=shop.default_locale)
        db.add(principal)
        await db.flush()
        membership = Membership(
            shop_id=actor.shop_id,
            principal_id=principal.id,
            role=data.role,
            branch_scope=data.branch_scope,
            invited_by=actor.membership_id,
        )
        db.add(membership)
        await db.flush()
        await self._set_branches(db, membership, branch_ids)
        url, expires_at = await issue_link(
            db,
            shop_id=actor.shop_id,
            membership_id=membership.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.app_public_url,
        )
        await self.audit.record(
            db,
            action="staff.member.invited",
            entity_type=MEMBERSHIP,
            entity_id=membership.id,
            actor=actor,
            diff={"role": {"old": None, "new": data.role}},
        )
        return InviteOut(
            member=await self._out(db, membership, principal), invite=LinkOut(url=url, expires_at=expires_at)
        )

    async def resend_invite(self, db: AsyncSession, actor: ActorContext, membership_id: UUID) -> LinkOut:
        membership = await self._get(db, actor, membership_id)
        if membership.status != "INVITED":
            raise InvalidTransitionError(
                "Member already joined",
                entity=MEMBERSHIP,
                **{"from": membership.status},
                command="RESEND_INVITE",
            )
        url, expires_at = await issue_link(
            db,
            shop_id=membership.shop_id,
            membership_id=membership.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.app_public_url,
        )
        await self.audit.record(
            db,
            action="staff.member.invite_resent",
            entity_type=MEMBERSHIP,
            entity_id=membership.id,
            actor=actor,
        )
        return LinkOut(url=url, expires_at=expires_at)

    async def update_access(
        self,
        db: AsyncSession,
        actor: ActorContext,
        membership_id: UUID,
        expected_version: int,
        data: AccessUpdate,
    ) -> MemberOut:
        membership = await self._get(db, actor, membership_id, for_update=True)
        check_version(membership.version, expected_version)
        if membership.status == "DISABLED":
            raise InvalidTransitionError(
                "Member is disabled", entity=MEMBERSHIP, **{"from": "DISABLED"}, command="UPDATE_ACCESS"
            )
        branch_ids = await self._checked_branches(db, membership.shop_id, data.branch_scope, data.branch_ids)
        old_role = membership.role
        membership.role = data.role
        membership.branch_scope = data.branch_scope
        await flush_guarding_owner(db)  # oxirgi egani menejer qilib bo'lmaydi
        await self._set_branches(db, membership, branch_ids)
        await self.audit.record(
            db,
            action="staff.member.access_changed",
            entity_type=MEMBERSHIP,
            entity_id=membership.id,
            actor=actor,
            entity_version=membership.version,
            diff={"role": {"old": old_role, "new": data.role}, "branch_scope": data.branch_scope},
        )
        principal = await db.get(Principal, membership.principal_id)
        assert principal is not None
        return await self._out(db, membership, principal)

    async def disable(
        self, db: AsyncSession, actor: ActorContext, membership_id: UUID, reason: str | None
    ) -> MemberOut:
        membership = await self._get(db, actor, membership_id, for_update=True)
        command = "REVOKE_INVITE" if membership.status == "INVITED" else "DISABLE"
        rule = self.use.validate_transition(MEMBERSHIP, membership.status, "DISABLED", command, actor)
        now = utcnow()
        membership.status, membership.disabled_at = "DISABLED", now
        await flush_guarding_owner(db)
        await self.use.log_transition(db, entity_id=membership.id, rule=rule, actor=actor, reason=reason)
        # Barcha sessiyalari darhol tugaydi (TC-025); ochiq havolalar bekor
        await db.execute(
            update(AuthSession)
            .where(AuthSession.principal_id == membership.principal_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason="MEMBERSHIP_DISABLED")
        )
        await revoke_links(db, membership.id, None, now)
        await self.audit.record(
            db,
            action="staff.member.disabled",
            entity_type=MEMBERSHIP,
            entity_id=membership.id,
            actor=actor,
            reason=reason,
        )
        principal = await db.get(Principal, membership.principal_id)
        assert principal is not None
        return await self._out(db, membership, principal)

    async def issue_password_reset(
        self, db: AsyncSession, actor: ActorContext, membership_id: UUID
    ) -> LinkOut:
        membership = await self._get(db, actor, membership_id)
        return await self.password_reset_link(db, actor, membership)

    async def password_reset_link(
        self, db: AsyncSession, actor: ActorContext, membership: Membership
    ) -> LinkOut:
        if membership.status != "ACTIVE":
            raise InvalidTransitionError(
                "Member is not active",
                entity=MEMBERSHIP,
                **{"from": membership.status},
                command="PASSWORD_RESET",
            )
        url, expires_at = await issue_link(
            db,
            shop_id=membership.shop_id,
            membership_id=membership.id,
            purpose="PASSWORD_RESET",
            ttl=self.config.password_reset_ttl,
            app_url=self.config.app_public_url,
        )
        await self.audit.record(
            db,
            action="staff.member.password_reset_issued",
            entity_type=MEMBERSHIP,
            entity_id=membership.id,
            actor=actor,
        )
        return LinkOut(url=url, expires_at=expires_at)

    # ---------------------------------------------------------------- helpers
    async def _get(
        self, db: AsyncSession, actor: ActorContext, membership_id: UUID, for_update: bool = False
    ) -> Membership:
        query = select(Membership).where(Membership.id == membership_id, Membership.shop_id == actor.shop_id)
        membership = (await db.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()
        if membership is None:
            raise NotFoundError("Member not found")  # boshqa shopniki ham — 404 (TC-001)
        return membership

    async def _checked_branches(
        self, db: AsyncSession, shop_id: UUID, scope: str, branch_ids: Sequence[UUID]
    ) -> list[UUID]:
        if scope == "ALL":
            return []
        unique = list(dict.fromkeys(branch_ids))
        if not unique:
            raise ValidationError(
                "Branches required", fields=[{"field": "branch_ids", "code": "required", "params": {}}]
            )
        found = set(
            (
                await db.execute(
                    select(Branch.id).where(
                        Branch.shop_id == shop_id, Branch.id.in_(unique), Branch.status == "ACTIVE"
                    )
                )
            ).scalars()
        )
        if found != set(unique):
            raise ValidationError(
                "Unknown or closed branch",
                fields=[{"field": "branch_ids", "code": "invalid_choice", "params": {}}],
            )
        return unique

    async def _set_branches(self, db: AsyncSession, membership: Membership, branch_ids: list[UUID]) -> None:
        await db.execute(delete(MembershipBranch).where(MembershipBranch.membership_id == membership.id))
        for branch_id in branch_ids:
            db.add(
                MembershipBranch(shop_id=membership.shop_id, membership_id=membership.id, branch_id=branch_id)
            )
        await db.flush()

    async def _out(self, db: AsyncSession, membership: Membership, principal: Principal) -> MemberOut:
        branch_ids = list(
            (
                await db.execute(
                    select(MembershipBranch.branch_id).where(MembershipBranch.membership_id == membership.id)
                )
            ).scalars()
        )
        return MemberOut(
            id=membership.id,
            principal_id=principal.id,
            full_name=principal.full_name,
            phone=principal.phone,
            role=membership.role,
            status=membership.status,
            branch_scope=membership.branch_scope,
            branch_ids=branch_ids,
            activated_at=membership.activated_at,
            version=membership.version,
        )
