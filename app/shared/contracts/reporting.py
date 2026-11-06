"""Hisobot (7c) manba port'i: proyeksiyalarni mavjud ma'lumotdan qayta qurish va tannarx o'qish.

`reporting` boshqa domenlarning jadvallarini o'qimaydi (19 §2). Qayta qurish uchun manba adapteri
(`app/db/reporting_sources.py`, composition root) mavjud qatorlardan SINTETIK event'lar yasaydi — ular
jonli event'lar bilan bir xil shaklda va bir xil proyeksiya kodidan o'tadi, shuning uchun qayta qurish
natijasi jonli natija bilan mos keladi. Shaxsiy ma'lumot qaytarilmaydi.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events.envelope import EventEnvelope


class ReportingSourcePort(Protocol):
    async def sku_costs(self, db: AsyncSession, shop_id: UUID) -> dict[UUID, int]:
        """SKU → joriy o'rtacha tannarx (so'm, tiyinda). Tannarxi noma'lum SKU natijada yo'q."""
        ...

    async def orders(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        """Har buyurtma uchun bitta `commerce.order.<holat>` (COMPLETED bo'lsa `lines[]` bilan)."""
        ...

    async def quick_sales(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        """Har tez sotuv uchun `commerce.quick_sale.recorded`."""
        ...

    async def stock(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        """Har filial × SKU uchun `commerce.stock.changed` (absolyut qiymatlar)."""
        ...

    async def cases(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        """Har murojaat uchun `support.case.status_changed`."""
        ...

    async def conversations(self, db: AsyncSession, shop_id: UUID) -> list[EventEnvelope]:
        """Xabarlar (`message.received` / `message.queued`) va uzatishlar (`conversation.handed_off` /
        `conversation.taken`) — vaqt bo'yicha tartiblangan."""
        ...
