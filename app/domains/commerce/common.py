"""commerce ichidagi umumiy yordamchilar: filial, shop siyosati, xodim nomlari, filial doirasi (10 §6.8)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.shops.models.orm import Branch, ShopPolicy
from app.platform.staff.models.orm import Membership, Principal
from app.shared.errors.base import BranchClosedError, ForbiddenError, ValidationError
from app.shared.pagination import decode_cursor, encode_cursor
from app.shared.text import NUL
from app.shared.types.actor import ActorContext

RESERVATION_REVIEW_HOURS = 72  # DEC-104: "bekor qilinsinmi?" — tasdiqdan 72 soat (shop sozlamasi keyin)
STALE_RATE_HOURS = 72  # catalog.md §7 bilan bir xil


def field(field: str, code: str, **params: object) -> dict[str, Any]:
    return {"field": field, "code": code, "params": params}


@dataclass(frozen=True)
class Policy:
    discount_limit_sales_pct: Decimal
    discount_limit_manager_pct: Decimal
    unconfirmed_after_hours: int  # birinchi eslatma (order_reminder_hours[0], DEC-104)
    low_stock_threshold: int
    stock_display: str


DEFAULT_POLICY = Policy(Decimal(0), Decimal(5), 24, 2, "STATUS_ONLY")
UNLIMITED = Decimal(100)


def discount_limit(actor: ActorContext, policy: Policy) -> Decimal:
    """Shu xodim tasdiqsiz bera oladigan eng katta chegirma (DEC-110): ega — cheksiz."""
    if "OWNER" in actor.roles:
        return UNLIMITED
    if "MANAGER" in actor.roles:
        return policy.discount_limit_manager_pct
    if "SALES" in actor.roles:
        return policy.discount_limit_sales_pct
    return Decimal(0)


async def load_policy(db: AsyncSession, shop_id: UUID) -> Policy:
    row = await db.get(ShopPolicy, shop_id)
    if row is None:
        return DEFAULT_POLICY
    hours = [h for h in (row.order_reminder_hours or []) if h > 0]
    return Policy(
        discount_limit_sales_pct=row.discount_limit_sales_pct,
        discount_limit_manager_pct=row.discount_limit_manager_pct,
        unconfirmed_after_hours=min(hours) if hours else DEFAULT_POLICY.unconfirmed_after_hours,
        low_stock_threshold=row.low_stock_threshold,
        stock_display=row.stock_display,
    )


def in_branch_scope(actor: ActorContext, branch_id: UUID | None) -> bool:
    """`branch_ids` None — hamma filial. Filiali hali tanlanmagan obyekt doiradan tashqarida emas."""
    return actor.branch_ids is None or branch_id is None or branch_id in actor.branch_ids


def ensure_branch_scope(actor: ActorContext, branch_id: UUID | None) -> None:
    if not in_branch_scope(actor, branch_id):
        raise ForbiddenError("Branch is outside your scope", branch_id=branch_id)


async def load_branch(
    db: AsyncSession,
    actor: ActorContext,
    branch_id: UUID,
    *,
    field_name: str = "branch_id",
    pickup: bool = False,
) -> Branch:
    """Shu shopning ochiq filiali. Yo'q yoki boshqa shopniki — maydon xatosi; yopiq — BRANCH_CLOSED."""
    branch = (
        await db.execute(select(Branch).where(Branch.id == branch_id, Branch.shop_id == actor.shop_id))
    ).scalar_one_or_none()
    if branch is None:
        raise ValidationError("Branch not found", fields=[field(field_name, "invalid")])
    if branch.status != "ACTIVE":
        raise BranchClosedError("Branch is closed", branch_id=branch_id)
    if pickup and not branch.is_pickup_point:  # olib ketish — faqat olib ketish joyidan (commerce.md §7)
        raise ValidationError("Branch is not a pickup point", fields=[field(field_name, "invalid")])
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
    """platform.memberships.id → xodim ismi (ro'yxat va kartochkada "kim")."""
    wanted = {i for i in ids if i is not None}
    if not wanted or shop_id is None:
        return {}
    rows = await db.execute(
        select(Membership.id, Principal.full_name)
        .join(Principal, Principal.id == Membership.principal_id)
        .where(Membership.shop_id == shop_id, Membership.id.in_(wanted))
    )
    return {membership_id: name for membership_id, name in rows}


# ------------------------------------------------------------------ cursor (11 §4.1)


def _bad_cursor() -> ValidationError:
    return ValidationError("Cursor is invalid", fields=[field("cursor", "invalid_format")])


def read_cursor(cursor: str, kind: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Cursor klientdan keladi — har shakli tekshiriladi (buzilgani 500 emas, 422)."""
    raw = decode_cursor(cursor)
    if raw.get("k") != kind:
        raise _bad_cursor()
    values: dict[str, str] = {}
    for key in keys:
        value = raw.get(key)
        if not isinstance(value, str) or NUL in value or len(value) > 100:
            raise _bad_cursor()
        values[key] = value
    return values


def cursor_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise _bad_cursor() from exc


def cursor_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _bad_cursor() from exc
    if parsed.tzinfo is None or parsed.year < 2000:
        raise _bad_cursor()
    return parsed


def make_cursor(kind: str, **values: object) -> str:
    return encode_cursor(
        {"k": kind, **{k: v.isoformat() if isinstance(v, datetime) else str(v) for k, v in values.items()}}
    )
