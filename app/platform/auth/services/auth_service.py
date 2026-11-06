"""Auth: kirish, token yangilash, chiqish, parol, taklifni qabul qilish, parolni tiklash (ADR-023, 10 §5).

Muhim: xato parol hisoblagichi va "eski refresh token qayta ishlatildi" holatida oilani bekor qilish
bazaga YOZILISHI kerak, garchi so'rov xato bilan tugasa ham. Shuning uchun bu metodlar xatoni
tashlamaydi, `Outcome` qaytaradi: endpoint tranzaksiyani COMMIT qiladi, keyin xatoni tashlaydi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.config import AuthConfig
from app.platform.auth.models.orm import AuthSession
from app.platform.auth.passwords import PasswordHasher, validate_new_password
from app.platform.auth.tokens import (
    AccessClaims,
    Audience,
    issue_access_token,
    new_refresh_token,
    parse_refresh_token,
)
from app.platform.shops.models.orm import Shop
from app.platform.staff.models.orm import Membership, PlatformStaff, Principal
from app.platform.staff.services.links import find_valid_link
from app.platform.staff.services.platform_links import find_valid_platform_link
from app.platform.staff.state_machine import ENTITY as MEMBERSHIP
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.db.ids import uuid7
from app.shared.db.session import set_identity_context
from app.shared.errors.base import (
    DomainError,
    NotFoundError,
    RateLimitedError,
    ShopNotActiveError,
    UnauthenticatedError,
    ValidationError,
)
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

INVALID_CREDENTIALS = "Invalid phone or password"


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    audience: Audience


@dataclass(frozen=True)
class Outcome:
    """Natija yoki COMMIT'dan keyin tashlanadigan xato."""

    tokens: IssuedTokens | None = None
    error: DomainError | None = None


def _actor(principal_id: UUID, shop_id: UUID | None, audience: Audience) -> ActorContext:
    return ActorContext(
        actor_type="PLATFORM" if audience == "platform" else "STAFF",
        actor_id=principal_id,
        shop_id=shop_id,
        surface="platform" if audience == "platform" else "shop",
    )


