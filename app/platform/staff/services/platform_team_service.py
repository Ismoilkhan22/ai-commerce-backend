"""Platforma jamoasi: taklif, rol, o'chirish, parol tiklash havolasi (business/15 §5).

Faqat platforma admini boshqaradi. Oxirgi faol PLATFORM_ADMIN'ni o'chirib yoki rolini olib bo'lmaydi:
avval hamma faol adminlar qatori qulflanadi (id tartibida — deadlock bo'lmasin), keyin sanaladi.
Ikki admin bir vaqtda bir-birini o'chirmoqchi bo'lsa, ikkinchisi birinchisi tugashini kutadi va
yangi holatni ko'radi.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.config import AuthConfig
from app.platform.auth.models.orm import AuthSession
from app.platform.staff.models.orm import PlatformStaff, Principal
from app.platform.staff.platform_schemas import (
    PlatformInviteIn,
    PlatformInviteOut,
    PlatformRole,
    PlatformStaffOut,
)
from app.platform.staff.schemas import LinkOut
from app.platform.staff.services.platform_links import issue_platform_link, revoke_platform_links
from app.shared.clock import utcnow
from app.shared.db.session import set_identity_context
from app.shared.errors.base import (
    ForbiddenError,
    InvalidTransitionError,
    LastAdminRequiredError,
    NotFoundError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

STAFF = "platform.platform_staff"
ADMIN = "PLATFORM_ADMIN"


def _phone_taken() -> ValidationError:
    return ValidationError(
        "Phone already registered", fields=[{"field": "phone", "code": "not_unique", "params": {}}]
    )


class PlatformTeamService:
    def __init__(self, audit: AuditService, config: AuthConfig) -> None:
        self.audit = audit
        self.config = config

    async def list_staff(self, db: AsyncSession) -> list[PlatformStaffOut]:
        rows = (
            await db.execute(
                select(PlatformStaff, Principal)
                .join(Principal, Principal.id == PlatformStaff.principal_id)
                .order_by(PlatformStaff.created_at)
            )
        ).all()
        names = await self._inviter_names(db, (staff.invited_by for staff, _ in rows))
        return [self._out(staff, principal, names) for staff, principal in rows]

    async def invite(
        self, db: AsyncSession, actor: ActorContext, data: PlatformInviteIn
    ) -> PlatformInviteOut:
        phone = normalize_phone(data.phone)
        if (await db.execute(select(Principal.id).where(Principal.phone == phone))).first():
            raise _phone_taken()  # shop xodimi ham, jamoa a'zosi ham — bir odam bitta joyda
        principal = Principal(phone=phone, full_name=data.full_name.strip())
        db.add(principal)
        try:
            await db.flush()
        except IntegrityError as exc:  # parallel so'rov xuddi shu telefonni oldi
            if "uq_principals_phone" in str(exc.orig):
                raise _phone_taken() from exc
            raise
        inviter = await self._staff_id_of(db, actor)
        staff = PlatformStaff(principal_id=principal.id, role=data.role, status="INVITED", invited_by=inviter)
        db.add(staff)
        await db.flush()
        await db.refresh(staff)  # created_at — bazada yaratiladi
        url, expires_at = await issue_platform_link(
            db,
            staff_id=staff.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.platform_app_public_url,
            created_by=inviter,
        )
        await self.audit.record(
            db,
            action="platform.staff.invited",
            entity_type=STAFF,
            entity_id=staff.id,
            actor=actor,
            diff={"role": {"old": None, "new": data.role}},
        )
        names = await self._inviter_names(db, [inviter])
        return PlatformInviteOut(
            member=self._out(staff, principal, names), invite=LinkOut(url=url, expires_at=expires_at)
        )

    async def resend_invite(self, db: AsyncSession, actor: ActorContext, staff_id: UUID) -> LinkOut:
        staff = await self._get(db, staff_id)
        if staff.status != "INVITED":
            raise InvalidTransitionError(
                "Member already joined", entity=STAFF, **{"from": staff.status}, command="RESEND_INVITE"
            )
        url, expires_at = await issue_platform_link(
            db,
            staff_id=staff.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.platform_app_public_url,
            created_by=await self._staff_id_of(db, actor),
        )
        await self.audit.record(
            db, action="platform.staff.invite_resent", entity_type=STAFF, entity_id=staff.id, actor=actor
        )
        return LinkOut(url=url, expires_at=expires_at)

    async def issue_password_reset(self, db: AsyncSession, actor: ActorContext, staff_id: UUID) -> LinkOut:
        staff = await self._get(db, staff_id)
        if staff.status != "ACTIVE":
            raise InvalidTransitionError(
                "Member is not active", entity=STAFF, **{"from": staff.status}, command="PASSWORD_RESET"
            )
        url, expires_at = await issue_platform_link(
            db,
            staff_id=staff.id,
            purpose="PASSWORD_RESET",
            ttl=self.config.password_reset_ttl,
            app_url=self.config.platform_app_public_url,
            created_by=await self._staff_id_of(db, actor),
        )
        await self.audit.record(
            db,
            action="platform.staff.password_reset_issued",
            entity_type=STAFF,
            entity_id=staff.id,
            actor=actor,
        )
        return LinkOut(url=url, expires_at=expires_at)

    async def change_role(
        self, db: AsyncSession, actor: ActorContext, staff_id: UUID, expected_version: int, role: PlatformRole
    ) -> PlatformStaffOut:
        active_admins = await self._lock_active_admins(db)
        staff = await self._get(db, staff_id, for_update=True)
        check_version(staff.version, expected_version)
        if staff.status == "DISABLED":
            raise InvalidTransitionError(
                "Member is disabled", entity=STAFF, **{"from": "DISABLED"}, command="CHANGE_ROLE"
            )
        if role != ADMIN:
            self._guard_last_admin(staff, active_admins)
        old_role = staff.role
        staff.role = role
        await db.flush()
        await self.audit.record(
            db,
            action="platform.staff.role_changed",
            entity_type=STAFF,
            entity_id=staff.id,
            actor=actor,
            entity_version=staff.version,
            diff={"role": {"old": old_role, "new": role}},
        )
        return await self._out_one(db, staff)

    async def disable(
        self, db: AsyncSession, actor: ActorContext, staff_id: UUID, reason: str | None
    ) -> PlatformStaffOut:
        active_admins = await self._lock_active_admins(db)
        staff = await self._get(db, staff_id, for_update=True)
        if staff.principal_id == actor.actor_id:
            raise ForbiddenError("You cannot disable yourself", reason="self")
        if staff.status == "DISABLED":
            raise InvalidTransitionError(
                "Member is already disabled", entity=STAFF, **{"from": "DISABLED"}, command="DISABLE"
            )
        self._guard_last_admin(staff, active_admins)
        now = utcnow()
        staff.status = "DISABLED"
        await db.flush()
        # Platforma sessiyalari darhol tugaydi (shop_id yo'q — RLS uchun shu odam konteksti kerak)
        await set_identity_context(db, principal_id=staff.principal_id)
        await db.execute(
            update(AuthSession)
            .where(
                AuthSession.principal_id == staff.principal_id,
                AuthSession.audience == "platform",
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason="STAFF_DISABLED")
        )
        await set_identity_context(db, principal_id=actor.actor_id)
        await revoke_platform_links(db, staff.id, None, now)
        await self.audit.record(
            db,
            action="platform.staff.disabled",
            entity_type=STAFF,
            entity_id=staff.id,
            actor=actor,
            reason=reason,
        )
        return await self._out_one(db, staff)

    # ---------------------------------------------------------------- helpers
    async def _lock_active_admins(self, db: AsyncSession) -> list[UUID]:
        rows = await db.execute(
            select(PlatformStaff.id)
            .where(PlatformStaff.role == ADMIN, PlatformStaff.status == "ACTIVE")
            .order_by(PlatformStaff.id)
            .with_for_update()
        )
        return list(rows.scalars())

    @staticmethod
    def _guard_last_admin(staff: PlatformStaff, active_admins: list[UUID]) -> None:
        if staff.id in active_admins and len(active_admins) <= 1:
            raise LastAdminRequiredError("Platform must keep at least one active admin")

    async def _get(self, db: AsyncSession, staff_id: UUID, for_update: bool = False) -> PlatformStaff:
        staff = await db.get(PlatformStaff, staff_id, with_for_update=for_update)
        if staff is None:
            raise NotFoundError("Platform team member not found")
        return staff

    async def _staff_id_of(self, db: AsyncSession, actor: ActorContext) -> UUID | None:
        return (
            await db.execute(select(PlatformStaff.id).where(PlatformStaff.principal_id == actor.actor_id))
        ).scalar_one_or_none()

    async def _inviter_names(self, db: AsyncSession, staff_ids: Iterable[UUID | None]) -> dict[UUID, str]:
        ids = {i for i in staff_ids if i is not None}
        if not ids:
            return {}
        rows = await db.execute(
            select(PlatformStaff.id, Principal.full_name)
            .join(Principal, Principal.id == PlatformStaff.principal_id)
            .where(PlatformStaff.id.in_(ids))
        )
        return {staff_id: name for staff_id, name in rows}

    async def _out_one(self, db: AsyncSession, staff: PlatformStaff) -> PlatformStaffOut:
        principal = await db.get(Principal, staff.principal_id)
        assert principal is not None
        return self._out(staff, principal, await self._inviter_names(db, [staff.invited_by]))

    @staticmethod
    def _out(staff: PlatformStaff, principal: Principal, names: dict[UUID, str]) -> PlatformStaffOut:
        return PlatformStaffOut(
            id=staff.id,
            principal_id=principal.id,
            full_name=principal.full_name,
            phone=principal.phone,
            role=staff.role,
            status=staff.status,
            last_login_at=principal.last_login_at,
            created_at=staff.created_at,
            invited_by_name=names.get(staff.invited_by) if staff.invited_by else None,
            version=staff.version,
        )
