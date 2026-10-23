"""Bir martalik havolalar: xodim taklifi (72 soat) va parolni tiklash (24 soat) — DEC-131.

Havolani ega (yoki platforma admini) o'zi nusxalab yuboradi. Bazada tokenning faqat hash'i saqlanadi.
Yangi havola berilganda shu a'zolikning shu turdagi eski havolalari bekor qilinadi — faqat oxirgisi ishlaydi.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.auth.tokens import hash_token, new_link_token
from app.platform.staff.models.orm import Invitation
from app.shared.clock import utcnow
from app.shared.errors.base import NotFoundError

Purpose = Literal["INVITE", "PASSWORD_RESET"]
_PATHS: dict[str, str] = {"INVITE": "invite", "PASSWORD_RESET": "reset-password"}


async def issue_link(
    db: AsyncSession,
    *,
    shop_id: UUID,
    membership_id: UUID,
    purpose: Purpose,
    ttl: timedelta,
    app_url: str,
) -> tuple[str, datetime]:
    now = utcnow()
    await revoke_links(db, membership_id, purpose, now)
    token, token_hash = new_link_token()
    expires_at = now + ttl
    db.add(
        Invitation(
            shop_id=shop_id,
            membership_id=membership_id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return f"{app_url}/{_PATHS[purpose]}/{token}", expires_at


async def revoke_links(db: AsyncSession, membership_id: UUID, purpose: Purpose | None, now: datetime) -> None:
    condition = (Invitation.membership_id == membership_id) & Invitation.accepted_at.is_(None)
    if purpose is not None:
        condition &= Invitation.purpose == purpose
    await db.execute(
        update(Invitation).where(condition, Invitation.revoked_at.is_(None)).values(revoked_at=now)
    )


async def find_valid_link(db: AsyncSession, token: str, purpose: Purpose) -> Invitation:
    """Yaroqsiz, ishlatilgan, bekor qilingan yoki muddati o'tgan — hammasi 404, sababi `details.reason` da."""
    invitation = (
        await db.execute(
            select(Invitation).where(Invitation.token_hash == hash_token(token)).with_for_update()
        )
    ).scalar_one_or_none()
    if invitation is None or invitation.purpose != purpose:
        raise NotFoundError("Link not found", reason="invalid")
    if invitation.accepted_at is not None:
        raise NotFoundError("Link already used", reason="used")
    if invitation.revoked_at is not None:
        raise NotFoundError("Link revoked", reason="revoked")
    if invitation.expires_at <= utcnow():
        raise NotFoundError("Link expired", reason="expired")
    return invitation
