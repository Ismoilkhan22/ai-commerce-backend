"""Xaridorga yuboriladigan matnlar (20 §6–7, DEC-139 1-qaror): standart matnlar kodda, versiyasi bilan.

Shop o'zgartirgan matn — `platform.shop_message_templates` (faol versiya). Tanlash tartibi:
shop matni (xaridor tilida) → standart (xaridor tilida) → standart (uz).

O'zgaruvchilarda telefon, manzil va ism YO'Q — faqat buyurtma raqami, summa va shop rekvizitlari
(filial manzili — shopning ochiq ma'lumoti, xaridorniki emas).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

CUSTOMER_TEMPLATE_VERSION = "customer-2026-10-v1"
LOCALES = ("uz", "ru", "en")
_NAME = re.compile(r"[a-z_]+")
MAX_RENDERED_LENGTH = 1500  # Telegram bitta xabar (4096) va chat uchun yetarli; o'zgaruvchi "portlatmaydi"


@dataclass(frozen=True)
class CustomerTemplate:
    required: frozenset[str]  # shop matnida qolishi shart (TC-NOT-03)
    allowed: frozenset[str]  # matnda ishlatish mumkin bo'lganlar (qolgani — rad)
    body: dict[str, str]


def _template(required: set[str], optional: set[str], body: dict[str, str]) -> CustomerTemplate:
    return CustomerTemplate(frozenset(required), frozenset(required | optional), body)


CUSTOMER_TEMPLATES: dict[str, CustomerTemplate] = {
    "customer.order_confirmed": _template(
        {"order_number"},
        {"total", "fulfillment_line", "shop_name"},
        {
            "uz": "Buyurtma #{order_number} tasdiqlandi. Jami: {total}. {fulfillment_line}",
            "ru": "Заказ #{order_number} подтверждён. Итого: {total}. {fulfillment_line}",
            "en": "Order #{order_number} is confirmed. Total: {total}. {fulfillment_line}",
        },
    ),
    "customer.order_ready_pickup": _template(
        {"order_number"},
        {"shop_address", "shop_phone", "phone_line", "shop_name"},
        {
            "uz": "Buyurtma #{order_number} tayyor. Manzil: {shop_address}. {phone_line}",
            "ru": "Заказ #{order_number} готов. Адрес: {shop_address}. {phone_line}",
            "en": "Order #{order_number} is ready. Address: {shop_address}. {phone_line}",
        },
    ),
    "customer.order_completed": _template(
        set(),
        {"order_number", "shop_name"},
        {
            "uz": "Xaridingiz uchun rahmat! Savollar bo'lsa, shu yerga yozing.",
            "ru": "Спасибо за покупку! Если будут вопросы, пишите сюда.",
            "en": "Thank you for your purchase! If you have any questions, write here.",
        },
    ),
    "customer.order_cancelled": _template(
        {"order_number"},
        {"shop_name"},
        {
            "uz": "Buyurtma #{order_number} bekor qilindi. Savollar bo'lsa, operatorga yozing.",
            "ru": "Заказ #{order_number} отменён. Если есть вопросы, напишите оператору.",
            "en": "Order #{order_number} has been cancelled. If you have questions, write to the operator.",
        },
    ),
    # 7b (DEC-145): kafolat murojaati — faqat suhbat bo'lsa, bir holatga bitta xabar (BL-060)
    "customer.support_case_opened": _template(
        {"case_number"},
        {"item_line", "shop_name"},
        {
            "uz": "Murojaatingiz K-{case_number} qabul qilindi.{item_line} Natija haqida shu yerga yozamiz.",
            "ru": "Ваше обращение K-{case_number} принято.{item_line} О результате напишем сюда.",
            "en": "Your request K-{case_number} has been received.{item_line} We will write the result here.",
        },
    ),
    "customer.support_case_approved": _template(
        {"case_number"},
        {"resolution_line", "shop_name"},
        {
            "uz": "K-{case_number}: murojaatingiz qabul qilindi — {resolution_line}.",
            "ru": "K-{case_number}: ваше обращение одобрено — {resolution_line}.",
            "en": "K-{case_number}: your request was approved — {resolution_line}.",
        },
    ),
    "customer.support_case_rejected": _template(
        {"case_number"},
        {"reason_line", "shop_name"},
        {
            "uz": "K-{case_number}: afsuski, kafolat bo'yicha qabul qilib bo'lmadi. {reason_line}"
            "Savollar bo'lsa, shu yerga yozing.",
            "ru": "K-{case_number}: к сожалению, по гарантии принять не удалось. {reason_line}"
            "Если есть вопросы, пишите сюда.",
            "en": "K-{case_number}: unfortunately we could not accept this under warranty. {reason_line}"
            "If you have questions, write here.",
        },
    ),
    "customer.support_case_ready": _template(
        {"case_number"},
        {"shop_address", "shop_phone", "phone_line", "shop_name"},
        {
            "uz": "K-{case_number}: mahsulotingiz tayyor. Manzil: {shop_address}. {phone_line}",
            "ru": "K-{case_number}: ваш товар готов. Адрес: {shop_address}. {phone_line}",
            "en": "K-{case_number}: your item is ready. Address: {shop_address}. {phone_line}",
        },
    ),
    # Instagram izohi → Direct'ga avtomatik javob (DEC-148). Narx faqat shop bog'lagan katalog mahsulotidan
    "customer.ig_comment_price_reply": _template(
        {"product_title", "price"},
        {"stock_line", "product_url", "shop_name"},
        {
            "uz": "Salom! {product_title} — {price}, {stock_line}.\nBatafsil: {product_url}\n"
            "Savolingiz bo'lsa, shu yerga yozing.",
            "ru": "Здравствуйте! {product_title} — {price}, {stock_line}.\nПодробнее: {product_url}\n"
            "Если есть вопросы, пишите сюда.",
            "en": "Hi! {product_title} — {price}, {stock_line}.\nDetails: {product_url}\n"
            "If you have any questions, write here.",
        },
    ),
    "customer.ig_comment_generic_reply": _template(
        set(),
        {"shop_name"},
        {
            "uz": "Salom! Narx va mavjudlik bo'yicha shu yerga yozing, javob beramiz.",
            "ru": "Здравствуйте! По цене и наличию пишите сюда, мы ответим.",
            "en": "Hi! Write here about price and availability, and we will reply.",
        },
    ),
    "customer.handoff_after_hours": _template(
        set(),
        {"hours", "shop_name"},
        {
            "uz": "Hozir ish vaqtidan tashqari. Operatorimiz {hours} oralig'ida javob beradi.",
            "ru": "Сейчас нерабочее время. Оператор ответит в часы работы: {hours}.",
            "en": "We are currently closed. An operator will reply during working hours: {hours}.",
        },
    ),
}


class TemplateBodyError(ValueError):
    """Shop matni noto'g'ri: majburiy o'zgaruvchi yo'q, noma'lum o'zgaruvchi yoki noto'g'ri qavs/format."""

    def __init__(self, code: str, variables: list[str]) -> None:
        super().__init__(code)
        self.code = code
        self.variables = variables


def _fields(body: str) -> list[tuple[str, str | None]]:
    """Matnni (oddiy matn, o'zgaruvchi nomi) bo'laklariga ajratadi. Ruxsat: faqat `{nom}`.

    Taqiq (QA H1): yolg'iz `{` yoki `}`, pozitsion `{0}` / `{}`, atribut va indeks (`{a.b}`, `{a[0]}`),
    konversiya (`{a!r}`), format (`{a:>999}`). `{{` va `}}` — oddiy qavs sifatida ruxsat.
    """
    try:
        parts = list(string.Formatter().parse(body))
    except ValueError as exc:
        raise TemplateBodyError("invalid_braces", []) from exc
    out: list[tuple[str, str | None]] = []
    for literal, name, spec, conversion in parts:
        if name is None:
            out.append((literal, None))
            continue
        if not name or not _NAME.fullmatch(name):
            raise TemplateBodyError("invalid_placeholder", [name or "{}"])
        if spec or conversion:
            raise TemplateBodyError("invalid_placeholder", [name])
        out.append((literal, name))
    return out


def check_body(template_key: str, body: str) -> None:
    template = CUSTOMER_TEMPLATES[template_key]
    used = {name for _, name in _fields(body) if name is not None}
    missing = sorted(template.required - used)
    if missing:
        raise TemplateBodyError("missing_variables", missing)
    unknown = sorted(used - template.allowed)
    if unknown:
        raise TemplateBodyError("unknown_variables", unknown)


def render_customer(body: str, variables: dict[str, Any]) -> str:
    """Faqat `{nom}` almashtiriladi (format_map emas — atribut/format yo'q). Yo'q qiymat — bo'sh joy."""
    chunks: list[str] = []
    for literal, name in _fields(body):
        chunks.append(literal)
        if name is not None:
            value = variables.get(name)
            chunks.append("" if value is None else str(value))
    text = re.sub(r"[ \t]{2,}", " ", "".join(chunks)).strip()
    return text[:MAX_RENDERED_LENGTH]


def safe_render(template_key: str, body: str, variables: dict[str, Any], locale: str) -> str:
    """Xato bo'lsa — standart matn (o'sha tilda): kiruvchi xabar hech qachon shu sabab yo'qolmaydi."""
    try:
        check_body(template_key, body)
        return render_customer(body, variables)
    except (TemplateBodyError, KeyError):
        logger.warning("notifications.customer_template_fallback", template_key=template_key, locale=locale)
        return render_customer(default_body(template_key, locale), variables)


def default_body(template_key: str, locale: str) -> str:
    bodies = CUSTOMER_TEMPLATES[template_key].body
    return bodies.get(locale) or bodies["uz"]
