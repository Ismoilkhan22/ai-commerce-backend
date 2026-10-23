"""Tokenlar (ADR-023, 10 §5.1).

- Access token: JWT, 15 daqiqa, frontend xotirasida. Claim'lar: sub, sid, shop, aud — rollar emas
  (ular har so'rovda bazadan olinadi, TC-025).
- Refresh token: `<session_id>.<tasodifiy sir>`; bazada faqat sir hash'i. Session ID ochiq —
  RLS siyosati uni token tekshirilishidan oldin qatorni ko'rish uchun ishlatadi.
- Havola tokenlari (taklif, parol tiklash): tasodifiy; bazada faqat hash.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import jwt

from app.platform.auth.config import AuthConfig
from app.shared.errors.base import UnauthenticatedError

Audience = Literal["shop", "platform"]
_JWT_AUDIENCE = {"shop": "cos-shop", "platform": "cos-platform"}
_ALGORITHM = "HS256"
_KEY_ID = "v1"


@dataclass(frozen=True)
class AccessClaims:
    principal_id: UUID
    session_id: UUID
    shop_id: UUID | None
    audience: Audience


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def issue_access_token(config: AuthConfig, claims: AccessClaims, now: datetime) -> tuple[str, int]:
    expires = now + config.access_token_ttl
    payload = {
        "iss": config.jwt_issuer,
        "aud": _JWT_AUDIENCE[claims.audience],
        "sub": str(claims.principal_id),
        "sid": str(claims.session_id),
        "shop": str(claims.shop_id) if claims.shop_id else None,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_hex(8),
    }
    token = jwt.encode(payload, config.jwt_secret, algorithm=_ALGORITHM, headers={"kid": _KEY_ID})
    return token, int(config.access_token_ttl.total_seconds())


def decode_access_token(config: AuthConfig, token: str, audience: Audience) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[_ALGORITHM],
            audience=_JWT_AUDIENCE[audience],
            issuer=config.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "sid", "aud", "iss"]},
        )
        return AccessClaims(
            principal_id=UUID(payload["sub"]),
            session_id=UUID(payload["sid"]),
            shop_id=UUID(payload["shop"]) if payload.get("shop") else None,
            audience=audience,
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise UnauthenticatedError("Invalid or expired access token") from exc


def audience_of(config: AuthConfig, token: str) -> Audience:
    """Imzo tekshirilmasdan qaysi panel tokeni ekanini aniqlaydi (keyin decode to'liq tekshiradi)."""
    try:
        aud = jwt.decode(token, options={"verify_signature": False}).get("aud")
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError("Invalid access token") from exc
    for name, value in _JWT_AUDIENCE.items():
        if aud == value:
            return name  # type: ignore[return-value]
    raise UnauthenticatedError("Invalid access token")


def new_refresh_token(session_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    return f"{session_id}.{secret}", hash_token(secret)


def parse_refresh_token(token: str) -> tuple[UUID, str]:
    session_part, _, secret = token.partition(".")
    try:
        return UUID(session_part), hash_token(secret) if secret else ""
    except ValueError as exc:
        raise UnauthenticatedError("Invalid refresh token") from exc


def new_link_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)
