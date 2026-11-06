"""Rejali ishlar uchun shoplar ro'yxati (DEC-138, 3-qaror).

`platform.shops` RLS'siz — ro'yxat to'g'ridan o'qiladi; har shop keyin ALOHIDA tranzaksiyada, o'z konteksti
bilan ishlanadi (RLS hech qayerda o'chirilmaydi, 07 §10). Yopilgan shoplarda ish yo'q.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.platform.shops.models.orm import Shop
from app.shared.db.session import Database


async def open_shop_ids(database: Database) -> list[UUID]:
    async with database.transaction(read_only=True) as db:
        return list(
            (await db.execute(select(Shop.id).where(Shop.status != "CLOSED").order_by(Shop.id))).scalars()
        )
