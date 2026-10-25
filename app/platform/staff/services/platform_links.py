"""Platforma jamoasiga bir martalik havolalar: taklif (72 soat) va parolni tiklash (24 soat) — business/15 §5.

Shop xodimi havolalari (`links.py`) bilan bir xil ishlaydi: bazada faqat hash, yangi havola berilganda
eskilari bekor qilinadi. Havola platforma paneli manziliga olib boradi.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.auth.tokens import hash_token, new_link_token
from app.platform.staff.models.orm import PlatformStaffInvitation
from app.platform.staff.services.links import Purpose
from app.shared.clock import utcnow
from app.shared.errors.base import NotFoundError

_PATHS: dict[str, str] = {"INVITE": "invite", "PASSWORD_RESET": "reset-password"}


async def issue_platform_link(
    db: AsyncSession,
    *,
    staff_id: UUID,
    purpose: Purpose,
    ttl: timedelta,
    app_url: str,
    created_by: UUID | None,
) -> tuple[str, datetime]:
    now = utcnow()
    await revoke_platform_links(db, staff_id, purpose, now)
    token, token_hash = new_link_token()
    expires_at = now + ttl
    db.add(
        PlatformStaffInvitation(
            platform_staff_id=staff_id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by=created_by,
        )
    )
    await db.flush()
    return f"{app_url}/{_PATHS[purpose]}/{token}", expires_at


async def revoke_platform_links(
    db: AsyncSession, staff_id: UUID, purpose: Purpose | None, now: datetime
) -> None:
    condition = (
        PlatformStaffInvitation.platform_staff_id == staff_id
    ) & PlatformStaffInvitation.accepted_at.is_(None)
    if purpose is not None:
        condition &= PlatformStaffInvitation.purpose == purpose
    await db.execute(
        update(PlatformStaffInvitation)
        .where(condition, PlatformStaffInvitation.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def find_valid_platform_link(db: AsyncSession, token: str, purpose: Purpose) -> PlatformStaffInvitation:
    """Yaroqsiz, ishlatilgan, bekor qilingan yoki muddati o'tgan — 404, sababi `details.reason` da."""
    invitation = (
        await db.execute(
            select(PlatformStaffInvitation)
            .where(PlatformStaffInvitation.token_hash == hash_token(token))
            .with_for_update()
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
