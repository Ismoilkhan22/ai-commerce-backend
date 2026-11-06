"""Auth endpoint'lari (11 §9.1, ADR-023). Rate limit: login 10/daq IP+telefon, 30/daq IP (10 §5.2)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.platform.auth.config import AuthConfig
from app.platform.auth.schemas import (
    ChangePasswordIn,
    LoginIn,
    MeOut,
    MeShop,
    RefreshIn,
    ResetConfirmIn,
    SessionList,
    SessionOut,
    SetPasswordIn,
    TokenOut,
)
from app.platform.auth.services.auth_service import AuthService, IssuedTokens, Outcome
from app.platform.auth.tokens import Audience
from app.platform.shops.models.orm import Shop
from app.platform.staff.infrastructure.guard import AnyContext, RequestContext
from app.platform.staff.infrastructure.providers import auth_service
from app.platform.staff.models.orm import Principal
from app.shared.client_ip import client_ip
from app.shared.db.session import Database
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(tags=["auth"])

# Har panelning o'z cookie'si: bitta brauzerda shop paneli va platforma paneli bir-birining
# sessiyasini almashtirib yubormaydi. Cookie faqat refresh manziliga yuboriladi (10 §5.1).
REFRESH_COOKIES: dict[Audience, str] = {"shop": "cos_refresh_shop", "platform": "cos_refresh_platform"}
REFRESH_PATH = "/api/v1/auth/refresh"

Auth = Annotated[AuthService, Depends(auth_service)]


def _ip(request: Request) -> str:
    return client_ip(request)  # XFF faqat ishonchli proksidan (TRUSTED_PROXIES)


def _limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


def _issue(response: Response, request: Request, tokens: IssuedTokens) -> TokenOut:
    config: AuthConfig = request.app.state.auth_config
    response.set_cookie(
        REFRESH_COOKIES[tokens.audience],
        tokens.refresh_token,
        max_age=int(config.refresh_token_ttl.total_seconds()),
        path=REFRESH_PATH,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in, audience=tokens.audience)


def _clear_cookie(response: Response, request: Request, audience: Audience) -> None:
    config: AuthConfig = request.app.state.auth_config
    response.delete_cookie(
        REFRESH_COOKIES[audience],
        path=REFRESH_PATH,
        secure=config.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _surface(ctx: RequestContext) -> Audience:
    return "platform" if ctx.actor.actor_type == "PLATFORM" else "shop"


def _raise_after_commit(outcome: Outcome) -> IssuedTokens:
    if outcome.error is not None:
        raise outcome.error
    assert outcome.tokens is not None
    return outcome.tokens


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, svc: Auth) -> TokenOut:
    limiter = _limiter(request)
    await enforce(limiter, f"login-ip:{_ip(request)}", limit=30)
    await enforce(limiter, f"login:{_ip(request)}:{body.phone}", limit=10)
    database: Database = request.app.state.db
    async with database.transaction() as db:  # xato urinish hisoblagichi COMMIT bo'lishi uchun
        outcome = await svc.login(
            db, body.phone, body.password, body.audience, request.headers.get("user-agent")
        )
    return _issue(response, request, _raise_after_commit(outcome))


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, request: Request, response: Response, svc: Auth) -> TokenOut:
    await enforce(_limiter(request), f"refresh:{_ip(request)}", limit=60)
    database: Database = request.app.state.db
    async with (
        database.transaction() as db
    ):  # qayta ishlatish aniqlansa — oila bekor qilinishi COMMIT bo'ladi
        refresh_token = request.cookies.get(REFRESH_COOKIES[body.audience])
        outcome = await svc.refresh(db, refresh_token, body.audience, request.headers.get("user-agent"))
    if outcome.error is not None:
        _clear_cookie(response, request, body.audience)
    return _issue(response, request, _raise_after_commit(outcome))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, ctx: AnyContext, svc: Auth) -> None:
    await svc.logout(ctx.db, ctx.actor, request.state.session_id)
    _clear_cookie(response, request, _surface(ctx))


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(request: Request, response: Response, ctx: AnyContext, svc: Auth) -> None:
    await svc.logout_all(ctx.db, ctx.actor)
    _clear_cookie(response, request, _surface(ctx))


@router.get("/me", response_model=MeOut)
async def me(ctx: AnyContext) -> MeOut:
    actor = ctx.actor
    principal = await ctx.db.get(Principal, actor.actor_id)
    assert principal is not None
    shop = await ctx.db.get(Shop, actor.shop_id) if actor.shop_id else None
    return MeOut(
        principal_id=principal.id,
        full_name=principal.full_name,
        phone=principal.phone,
        locale=principal.locale,
        audience="platform" if actor.actor_type == "PLATFORM" else "shop",
        role=next(iter(actor.roles)),
        permissions=sorted(actor.permissions),
        shop=MeShop(id=shop.id, slug=shop.slug, name=shop.name, status=shop.status) if shop else None,
        branch_ids=sorted(actor.branch_ids) if actor.branch_ids is not None else None,
        membership_id=actor.membership_id,
    )


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordIn, request: Request, ctx: AnyContext, svc: Auth) -> None:
    await svc.change_password(
        ctx.db, ctx.actor, request.state.session_id, body.current_password, body.new_password
    )


@router.post("/invites/{token}/accept", response_model=TokenOut)
async def accept_invite(
    token: str, body: SetPasswordIn, request: Request, response: Response, svc: Auth
) -> TokenOut:
    await enforce(_limiter(request), f"link:{_ip(request)}", limit=10)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        tokens = await svc.accept_invite(db, token, body.password, request.headers.get("user-agent"))
    return _issue(response, request, tokens)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(body: ResetConfirmIn, request: Request, svc: Auth) -> None:
    await enforce(_limiter(request), f"link:{_ip(request)}", limit=10)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        await svc.confirm_password_reset(db, body.token, body.password)


@router.post("/platform-invites/{token}/accept", response_model=TokenOut)
async def accept_platform_invite(
    token: str, body: SetPasswordIn, request: Request, response: Response, svc: Auth
) -> TokenOut:
    """Platforma jamoasiga taklif (business/15 §5): parol o'rnatiladi, platforma paneliga kiriladi."""
    await enforce(_limiter(request), f"link:{_ip(request)}", limit=10)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        tokens = await svc.accept_platform_invite(db, token, body.password, request.headers.get("user-agent"))
    return _issue(response, request, tokens)


@router.post("/platform-password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_platform_password_reset(body: ResetConfirmIn, request: Request, svc: Auth) -> None:
    await enforce(_limiter(request), f"link:{_ip(request)}", limit=10)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        await svc.confirm_platform_password_reset(db, body.token, body.password)


@router.get("/sessions", response_model=SessionList)
async def list_sessions(request: Request, ctx: AnyContext, svc: Auth) -> SessionList:
    current = request.state.session_id
    sessions = await svc.list_sessions(ctx.db, ctx.actor)
    return SessionList(
        items=[
            SessionOut(
                id=s.id,
                user_agent=s.user_agent,
                created_at=s.created_at,
                last_used_at=s.last_used_at,
                current=s.id == current,
            )
            for s in sessions
        ]
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: UUID, ctx: AnyContext, svc: Auth) -> None:
    await svc.revoke_session(ctx.db, ctx.actor, session_id)
