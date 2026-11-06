"""messaging tinglovchilari (05 §6, 13 §4): kanalga yuborish, xaridor rasmini yuklab olish,
buyurtma holati xabari.

`channel_send` va rasm yuklash — tashqi chaqiruv, shuning uchun tranzaksiyasiz (o'z holati bilan idempotent:
faqat `QUEUED` xabar yuboriladi, faqat `PENDING` biriktirma yuklanadi). Buyurtma holati xabari —
tranzaksiyali: chiquvchi xabar va uning outbox'i tinglovchi belgisi bilan bitta COMMIT'da.
"""

from __future__ import annotations

from app.domains.messaging.providers import from_state
from app.domains.messaging.services.ig_common import as_uuid
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


@subscriber(
    "messaging.support_case_notify",
    "support.case.opened",
    "support.case.status_changed",
    "support.case.ready_notice",
    schema="messaging",
)
async def support_case_notify(ctx: EventContext) -> None:
    """Kafolat murojaati (7b, DEC-145): ochildi / qabul qilindi / rad etildi / tayyor — suhbat bo'lsa."""
    await from_state(ctx.services).notifier.on_support_event(ctx.session, ctx.envelope)


@subscriber("messaging.quote_reminder", "commerce.quote.reminder_due", schema="messaging")
async def quote_reminder_notify(ctx: EventContext) -> None:
    """DEC-149: javobsiz taklifga bitta eslatma — suhbat bo'lsa va xaridor voz kechmagan bo'lsa."""
    await from_state(ctx.services).notifier.on_quote_reminder(ctx.session, ctx.envelope)


# ------------------------------------------------------------------ Instagram izohlari (DEC-148)
# Uchala tinglovchi `ig_comment.received` ga alohida: javob, kayfiyat va post media bir-birini kutmaydi.
@subscriber("messaging.ig_comment_reply", "messaging.ig_comment.received", schema="messaging")
async def ig_comment_reply(ctx: EventContext) -> None:
    """«+» / narx so'rovi → qaror va (ruxsat bo'lsa) javob navbati. `intent_key` takrorni yopadi."""
    await from_state(ctx.services).ig.reply.decide(ctx.session, ctx.envelope)


@subscriber(
    "messaging.ig_reply_send",
    "messaging.ig_comment.reply_queued",
    schema="messaging",
    transactional=False,
)
async def ig_reply_send(ctx: EventContext) -> None:
    envelope = ctx.envelope
    reply_id = as_uuid(envelope.payload.get("reply_id"))
    if envelope.shop_id is None or reply_id is None:
        return
    await from_state(ctx.services).ig.reply.send(ctx.database, envelope.shop_id, reply_id)


@subscriber(
    "messaging.ig_comment_classify",
    "messaging.ig_comment.received",
    schema="messaging",
    transactional=False,
)
async def ig_comment_classify(ctx: EventContext) -> None:
    """Kayfiyat (AI, `light`): tashqi chaqiruv tranzaksiyadan tashqarida; holati o'zida (idempotent)."""
    envelope = ctx.envelope
    comment_id = as_uuid(envelope.payload.get("item_id"))
    if envelope.shop_id is None or comment_id is None or not envelope.payload.get("has_content"):
        return
    await from_state(ctx.services).ig.classify.run(ctx.database, envelope.shop_id, comment_id)


@subscriber(
    "messaging.ig_post_fetch",
    "messaging.ig_comment.received",
    schema="messaging",
    transactional=False,
)
async def ig_post_fetch(ctx: EventContext) -> None:
    envelope = ctx.envelope
    post_id = as_uuid(envelope.payload.get("post_id"))
    if envelope.shop_id is None or post_id is None:
        return
    await from_state(ctx.services).ig.media.fetch(ctx.database, envelope.shop_id, post_id)
