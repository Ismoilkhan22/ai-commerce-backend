"""Xaridorga buyurtma holati xabari (S4-06, 20 §6): buyurtma suhbatdan bo'lsa — o'sha kanal orqali.

`commerce.order.confirmed | ready | completed | cancelled` event'i → matn (shop matni yoki standart,
xaridor tilida) → chiquvchi xabar (`NOTIFICATION`) → `channel_send`. Har o'tish uchun bitta xabar:
`intent_key = order:{id}:{holat}` unikal, tinglovchi esa `consumer_receipts` bilan takrorlanmaydi.
Saytdan kelgan, suhbatsiz buyurtmaga xabar yo'q — xaridor holat sahifasidan ko'radi (DEC-115).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.models.orm import Conversation
from app.domains.messaging.services.outbound import MessageWriter, reachability
from app.platform.notifications.customer_templates import safe_render
from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.platform.shops.models.orm import Branch, Shop
from app.shared.events.envelope import EventEnvelope
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

ORDER_TEMPLATES: dict[str, str] = {
    "commerce.order.confirmed": "customer.order_confirmed",
    "commerce.order.ready": "customer.order_ready_pickup",
    "commerce.order.completed": "customer.order_completed",
    "commerce.order.cancelled": "customer.order_cancelled",
}
_CURRENCY = {"uz": "so'm", "ru": "сум", "en": "UZS"}
_PICKUP = {"uz": "Olib ketish: {address}", "ru": "Самовывоз: {address}", "en": "Pickup: {address}"}
_PHONE = {"uz": "Tel: {phone}.", "ru": "Тел.: {phone}.", "en": "Phone: {phone}."}
_DELIVERY = {
    "uz": "Yetkazish bo'yicha operator siz bilan kelishadi.",
    "ru": "Оператор согласует с вами доставку.",
    "en": "Our operator will arrange the delivery with you.",
}


def format_total(total_minor: Any, locale: str) -> str:
    """Tiyin → "4 800 000 so'm" (en: "UZS 4,800,000")."""
    try:
        som = int(total_minor) // 100
    except (TypeError, ValueError):
        return ""
    if locale == "en":
        return f"UZS {som:,}"
    return f"{som:,}".replace(",", " ") + f" {_CURRENCY.get(locale, _CURRENCY['uz'])}"


class CustomerNotifier:
    def __init__(self, writer: MessageWriter, templates: CustomerTemplateService) -> None:
        self.writer = writer
        self.templates = templates

    async def on_order_event(self, db: AsyncSession, envelope: EventEnvelope) -> str:
        """Natija: sent | skipped:<sabab>."""
        template_key = ORDER_TEMPLATES.get(envelope.event_type)
        payload = envelope.payload
        raw_conversation = payload.get("conversation_id")
        if template_key is None or not raw_conversation or envelope.shop_id is None:
            return "skipped:no_conversation"
        if envelope.event_type == "commerce.order.ready" and payload.get("fulfillment_method") != "PICKUP":
            return "skipped:delivery"  # "tayyor — olib keting" faqat olib ketishda (20 §6)
        conversation = await db.get(Conversation, UUID(str(raw_conversation)), with_for_update=True)
        if conversation is None or conversation.shop_id != envelope.shop_id:
            return "skipped:no_conversation"
        reach = await reachability(db, conversation)
        if not reach.ok:
            logger.info("messaging.order_notice_suppressed", reason=reach.reason)
            return f"skipped:{reach.reason}"
        # Til: buyurtmadagi xaridor tili → suhbat tili → uz (QA 5b M1)
        locale = str(payload.get("customer_locale") or conversation.locale or "uz")
        body, _ = await self.templates.resolve(db, conversation.shop_id, template_key, locale)
        text = safe_render(template_key, body, await self._variables(db, envelope, locale), locale)
        status = envelope.event_type.rsplit(".", 1)[-1]
        await self.writer.append_outbound(
            db,
            ActorContext.system(conversation.shop_id),
            conversation,
            origin="NOTIFICATION",
            author_type="SYSTEM",
            body=text,
            intent_key=f"order:{payload.get('order_id')}:{status}",
            require_reachable=False,
        )
        return "sent"

    async def _variables(self, db: AsyncSession, envelope: EventEnvelope, locale: str) -> dict[str, Any]:
        payload = envelope.payload
        shop = await db.get(Shop, envelope.shop_id)
        branch = await db.get(Branch, UUID(str(payload["branch_id"]))) if payload.get("branch_id") else None
        lang = locale if locale in _PICKUP else "uz"
        if payload.get("fulfillment_method") == "DELIVERY":
            line = _DELIVERY[lang]
        else:
            line = _PICKUP[lang].format(address=branch.address) if branch is not None else ""
        phone = (branch.phone if branch is not None else None) or ""
        return {
            "phone_line": _PHONE[lang].format(phone=phone) if phone else "",
            "order_number": payload.get("number"),
            "total": format_total(payload.get("total_minor"), lang),
            "fulfillment_line": line,
            "shop_address": branch.address if branch is not None else "",
            "shop_phone": phone,
            "shop_name": shop.name if shop is not None else "",
        }
