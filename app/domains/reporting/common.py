"""reporting umumiy yordamchilari: shop vaqti, JSON qiymatlarni o'qish, `data_as_of`."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reporting.models.orm import ProjectionCheckpoint
from app.platform.shops.models.orm import Shop

DEFAULT_ZONE = "Asia/Tashkent"  # DEC-146: "kecha" — Toshkent vaqti bo'yicha


async def shop_zone(db: AsyncSession, shop_id: UUID) -> ZoneInfo:
    name = await db.scalar(select(Shop.timezone).where(Shop.id == shop_id))
    try:
        return ZoneInfo(name or DEFAULT_ZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_ZONE)


def day_of(moment: datetime, zone: ZoneInfo) -> date:
    """Lahza shop vaqtida qaysi kunga tushadi (23:30 Toshkent = o'sha kun, UTC'da esa 18:30)."""
    return moment.astimezone(zone).date()


def day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=zone)


def days_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def as_uuid(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def as_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def as_int(value: Any) -> int | None:
    return None if value is None else int(value)


async def data_as_of(db: AsyncSession, shop_id: UUID, projections: tuple[str, ...]) -> datetime | None:
    """Javobdagi `data_as_of`: so'rovdagi proyeksiyalarning eng eskisi (19 §5). Hech biri yangilanmagan
    bo'lsa — None."""
    rows = (
        await db.execute(
            select(ProjectionCheckpoint.projection, func.max(ProjectionCheckpoint.last_occurred_at))
            .where(ProjectionCheckpoint.shop_id == shop_id, ProjectionCheckpoint.projection.in_(projections))
            .group_by(ProjectionCheckpoint.projection)
        )
    ).all()
    moments = [moment for _, moment in rows if moment is not None]
    return min(moments) if moments else None
