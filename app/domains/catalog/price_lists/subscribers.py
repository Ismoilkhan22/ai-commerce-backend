"""Narx ro'yxatini fonda o'qish (DEC-149): `catalog.price_list.read` → AI o'qiydi va moslaydi.

Tranzaksiyasiz: LLM chaqiruvi uzoq, natija o'z tranzaksiyasida yoziladi; takror ishlasa — `READING` emas,
o'tkaziladi.
"""

from __future__ import annotations

from uuid import UUID

from app.domains.catalog.providers import CatalogServices
from app.shared.events.registry import EventContext, subscriber


@subscriber("catalog.price_list_reader", "catalog.price_list.read", schema="catalog", transactional=False)
async def read_price_list(ctx: EventContext) -> None:
    catalog: CatalogServices = ctx.services.catalog
    assert ctx.envelope.shop_id is not None
    await catalog.price_lists.read(
        ctx.database, ctx.envelope.shop_id, UUID(str(ctx.envelope.payload["price_list_id"]))
    )