class AuthService:
    def __init__(
        self, config: AuthConfig, hasher: PasswordHasher, audit: AuditService, use: UseService
    ) -> None:
        self.config = config
        self.hasher = hasher
        self.audit = audit
        self.use = use

    # ------------------------------------------------------------------ login
    async def login(
        self, db: AsyncSession, phone: str, password: str, audience: Audience, user_agent: str | None
    ) -> Outcome:
        try:
            normalized = normalize_phone(phone)
        except ValidationError:
            await self.hasher.verify(None, password)
            return Outcome(error=UnauthenticatedError(INVALID_CREDENTIALS))
        principal = (
            await db.execute(select(Principal).where(Principal.phone == normalized).with_for_update())
        ).scalar_one_or_none()
        now = utcnow()
        if principal is None or principal.status != "ACTIVE":
            await self.hasher.verify(None, password)  # vaqt bo'yicha farq qilmasin
            return Outcome(error=UnauthenticatedError(INVALID_CREDENTIALS))
        if principal.locked_until and principal.locked_until > now:
            retry = int((principal.locked_until - now).total_seconds()) + 1
            return Outcome(error=RateLimitedError("Account temporarily locked", retry_after_seconds=retry))

        if not await self.hasher.verify(principal.password_hash, password):
            principal.failed_login_attempts += 1
            if principal.failed_login_attempts >= self.config.login_max_failures:
                principal.locked_until = now + self.config.login_lockout
                principal.failed_login_attempts = 0
            await self.audit.record(
                db,
                action="auth.login.failed",
                entity_type="platform.principal",
                entity_id=principal.id,
                actor=_actor(principal.id, None, audience),
            )
            return Outcome(error=UnauthenticatedError(INVALID_CREDENTIALS))

        await set_identity_context(db, principal_id=principal.id)
        shop_id: UUID | None = None
        if audience == "shop":
            membership = (
                await db.execute(select(Membership).where(Membership.principal_id == principal.id))
            ).scalar_one_or_none()
            if membership is None or membership.status != "ACTIVE":
                return Outcome(error=UnauthenticatedError(INVALID_CREDENTIALS))
            shop = await db.get(Shop, membership.shop_id)
            if shop is None or shop.status == "CLOSED":
                return Outcome(error=ShopNotActiveError("Shop is closed", shop_status="CLOSED"))
            shop_id = membership.shop_id
        else:
            staff = (
                await db.execute(select(PlatformStaff).where(PlatformStaff.principal_id == principal.id))
            ).scalar_one_or_none()
            if staff is None or staff.status != "ACTIVE":
                return Outcome(error=UnauthenticatedError(INVALID_CREDENTIALS))

        principal.failed_login_attempts = 0
        principal.locked_until = None
        principal.last_login_at = now
        if principal.password_hash and self.hasher.needs_rehash(principal.password_hash):
            principal.password_hash = await self.hasher.hash(password)
        tokens = await self._open_session(db, principal.id, shop_id, audience, uuid7(), user_agent, now)
        await self.audit.record(
            db,
            action="auth.login.succeeded",
            entity_type="platform.principal",
            entity_id=principal.id,
            actor=_actor(principal.id, shop_id, audience),
        )
        return Outcome(tokens=tokens)

    # ---------------------------------------------------------------- refresh
    async def refresh(
        self, db: AsyncSession, refresh_token: str | None, audience: Audience, user_agent: str | None
    ) -> Outcome:
        if not refresh_token:
            return Outcome(error=UnauthenticatedError("Refresh token required"))
        try:
            session_id, secret_hash = parse_refresh_token(refresh_token)
        except UnauthenticatedError as exc:
            return Outcome(error=exc)
        await set_identity_context(db, session_id=session_id)
        session = (
            await db.execute(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
        ).scalar_one_or_none()
        if session is None or session.refresh_token_hash != secret_hash or session.audience != audience:
            return Outcome(error=UnauthenticatedError("Invalid refresh token"))
        now = utcnow()
        await set_identity_context(db, principal_id=session.principal_id)
        if session.revoked_at is not None:
            if session.revoked_reason == "ROTATED":
                # Almashtirilgan token qayta ishlatildi — o'g'irlangan bo'lishi mumkin: butun oila bekor
                await self._revoke(db, AuthSession.family_id == session.family_id, "REUSE_DETECTED", now)
                await self.audit.record(
                    db,
                    action="auth.refresh.reuse_detected",
                    entity_type="platform.session",
                    entity_id=session.family_id,
                    actor=_actor(session.principal_id, session.shop_id, session.audience),
                )
                logger.warning("auth.refresh_reuse_detected", family_id=str(session.family_id))
            if session.revoked_reason == "SHOP_CLOSED":
                return Outcome(error=ShopNotActiveError("Shop is closed", shop_status="CLOSED"))
            return Outcome(error=UnauthenticatedError("Refresh token is no longer valid"))
        if session.expires_at <= now:
            return Outcome(error=UnauthenticatedError("Refresh token expired"))
        if not await self._still_allowed(db, session):
            await self._revoke(db, AuthSession.id == session.id, "ACCESS_REVOKED", now)
            return Outcome(error=UnauthenticatedError("Access revoked"))

        session.revoked_at, session.revoked_reason, session.last_used_at = now, "ROTATED", now
        tokens = await self._open_session(
            db, session.principal_id, session.shop_id, audience, session.family_id, user_agent, now
        )
        return Outcome(tokens=tokens)

    async def _still_allowed(self, db: AsyncSession, session: AuthSession) -> bool:
        principal = await db.get(Principal, session.principal_id)
        if principal is None or principal.status != "ACTIVE":
            return False
        if session.audience == "platform":
            staff = (
                await db.execute(select(PlatformStaff).where(PlatformStaff.principal_id == principal.id))
            ).scalar_one_or_none()
            return staff is not None and staff.status == "ACTIVE"
        await set_identity_context(db, shop_id=session.shop_id)
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.principal_id == principal.id, Membership.shop_id == session.shop_id
                )
            )
        ).scalar_one_or_none()
        shop = await db.get(Shop, session.shop_id) if session.shop_id else None
        return (
            membership is not None
            and membership.status == "ACTIVE"
            and shop is not None
            and shop.status != "CLOSED"
        )

    # ----------------------------------------------------------------- logout
    async def logout(self, db: AsyncSession, actor: ActorContext, session_id: UUID) -> None:
        await self._revoke(db, AuthSession.id == session_id, "LOGOUT", utcnow())
        await self._audit_principal(db, "auth.logout", actor)

    async def logout_all(self, db: AsyncSession, actor: ActorContext) -> None:
        await self._revoke(db, AuthSession.principal_id == actor.actor_id, "LOGOUT_ALL", utcnow())
        await self._audit_principal(db, "auth.logout_all", actor)

    async def list_sessions(self, db: AsyncSession, actor: ActorContext) -> list[AuthSession]:
        result = await db.execute(
            select(AuthSession)
            .where(
                AuthSession.principal_id == actor.actor_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
            .order_by(AuthSession.created_at.desc())
        )
        return list(result.scalars())

    async def revoke_session(self, db: AsyncSession, actor: ActorContext, session_id: UUID) -> None:
        session = await db.get(AuthSession, session_id)
        if session is None or session.principal_id != actor.actor_id or session.revoked_at is not None:
            raise NotFoundError("Session not found")
        await self._revoke(db, AuthSession.id == session_id, "REVOKED_BY_USER", utcnow())
        await self._audit_principal(db, "auth.session.revoked", actor)

    # --------------------------------------------------------------- password
    async def change_password(
        self, db: AsyncSession, actor: ActorContext, current_session_id: UUID, current: str, new: str
    ) -> None:
        principal = await db.get(Principal, actor.actor_id, with_for_update=True)
        assert principal is not None
        if not await self.hasher.verify(principal.password_hash, current):
            raise ValidationError(
                "Current password is wrong",
                fields=[{"field": "current_password", "code": "invalid", "params": {}}],
            )
        if new == current:
            raise ValidationError(
                "New password equals the current one",
                fields=[{"field": "new_password", "code": "same_as_current", "params": {}}],
            )
        validate_new_password(new, principal.phone, field="new_password")
        now = utcnow()
        principal.password_hash = await self.hasher.hash(new)
        principal.password_changed_at = now
        # Boshqa qurilmalardagi sessiyalar tugaydi; joriy sessiya qoladi
        await self._revoke(
            db,
            (AuthSession.principal_id == principal.id) & (AuthSession.id != current_session_id),
            "PASSWORD_CHANGED",
            now,
        )
        await self._audit_principal(db, "auth.password.changed", actor)

    async def accept_invite(
        self, db: AsyncSession, token: str, password: str, user_agent: str | None
    ) -> IssuedTokens:
        invitation = await find_valid_link(db, token, "INVITE")
        await set_identity_context(db, shop_id=invitation.shop_id)
        membership = await db.get(Membership, invitation.membership_id, with_for_update=True)
        if membership is None or membership.status != "INVITED":
            raise NotFoundError("Invitation is no longer valid", reason="used")
        principal = await db.get(Principal, membership.principal_id, with_for_update=True)
        assert principal is not None
        validate_new_password(password, principal.phone)
        actor = _actor(principal.id, membership.shop_id, "shop")
        rule = self.use.validate_transition(MEMBERSHIP, membership.status, "ACTIVE", "ACCEPT_INVITE", actor)

        now = utcnow()
        principal.password_hash = await self.hasher.hash(password)
        principal.phone_verified_at = now  # havola shu telefonga berilgan
        principal.last_login_at = now  # taklifni qabul qilish — birinchi kirish
        principal.failed_login_attempts, principal.locked_until = 0, None
        membership.status, membership.activated_at = "ACTIVE", now
        invitation.accepted_at = now
        await self.use.log_transition(db, entity_id=membership.id, rule=rule, actor=actor)
        await self.audit.record(
            db, action="staff.member.joined", entity_type=MEMBERSHIP, entity_id=membership.id, actor=actor
        )
        await set_identity_context(db, principal_id=principal.id)
        return await self._open_session(
            db, principal.id, membership.shop_id, "shop", uuid7(), user_agent, now
        )

    async def confirm_password_reset(self, db: AsyncSession, token: str, password: str) -> None:
        invitation = await find_valid_link(db, token, "PASSWORD_RESET")
        await set_identity_context(db, shop_id=invitation.shop_id)
        membership = await db.get(Membership, invitation.membership_id)
        if membership is None or membership.status != "ACTIVE":
            raise NotFoundError("Reset link is no longer valid", reason="used")
        principal = await db.get(Principal, membership.principal_id, with_for_update=True)
        assert principal is not None
        validate_new_password(password, principal.phone)
        now = utcnow()
        principal.password_hash = await self.hasher.hash(password)
        principal.password_changed_at = now
        principal.failed_login_attempts, principal.locked_until = 0, None
        invitation.accepted_at = now
        await set_identity_context(db, principal_id=principal.id)
        await self._revoke(db, AuthSession.principal_id == principal.id, "PASSWORD_RESET", now)
        await self.audit.record(
            db,
            action="auth.password.reset",
            entity_type="platform.principal",
            entity_id=principal.id,
            actor=_actor(principal.id, membership.shop_id, "shop"),
        )

    # ------------------------------------------------- platforma jamoasi havolalari
    async def accept_platform_invite(
        self, db: AsyncSession, token: str, password: str, user_agent: str | None
    ) -> IssuedTokens:
        """Platforma jamoasiga taklif: parol o'rnatiladi, a'zo ACTIVE bo'ladi va platforma paneliga kiradi."""
        invitation = await find_valid_platform_link(db, token, "INVITE")
        staff = await db.get(PlatformStaff, invitation.platform_staff_id, with_for_update=True)
        if staff is None or staff.status != "INVITED":
            raise NotFoundError("Invitation is no longer valid", reason="used")
        principal = await db.get(Principal, staff.principal_id, with_for_update=True)
        assert principal is not None
        validate_new_password(password, principal.phone)
        now = utcnow()
        principal.password_hash = await self.hasher.hash(password)
        principal.phone_verified_at = now  # havola shu telefonga berilgan
        principal.last_login_at = now  # taklifni qabul qilish — birinchi kirish
        principal.failed_login_attempts, principal.locked_until = 0, None
        staff.status = "ACTIVE"
        invitation.accepted_at = now
        actor = _actor(principal.id, None, "platform")
        await self.audit.record(
            db,
            action="platform.staff.joined",
            entity_type="platform.platform_staff",
            entity_id=staff.id,
            actor=actor,
        )
        await set_identity_context(db, principal_id=principal.id)
        return await self._open_session(db, principal.id, None, "platform", uuid7(), user_agent, now)

    async def confirm_platform_password_reset(self, db: AsyncSession, token: str, password: str) -> None:
        invitation = await find_valid_platform_link(db, token, "PASSWORD_RESET")
        staff = await db.get(PlatformStaff, invitation.platform_staff_id)
        if staff is None or staff.status != "ACTIVE":
            raise NotFoundError("Reset link is no longer valid", reason="used")
        principal = await db.get(Principal, staff.principal_id, with_for_update=True)
        assert principal is not None
        validate_new_password(password, principal.phone)
        now = utcnow()
        principal.password_hash = await self.hasher.hash(password)
        principal.password_changed_at = now
        principal.failed_login_attempts, principal.locked_until = 0, None
        invitation.accepted_at = now
        await set_identity_context(db, principal_id=principal.id)
        await self._revoke(db, AuthSession.principal_id == principal.id, "PASSWORD_RESET", now)
        await self.audit.record(
            db,
            action="auth.password.reset",
            entity_type="platform.principal",
            entity_id=principal.id,
            actor=_actor(principal.id, None, "platform"),
        )

    # ---------------------------------------------------------------- helpers
    async def open_shop_session(
        self, db: AsyncSession, principal_id: UUID, shop_id: UUID, user_agent: str | None
    ) -> IssuedTokens:
        """Yangi shop egasi uchun birinchi sessiya (M21: o'zi ro'yxatdan o'tgandan keyin)."""
        return await self._open_session(db, principal_id, shop_id, "shop", uuid7(), user_agent, utcnow())

    async def _open_session(
        self,
        db: AsyncSession,
        principal_id: UUID,
        shop_id: UUID | None,
        audience: Audience,
        family_id: UUID,
        user_agent: str | None,
        now: datetime,
    ) -> IssuedTokens:
        session_id = uuid7()
        refresh_token, refresh_hash = new_refresh_token(session_id)
        db.add(
            AuthSession(
                id=session_id,
                principal_id=principal_id,
                shop_id=shop_id,
                audience=audience,
                family_id=family_id,
                refresh_token_hash=refresh_hash,
                expires_at=now + self.config.refresh_token_ttl,
                user_agent=(user_agent or "")[:300] or None,
                last_used_at=now,
            )
        )
        await db.flush()
        access, expires_in = issue_access_token(
            self.config, AccessClaims(principal_id, session_id, shop_id, audience), now
        )
        return IssuedTokens(
            access_token=access, expires_in=expires_in, refresh_token=refresh_token, audience=audience
        )

    async def _revoke(self, db: AsyncSession, condition: object, reason: str, now: datetime) -> None:
        await db.execute(
            update(AuthSession)
            .where(condition, AuthSession.revoked_at.is_(None))  # type: ignore[arg-type]
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def _audit_principal(self, db: AsyncSession, action: str, actor: ActorContext) -> None:
        await self.audit.record(
            db, action=action, entity_type="platform.principal", entity_id=actor.actor_id, actor=actor
        )
