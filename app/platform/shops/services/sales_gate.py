"""Shop yangi savdo qabul qila oladimi (FSM-01, TC-023, DEC-136).

To'xtatilgan (SUSPENDED) va yopilgan (CLOSED) shopda yangi savdo yo'q: buyurtma yaratish, tez sotuv,
saytdan so'rov (4-modul). Mavjud buyurtmalar esa oxiriga yetkaziladi — tasdiq, tayyorlash, topshirish,
bekor qilish ishlayveradi. Qoralama va tekshiruvdagi shop sota oladi (DEC-136).

`details.shop_status` — klient farqlaydi: CLOSED — sessiya tugaydi; SUSPENDED — faqat shu amal rad etiladi.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.shops.models.orm import Shop
from app.shared.errors.base import ShopNotActiveError

NO_NEW_SALES = frozenset({"SUSPENDED", "CLOSED"})


async def ensure_shop_can_sell(db: AsyncSession, shop_id: UUID) -> None:
    status = await db.scalar(select(Shop.status).where(Shop.id == shop_id))
    if status in NO_NEW_SALES:
        raise ShopNotActiveError("Shop does not accept new sales", shop_status=status)
