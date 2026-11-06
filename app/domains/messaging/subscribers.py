"""messaging tinglovchilari (05 §6, 13 §4): kanalga yuborish, xaridor rasmini yuklab olish,
buyurtma holati xabari.

`channel_send` va rasm yuklash — tashqi chaqiruv, shuning uchun tranzaksiyasiz (o'z holati bilan idempotent:
faqat `QUEUED` xabar yuboriladi, faqat `PENDING` biriktirma yuklanadi). Buyurtma holati xabari —
tranzaksiyali: chiquvchi xabar va uning outbox'i tinglovchi belgisi bilan bitta COMMIT'da.
"""

from __future__ import annotations

from app.domains.messaging.providers import from_state
from app.shared.events.registry import EventContext, subscriber


@subscriber("messaging.channel_send", "messaging.message.queued", schema="messaging", transactional=False)
async def channel_send(ctx: EventContext) -> None:
    envelope = ctx.envelope
    if envelope.shop_id is None:
        return
    await from_state(ctx.services).sending.send(ctx.database, envelope.shop_id, envelope.aggregate_id)


@subscriber(
    "messaging.attachment_fetch", "messaging.message.received", schema="messaging", transactional=False
)
async def attachment_fetch(ctx: EventContext) -> None:
    envelope = ctx.envelope
    if envelope.shop_id is None or not envelope.payload.get("attachments"):
        return
    await from_state(ctx.services).sending.fetch_attachments(
        ctx.database, envelope.shop_id, envelope.aggregate_id
    )


@subscriber(
    "messaging.order_status_notify",
    "commerce.order.confirmed",
    "commerce.order.ready",
    "commerce.order.completed",
    "commerce.order.cancelled",
    schema="messaging",
)
async def order_status_notify(ctx: EventContext) -> None:
    await from_state(ctx.services).notifier.on_order_event(ctx.session, ctx.envelope)
