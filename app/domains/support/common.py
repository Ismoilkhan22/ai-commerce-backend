"""support ichidagi umumiy yordamchilar: filial, xodim nomlari, kafolat hisobi, cursor (11 §4.1)."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.shops.models.orm import Branch, Shop
from app.platform.staff.models.orm import Membership, Principal
from app.shared.errors.base import BranchClosedError, ForbiddenError, ValidationError
from app.shared.pagination import decode_cursor, encode_cursor
from app.shared.text import NUL
from app.shared.types.actor import ActorContext

AUTO_CLOSE_DAYS = 7  # RESOLVED dan keyin (FSM-11: "muddat o'tdi")
MAX_ATTACHMENTS = 10


def field(field: str, code: str, **params: object) -> dict[str, Any]:
    return {"field": field, "code": code, "params": params}


def in_branch_scope(actor: ActorContext, branch_id: UUID | None) -> bool:
    """`branch_ids` None — hamma filial."""
    return actor.branch_ids is None or branch_id is None or branch_id in actor.branch_ids


def ensure_branch_scope(actor: ActorContext, branch_id: UUID | None) -> None:
    if not in_branch_scope(actor, branch_id):
        raise ForbiddenError("Branch is outside your scope", branch_id=branch_id)


async def load_branch(db: AsyncSession, actor: ActorContext, branch_id: UUID) -> Branch:
    """Shu shopning ochiq filiali; yo'q yoki boshqa shopniki — maydon xatosi; yopiq — BRANCH_CLOSED."""
    branch = (
        await db.execute(select(Branch).where(Branch.id == branch_id, Branch.shop_id == actor.shop_id))
    ).scalar_one_or_none()
    if branch is None:
        raise ValidationError("Branch not found", fields=[field("branch_id", "invalid")])
    if branch.status != "ACTIVE":
        raise BranchClosedError("Branch is closed", branch_id=branch_id)
    ensure_branch_scope(actor, branch.id)
    return branch


async def branch_names(db: AsyncSession, shop_id: UUID | None, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted or shop_id is None:
        return {}
    rows = await db.execute(
        select(Branch.id, Branch.name).where(Branch.shop_id == shop_id, Branch.id.in_(wanted))
    )
    return {branch_id: name for branch_id, name in rows}


async def member_names(db: AsyncSession, shop_id: UUID | None, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    """platform.memberships.id → xodim ismi."""
    wanted = {i for i in ids if i is not None}
    if not wanted or shop_id is None:
        return {}
    rows = await db.execute(
        select(Membership.id, Principal.full_name)
        .join(Principal, Principal.id == Membership.principal_id)
        .where(Membership.shop_id == shop_id, Membership.id.in_(wanted))
    )
    return {membership_id: name for membership_id, name in rows}


# ------------------------------------------------------------------ kafolat hisobi (BL-057)


async def shop_zone(db: AsyncSession, shop_id: UUID) -> ZoneInfo:
    name = await db.scalar(select(Shop.timezone).where(Shop.id == shop_id))
    try:
        return ZoneInfo(name or "Asia/Tashkent")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Tashkent")


def add_months(start: date, months: int) -> date:
    """Oy oxirida qisqartiriladi: 31 yanvar + 1 oy = 28/29 fevral."""
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def warranty_window(
    sold_at: datetime, months: int | None, zone: ZoneInfo, now: datetime
) -> tuple[date | None, bool]:
    """(`warranty_until`, `within_warranty`): `sold_at + oylar`, shop zonasida; kafolat yo'q — (None, False).
    Oxirgi kun ham kafolat ichida."""
    if months is None:
        return None, False
    until = add_months(sold_at.astimezone(zone).date(), months)
    return until, now.astimezone(zone).date() <= until


# ------------------------------------------------------------------ cursor


def _bad_cursor() -> ValidationError:
    return ValidationError("Cursor is invalid", fields=[field("cursor", "invalid_format")])


def read_cursor(cursor: str) -> tuple[datetime, UUID]:
    raw = decode_cursor(cursor)
    t, i = raw.get("t"), raw.get("id")
    if raw.get("k") != "case" or not isinstance(t, str) or not isinstance(i, str) or NUL in t + i:
        raise _bad_cursor()
    try:
        moment, ident = datetime.fromisoformat(t), UUID(i)
    except ValueError as exc:
        raise _bad_cursor() from exc
    if moment.tzinfo is None or moment.year < 2000:
        raise _bad_cursor()
    return moment, ident


def make_cursor(created_at: datetime, case_id: UUID) -> str:
    return encode_cursor({"k": "case", "t": created_at.isoformat(), "id": str(case_id)})
