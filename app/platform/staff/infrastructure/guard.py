"""So'rov kim nomidan ekanini aniqlash va ruxsat tekshirish (10 §3, §5).

Har so'rovda: access token → sessiya, odam, a'zolik va shop BAZADAN o'qiladi (rollar tokenda emas).
Shu bilan bir tranzaksiyada RLS konteksti o'rnatiladi va endpoint'ga xuddi shu sessiya beriladi —
shop kontekstisiz tranzaksiya ochilmaydi. scope="function": COMMIT javobdan oldin (12 §4).

    SettingsView = Annotated[RequestContext, Depends(require_permission("shops.settings.view"))]

    @router.get("/branches")
    async def list_branches(ctx: SettingsView): ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.auth.config import AuthConfig
from app.platform.auth.models.orm import AuthSession
from app.platform.auth.tokens import AccessClaims, Audience, audience_of, decode_access_token
from app.platform.shops.models.orm import Shop
from app.platform.staff.models.orm import Membership, MembershipBranch, PlatformStaff, Principal
from app.platform.staff.permissions import PLATFORM_ROLE_PERMISSIONS, PermissionRegistry
from app.shared.clock import utcnow
from app.shared.db.session import Database, set_identity_context
from app.shared.errors.base import ForbiddenError, ShopNotActiveError, UnauthenticatedError
from app.shared.i18n.locale import SUPPORTED_LOCALES, set_locale
from app.shared.types.actor import ActorContext


@dataclass(frozen=True)
class RequestContext:
    actor: ActorContext
    db: AsyncSession


# OpenAPI'da "Bearer" sxemasi (Swagger'dagi Authorize, frontend client). auto_error=False: token yo'q
# bo'lsa xatoni o'zimiz K-07 formatida beramiz.
_bearer_scheme = HTTPBearer(auto_error=False, description="POST /api/v1/auth/login javobidagi access_token")
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


def _token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials.strip():
        raise UnauthenticatedError("Bearer token required")
    return credentials.credentials.strip()


def _bind(request: Request, actor: ActorContext) -> None:
    request.state.actor = actor
    structlog.contextvars.bind_contextvars(
        actor_id=str(actor.actor_id), shop_id=str(actor.shop_id) if actor.shop_id else None
    )
    if actor.locale in SUPPORTED_LOCALES:
        set_locale(actor.locale)  # profil tili Accept-Language'dan ustun (11 §8.2)


async def _active_session(db: AsyncSession, claims: AccessClaims) -> tuple[AuthSession, Principal]:
    row = (
        await db.execute(
            select(AuthSession, Principal)
            .join(Principal, Principal.id == AuthSession.principal_id)
            .where(AuthSession.id == claims.session_id, AuthSession.principal_id == claims.principal_id)
        )
    ).one_or_none()
    if row is None:
        raise UnauthenticatedError("Session not found")
    session, principal = row
    if (
        session.revoked_at is not None
        or session.expires_at <= utcnow()
        or session.audience != claims.audience
        or principal.status != "ACTIVE"
    ):
        raise UnauthenticatedError("Session is not active")
    return session, principal


async def resolve_shop_actor(
    db: AsyncSession, claims: AccessClaims, permissions: PermissionRegistry
) -> ActorContext:
    if claims.shop_id is None:
        raise UnauthenticatedError("Token has no shop")
    await set_identity_context(
        db, shop_id=claims.shop_id, principal_id=claims.principal_id, session_id=claims.session_id
    )
    _, principal = await _active_session(db, claims)
    row = (
        await db.execute(
            select(Membership, Shop)
            .join(Shop, Shop.id == Membership.shop_id)
            .where(Membership.principal_id == principal.id, Membership.shop_id == claims.shop_id)
        )
    ).one_or_none()
    if row is None or row[0].status != "ACTIVE":
        raise UnauthenticatedError("Membership is not active")  # TC-025: o'chirilgan xodim darhol
    membership, shop = row
    if shop.status == "CLOSED":
        raise ShopNotActiveError("Shop is closed")
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
        shop_id=shop.id,
        surface="shop",
        roles=frozenset({membership.role}),
        permissions=permissions.for_role(membership.role),
        branch_ids=branch_ids,
        locale=principal.locale,
        membership_id=membership.id,
    )


async def resolve_platform_actor(db: AsyncSession, claims: AccessClaims) -> ActorContext:
    await set_identity_context(db, principal_id=claims.principal_id, session_id=claims.session_id)
    _, principal = await _active_session(db, claims)
    staff = (
        await db.execute(select(PlatformStaff).where(PlatformStaff.principal_id == principal.id))
    ).scalar_one_or_none()
    if staff is None or staff.status != "ACTIVE":
        raise UnauthenticatedError("Platform access is not active")
    return ActorContext(
        actor_type="PLATFORM",
        actor_id=principal.id,
        shop_id=None,
        surface="platform",
        roles=frozenset({staff.role}),
        permissions=PLATFORM_ROLE_PERMISSIONS.get(staff.role, frozenset()),
        locale=principal.locale,
    )


@asynccontextmanager
async def _context(request: Request, token: str, audience: Audience | None) -> AsyncIterator[RequestContext]:
    # asynccontextmanager: endpoint'dagi xato shu yerga yetib boradi → darhol ROLLBACK, ulanish bo'shaydi
    config: AuthConfig = request.app.state.auth_config
    aud = audience or audience_of(config, token)
    claims = decode_access_token(config, token, aud)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        if aud == "shop":
            actor = await resolve_shop_actor(db, claims, request.app.state.permissions)
        else:
            actor = await resolve_platform_actor(db, claims)
        _bind(request, actor)
        request.state.session_id = claims.session_id
        yield RequestContext(actor=actor, db=db)


async def shop_context(request: Request, credentials: Bearer) -> AsyncIterator[RequestContext]:
    async with _context(request, _token(credentials), "shop") as ctx:
        yield ctx


async def platform_context(request: Request, credentials: Bearer) -> AsyncIterator[RequestContext]:
    async with _context(request, _token(credentials), "platform") as ctx:
        yield ctx


async def any_context(request: Request, credentials: Bearer) -> AsyncIterator[RequestContext]:
    """Ikkala panel uchun umumiy endpoint'lar (/auth/me, parol, sessiyalar)."""
    async with _context(request, _token(credentials), None) as ctx:
        yield ctx


ShopContext = Annotated[RequestContext, Depends(shop_context, scope="function")]
PlatformContext = Annotated[RequestContext, Depends(platform_context, scope="function")]
AnyContext = Annotated[RequestContext, Depends(any_context, scope="function")]


def require_permission(code: str) -> Callable[[RequestContext], Coroutine[Any, Any, RequestContext]]:
    """Shop paneli: rolida shu ruxsat bo'lmasa — 403 (10 §6)."""

    async def dependency(ctx: ShopContext) -> RequestContext:
        if code not in ctx.actor.permissions:
            raise ForbiddenError("Permission denied", permission=code)
        return ctx

    return dependency


def require_platform_permission(code: str) -> Callable[[RequestContext], Coroutine[Any, Any, RequestContext]]:
    async def dependency(ctx: PlatformContext) -> RequestContext:
        if code not in ctx.actor.permissions:
            raise ForbiddenError("Permission denied", permission=code)
        return ctx

    return dependency
