"""reporting tinglovchilari (19 §2, 05 §8): boshqa domenlar event'larini read model'larga yozadi.

Hammasi tranzaksiyali (standart): `reporting.consumer_receipts` belgisi va proyeksiya yozuvi bitta COMMIT'da
(TC-022), shop konteksti event shopi bilan ochiladi (RLS). Tashqi chaqiruv yo'q — faqat katalog o'lchami
`CatalogQueryPort` orqali o'qiladi. Tinglovchi nomi o'zgarmas: o'zgartirilsa takrordan himoya buziladi.
"""

from __future__ import annotations

from app.domains.reporting.projections import apply_event
from app.shared.events.registry import EventContext, subscriber


async def _apply(ctx: EventContext) -> None:
    await apply_event(ctx.session, ctx.services.reporting.catalog, ctx.envelope)


@subscriber(
    "reporting.sales_facts",
    "commerce.order.*",
    "commerce.quick_sale.recorded",
    schema="reporting",
)
async def sales_facts(ctx: EventContext) -> None:
    await _apply(ctx)


@subscriber("reporting.stock_facts", "commerce.stock.changed", schema="reporting")
async def stock_facts(ctx: EventContext) -> None:
    await _apply(ctx)


@subscriber("reporting.support_facts", "support.case.*", schema="reporting")
async def support_facts(ctx: EventContext) -> None:
    await _apply(ctx)


@subscriber(
    "reporting.conversation_facts",
    "messaging.message.received",
    "messaging.message.queued",
    "messaging.message.sent",
    "messaging.conversation.handed_off",
    "messaging.conversation.taken",
    schema="reporting",
)
async def conversation_facts(ctx: EventContext) -> None:
    await _apply(ctx)


SUBSCRIBERS = [sales_facts, stock_facts, support_facts, conversation_facts]
