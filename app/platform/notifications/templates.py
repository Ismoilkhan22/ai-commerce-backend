"""Xodim xabarnomalari matnlari — kodda, versiyasi bilan (DEC-139, 1-qaror; 20 §5).

Shop o'zgartiradigan xaridor matnlari (`customer.*`) — 5b, `shop_message_templates` bilan.
O'zgaruvchilarda telefon, manzil, ism YO'Q — faqat raqam, son, kod.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STAFF_TEMPLATE_VERSION = "staff-2026-10-v1"


@dataclass(frozen=True)
class Template:
    priority: str
    title: dict[str, str]
    body: dict[str, str]


TEMPLATES: dict[str, Template] = {
    "staff.new_order": Template(
        "HIGH",  # 20 §8: yangi buyurtma — yuqori (tinch soatda ham yetadi)
        {
            "uz": "Yangi buyurtma #{order_number}",
            "ru": "Новый заказ #{order_number}",
            "en": "New order #{order_number}",
        },
        {
            "uz": "Saytdan so'rov keldi — tasdiq kutmoqda.",
            "ru": "Заявка с сайта — ждёт подтверждения.",
            "en": "Request from the website — awaiting confirmation.",
        },
    ),
    "staff.order_confirm_reminder": Template(
        "NORMAL",
        {
            "uz": "Buyurtma #{order_number} tasdiq kutmoqda",
            "ru": "Заказ #{order_number} ждёт подтверждения",
            "en": "Order #{order_number} awaits confirmation",
        },
        {
            "uz": "{hours} soatdan beri tasdiqlanmagan. Xaridor bilan bog'laning.",
            "ru": "Не подтверждён уже {hours} ч. Свяжитесь с покупателем.",
            "en": "Unconfirmed for {hours} h. Please contact the customer.",
        },
    ),
    "staff.reservation_review": Template(
        "NORMAL",
        {
            "uz": "Buyurtma #{order_number}: band muddati o'tdi",
            "ru": "Заказ #{order_number}: срок резерва истёк",
            "en": "Order #{order_number}: reservation is due",
        },
        {
            "uz": "Mahsulot {hours} soatdan beri band. Kutasizmi yoki bekor qilasizmi?",
            "ru": "Товар в резерве уже {hours} ч. Ждём или отменяем?",
            "en": "Items reserved for {hours} h. Keep waiting or cancel?",
        },
    ),
    "staff.import_ready": Template(
        "NORMAL",
        {
            "uz": "Import tekshirildi",
            "ru": "Импорт проверен",
            "en": "Import checked",
        },
        {
            "uz": "{rows} qator: {created} yangi, {updated} yangilanadi, {errors} xato. Ko'rib chiqing.",
            "ru": "{rows} строк: {created} новых, {updated} обновится, {errors} с ошибками. Проверьте.",
            "en": "{rows} rows: {created} new, {updated} to update, {errors} with errors. Please review.",
        },
    ),
    "staff.import_completed": Template(
        "NORMAL",
        {
            "uz": "Import tugadi",
            "ru": "Импорт завершён",
            "en": "Import finished",
        },
        {
            "uz": "{created} ta yangi mahsulot (qoralama), {updated} ta yangilandi, {errors} xato.",
            "ru": "{created} новых товаров (черновики), {updated} обновлено, {errors} ошибок.",
            "en": "{created} new products (drafts), {updated} updated, {errors} errors.",
        },
    ),
    "staff.import_failed": Template(
        "NORMAL",
        {
            "uz": "Import to'xtadi",
            "ru": "Импорт остановлен",
            "en": "Import stopped",
        },
        {
            "uz": "Faylni qayta yuklang yoki yordamga murojaat qiling.",
            "ru": "Загрузите файл заново или обратитесь в поддержку.",
            "en": "Upload the file again or contact support.",
        },
    ),
    "staff.adjustment_approval": Template(
        "NORMAL",
        {
            "uz": "Qoldiq tuzatish so'rovi",
            "ru": "Запрос на корректировку остатка",
            "en": "Stock adjustment request",
        },
        {
            "uz": "Omborchi qoldiqni tuzatishni so'radi — tasdiqlash kerak.",
            "ru": "Кладовщик запросил корректировку — нужно подтверждение.",
            "en": "Warehouse staff requested an adjustment — approval needed.",
        },
    ),
    "staff.support_case_opened": Template(
        "NORMAL",
        {
            "uz": "Yangi kafolat murojaati K-{case_number}",
            "ru": "Новое гарантийное обращение K-{case_number}",
            "en": "New warranty case K-{case_number}",
        },
        {
            "uz": "Murojaat ochildi — qaror menejer yoki ega tomonidan qabul qilinadi.",
            "ru": "Обращение открыто — решение принимает менеджер или владелец.",
            "en": "A case was opened — a manager or owner makes the decision.",
        },
    ),
    "staff.stock_reconcile_mismatch": Template(
        "HIGH",
        {
            "uz": "Ombor daftarida farq",
            "ru": "Расхождение в складском журнале",
            "en": "Stock ledger mismatch",
        },
        {
            "uz": "{count} ta qoldiq daftar bilan mos emas. Avtomatik tuzatilmadi — tekshiring.",
            "ru": "{count} остатков не совпадают с журналом. Не исправлено автоматически — проверьте.",
            "en": "{count} balances differ from the ledger. Not fixed automatically — please check.",
        },
    ),
    "staff.exchange_rate_stale": Template(
        "NORMAL",
        {"uz": "Dollar kursi eskirgan", "ru": "Курс доллара устарел", "en": "Exchange rate is stale"},
        {
            "uz": (
                "Oxirgi kurs {hours} soatdan eski. Dollar narxli buyurtmalar tasdiqlanmaydi — "
                "yangi kurs kiriting."
            ),
            "ru": (
                "Курсу больше {hours} ч. Заказы с ценой в долларах не подтверждаются — введите новый курс."
            ),
            "en": (
                "The rate is older than {hours} h. USD-priced orders cannot be confirmed — enter a new rate."
            ),
        },
    ),
    # 5b: suhbatlar (20 §8). O'zgaruvchilarda xaridor ismi yo'q — faqat kanal va daqiqa
    "staff.handoff": Template(
        "HIGH",
        {
            "uz": "Operator kerak — {channel}",
            "ru": "Нужен оператор — {channel}",
            "en": "Operator needed — {channel}",
        },
        {
            "uz": "Xaridor javob kutmoqda. Suhbatni oling.",
            "ru": "Покупатель ждёт ответа. Возьмите диалог.",
            "en": "A customer is waiting for a reply. Take the conversation.",
        },
    ),
    "staff.handoff_reminder": Template(
        "NORMAL",
        {
            "uz": "Xaridor {minutes} daqiqadan beri kutmoqda",
            "ru": "Покупатель ждёт уже {minutes} мин",
            "en": "A customer has been waiting for {minutes} min",
        },
        {
            "uz": "{channel} suhbatiga hali hech kim javob bermadi.",
            "ru": "В диалоге ({channel}) ещё никто не ответил.",
            "en": "Nobody has replied in the {channel} conversation yet.",
        },
    ),
    "staff.message_failed": Template(
        "NORMAL",
        {
            "uz": "Xabar yuborilmadi — {channel}",
            "ru": "Сообщение не отправлено — {channel}",
            "en": "Message not delivered — {channel}",
        },
        {
            "uz": "Xaridorga xabar yetmadi ({error_code}). Suhbatni oching va boshqa yo'l bilan bog'laning.",
            "ru": "Сообщение не дошло ({error_code}). Откройте диалог и свяжитесь другим способом.",
            "en": "Message not delivered ({error_code}). Open the conversation and reach out another way.",
        },
    ),
    # 6b: AI sotuvchi (M06 §8) — limit tugadi, AI to'xtadi, suhbatlar operatorga
    "staff.ai_budget_warning": Template(
        "NORMAL",
        {
            "uz": "AI xarajati {period} limitning 80% iga yetdi",
            "ru": "Расход AI достиг 80% лимита ({period})",
            "en": "AI spend reached 80% of the {period} limit",
        },
        {
            "uz": "Limit tugasa AI to'xtaydi va suhbatlar operatorga o'tadi.",
            "ru": "Когда лимит закончится, AI остановится и диалоги перейдут к оператору.",
            "en": "When the limit is reached the AI pauses and conversations go to operators.",
        },
    ),
    "staff.ai_budget_exceeded": Template(
        "HIGH",
        {
            "uz": "AI sotuvchi to'xtadi — {period} limit tugadi",
            "ru": "AI-продавец остановлен — исчерпан лимит ({period})",
            "en": "AI seller paused — {period} cost limit reached",
        },
        {
            "uz": "Yangi suhbatlar operatorga o'tadi. Limitni AI sozlamalarida oshirishingiz mumkin.",
            "ru": "Новые диалоги переходят к оператору. Лимит можно поднять в настройках AI.",
            "en": "New conversations go to operators. You can raise the limit in AI settings.",
        },
    ),
}


class _Safe(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template_key: str, locale: str, variables: dict[str, Any]) -> tuple[str, str]:
    template = TEMPLATES[template_key]
    lang = locale if locale in template.title else "uz"
    values = _Safe(variables)
    return template.title[lang].format_map(values), template.body[lang].format_map(values)


def priority_of(template_key: str) -> str:
    return TEMPLATES[template_key].priority
