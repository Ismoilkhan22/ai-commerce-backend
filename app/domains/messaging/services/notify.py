"""Xaridorga buyurtma holati xabari (S4-06, 20 §6): buyurtma suhbatdan bo'lsa — o'sha kanal orqali.

`commerce.order.confirmed | ready | completed | cancelled` event'i → matn (shop matni yoki standart,
xaridor tilida) → chiquvchi xabar (`NOTIFICATION`) → `channel_send`. Har o'tish uchun bitta xabar:
`intent_key = order:{id}:{holat}` unikal, tinglovchi esa `consumer_receipts` bilan takrorlanmaydi.
Saytdan kelgan, suhbatsiz buyurtmaga xabar yo'q — xaridor holat sahifasidan ko'radi (DEC-115).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.models.orm import Conversation
from app.domains.messaging.services.outbound import MessageWriter, reachability
from app.platform.notifications.customer_templates import safe_render
from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.platform.shops.models.orm import Branch, Shop
from app.shared.clock import utcnow
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
_EXPIRES = {
    "uz": "Amal qilish muddati: {when} (UTC).",
    "ru": "Действует до: {when} (UTC).",
    "en": "Valid until: {when} (UTC).",
}
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


# 7b (DEC-145): kafolat murojaati — event → shablon. "approved"/"rejected" `status_changed` ning holatidan
SUPPORT_TEMPLATES: dict[str, str] = {
    "support.case.opened": "customer.support_case_opened",
    "APPROVED": "customer.support_case_approved",
    "REJECTED": "customer.support_case_rejected",
    "support.case.ready_notice": "customer.support_case_ready",
}
_ITEM = {"uz": " Mahsulot: {title}.", "ru": " Товар: {title}.", "en": " Item: {title}."}
_RESOLUTION = {
    "REPAIR": {"uz": "ta'mirlaymiz", "ru": "отремонтируем", "en": "we will repair it"},
    "REPLACE": {"uz": "almashtiramiz", "ru": "заменим", "en": "we will replace it"},
    "REFUND": {
        "uz": "qaytarishni rasmiylashtiramiz",
        "ru": "оформим возврат",
        "en": "we will process the return",
    },
}
# Sabab matni — rad sababi kodidan, xaridor tilida; erkin izoh xaridorga ketmaydi
_REJECT_REASON = {
    "WARRANTY_EXPIRED": {
        "uz": "Kafolat muddati tugagan. ",
        "ru": "Гарантийный срок истёк. ",
        "en": "The warranty period has expired. ",
    },
    "NO_DEFECT_FOUND": {
        "uz": "Tekshiruvda nuqson topilmadi. ",
        "ru": "При проверке дефект не найден. ",
        "en": "No defect was found during the check. ",
    },
    "USER_DAMAGE": {
        "uz": "Shikast kafolat shartiga kirmaydi. ",
        "ru": "Повреждение не покрывается гарантией. ",
        "en": "The damage is not covered by the warranty. ",
    },
    "NOT_OUR_SALE": {
        "uz": "Bu mahsulot bizdan sotilgani tasdiqlanmadi. ",
        "ru": "Не подтверждено, что товар продан нами. ",
        "en": "We could not confirm this item was sold by us. ",
    },
    "RETURN_NOT_ALLOWED": {
        "uz": "Qaytarish shartlariga mos kelmadi. ",
        "ru": "Не соответствует условиям возврата. ",
        "en": "It does not meet the return conditions. ",
    },
}


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

    async def on_support_event(self, db: AsyncSession, envelope: EventEnvelope) -> str:
        """Kafolat murojaati holati xaridorga — murojaat suhbatga bog'langan bo'lsa (4 ta xabar: ochildi,
        qabul qilindi, rad etildi, tayyor). Bir holatga bitta xabar: `intent_key = support:{id}:{holat}`."""
        payload = envelope.payload
        key = (
            envelope.event_type
            if envelope.event_type != "support.case.status_changed"
            else payload.get("status")
        )
        template_key = SUPPORT_TEMPLATES.get(str(key))
        raw_conversation = payload.get("conversation_id")
        if template_key is None or not raw_conversation or envelope.shop_id is None:
            return "skipped:no_conversation"
        conversation = await db.get(Conversation, UUID(str(raw_conversation)), with_for_update=True)
        if conversation is None or conversation.shop_id != envelope.shop_id:
            return "skipped:no_conversation"
        reach = await reachability(db, conversation)
        if not reach.ok:
            logger.info("messaging.support_notice_suppressed", reason=reach.reason)
            return f"skipped:{reach.reason}"
        locale = str(payload.get("customer_locale") or conversation.locale or "uz")
        lang = locale if locale in _ITEM else "uz"
        body, _ = await self.templates.resolve(db, conversation.shop_id, template_key, locale)
        shop = await db.get(Shop, envelope.shop_id)
        branch = await db.get(Branch, UUID(str(payload["branch_id"]))) if payload.get("branch_id") else None
        phone = (branch.phone if branch is not None else None) or ""
        title = payload.get("item_title")
        variables: dict[str, Any] = {
            "case_number": payload.get("number"),
            "item_line": _ITEM[lang].format(title=title) if title else "",
            "resolution_line": _RESOLUTION.get(str(payload.get("resolution")), {}).get(lang, ""),
            "reason_line": _REJECT_REASON.get(str(payload.get("reject_reason")), {}).get(lang, ""),
            "shop_address": branch.address if branch is not None else "",
            "shop_phone": phone,
            "phone_line": _PHONE[lang].format(phone=phone) if phone else "",
            "shop_name": shop.name if shop is not None else "",
        }
        text = safe_render(template_key, body, variables, locale)
        await self.writer.append_outbound(
            db,
            ActorContext.system(conversation.shop_id),
            conversation,
            origin="NOTIFICATION",
            author_type="SYSTEM",
            body=text,
            intent_key=f"support:{payload.get('case_id')}:{template_key.rsplit('_', 1)[-1]}",
            require_reachable=False,
        )
        return "sent"

    async def on_quote_reminder(self, db: AsyncSession, envelope: EventEnvelope) -> str:
        """DEC-149: taklif eslatmasi — bitta (`intent_key = quote:{id}:reminder`), xaridor voz kechgan yoki
        bloklagan bo'lsa yuborilmaydi."""
        payload = envelope.payload
        raw = payload.get("conversation_id")
        if not raw or envelope.shop_id is None:
            return "skipped:no_conversation"
        expires = payload.get("expires_at")
        if expires and datetime.fromisoformat(str(expires)) <= utcnow():
            return "skipped:expired"  # navbatda turib qolgan — muddati o'tgan taklifga eslatma yo'q (QA #16)
        conversation = await db.get(Conversation, UUID(str(raw)), with_for_update=True)
        if conversation is None or conversation.shop_id != envelope.shop_id:
            return "skipped:no_conversation"
        reach = await reachability(db, conversation)
        if not reach.ok:
            return f"skipped:{reach.reason}"
        locale = str(conversation.locale or "uz")
        lang = locale if locale in _EXPIRES else "uz"
        body, _ = await self.templates.resolve(db, conversation.shop_id, "customer.quote_reminder", locale)
        shop = await db.get(Shop, envelope.shop_id)
        expires = payload.get("expires_at")
        variables: dict[str, Any] = {
            "quote_number": payload.get("number"),
            "expires_line": _EXPIRES[lang].format(when=str(expires)[:16].replace("T", " "))
            if expires
            else "",
            "shop_name": shop.name if shop is not None else "",
        }
        text = safe_render("customer.quote_reminder", body, variables, locale)
        await self.writer.append_outbound(
            db,
            ActorContext.system(conversation.shop_id),
            conversation,
            origin="NOTIFICATION",
            author_type="SYSTEM",
            body=text,
            intent_key=f"quote:{payload.get('quote_id')}:reminder",
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
