"""M21: shopning o'zi ro'yxatdan o'tishi — ochiq endpoint'lar (`FEATURE_SELF_SIGNUP`).

Limitlar: kod yuborish — IP bo'yicha 10/soat, telefon bo'yicha 3/10 daqiqa; tasdiqlash — IP 30/soat;
yakunlash — IP 10/soat. Xizmat ichida: qayta yuborish 60 soniya, telefonga 5 so'rov/kun, 5 urinish.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.platform.auth.api.routes import _issue
from app.platform.auth.schemas import TokenOut
from app.platform.shops.services.signup_service import (
    SignupCompleteIn,
    SignupService,
    SignupStartIn,
    SignupStartOut,
    SignupVerifyIn,
    SignupVerifyOut,
)
from app.shared.client_ip import client_ip
from app.shared.db.session import Database
from app.shared.errors.base import ValidationError
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(prefix="/signup", tags=["signup"])
HOUR = 3600


def _svc(request: Request) -> SignupService:
    return request.app.state.signup  # type: ignore[no-any-return]


def _limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


class SignupStatusOut(BaseModel):
    enabled: bool


@router.get("/status", response_model=SignupStatusOut)
async def signup_status(request: Request) -> SignupStatusOut:
    """Kirish sahifasi "Do'kon ochish" havolasini ko'rsatadimi."""
    return SignupStatusOut(enabled=_svc(request).config.enabled)


@router.post("/start", response_model=SignupStartOut, status_code=202)
async def signup_start(body: SignupStartIn, request: Request) -> SignupStartOut:
    ip = client_ip(request)
    await enforce(_limiter(request), f"signup-ip:{ip}", limit=10, window_seconds=HOUR)
    await enforce(_limiter(request), f"signup-phone:{body.phone}", limit=3, window_seconds=600)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        return await _svc(request).start(db, body.phone, ip)


@router.post("/verify", response_model=SignupVerifyOut)
async def signup_verify(body: SignupVerifyIn, request: Request) -> SignupVerifyOut:
    await enforce(_limiter(request), f"signup-verify:{client_ip(request)}", limit=30, window_seconds=HOUR)
    database: Database = request.app.state.db
    async with database.transaction() as db:  # noto'g'ri urinish hisoblagichi COMMIT bo'lishi uchun
        result = await _svc(request).verify(db, body.request_id, body.code)
    if isinstance(result, ValidationError):
        raise result
    return result


@router.post("/complete", response_model=TokenOut, status_code=201)
async def signup_complete(body: SignupCompleteIn, request: Request, response: Response) -> TokenOut:
    await enforce(_limiter(request), f"signup-complete:{client_ip(request)}", limit=10, window_seconds=HOUR)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        tokens = await _svc(request).complete(db, body, request.headers.get("user-agent"))
    return _issue(response, request, tokens)
