"""M39 global Telegram bot va M36 narx ogohlantirishlari (Stage 3) — BL-102, BL-103, BL-108.

```
Xaridor botga yozadi ("RTX 4060") ──▶ ommaviy qidiruv (NetworkQueryPort) ──▶ 5 ta natija + "Ko'rish" (sayt)
                                                                         + "Narx tushsa xabar ber"
Saytdagi tugma ──▶ t.me/<bot>?start=alert_<canonical_id> ──▶ ogohlantirish yoqiladi
/alerts ──▶ ro'yxat va "Bekor qilish" tugmalari (bir bosish)
Har soat ──▶ eng past ommaviy narx oxirgi xabardagidan past bo'lsa va 24 soat o'tgan bo'lsa ──▶ xabar
```

Shop botlari, shop suhbatlari va xaridor ma'lumoti bilan aralashmaydi (alohida token va jadval). Chat raqami
shifrlangan, qidirish — HMAC. Bot bloklagan xaridorga yuborish to'xtaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import GlobalBotChat, PriceAlert
from app.domains.network.query_port import NetworkQueryPortImpl
from app.shared.clock import utcnow
from app.shared.db.encryption import search_hmac
from app.shared.db.session import Database

logger = structlog.get_logger(__name__)

ALERT_EVERY = timedelta(hours=24)  # BL-103: tez-tez emas
TEXTS = {
    "uz": {
        "hello": "Salom! Kompyuter yoki qism nomini yozing — barcha do'konlardagi ochiq narxlarni topaman.",
        "none": "Hech narsa topilmadi. Boshqacha yozib ko'ring (masalan: RTX 4060, Ryzen 5 7600).",
        "shops": "do'konda",
        "price": "so'm",
        "view": "Ko'rish",
        "alert": "Narx tushsa xabar ber",
        "alert_on": "Yoqildi: narx tushsa xabar beraman (kuniga ko'pi bilan 1 marta).",
        "alert_off": "Bekor qilindi.",
        "alerts_none": "Faol ogohlantirish yo'q.",
        "cancel": "Bekor qilish",
        "drop": "Narx tushdi",
    },
    "ru": {
        "hello": "Здравствуйте! Напишите название компьютера или комплектующего — найду цены магазинов.",
        "none": "Ничего не найдено. Попробуйте иначе (например: RTX 4060, Ryzen 5 7600).",
        "shops": "магазинах",
        "price": "сум",
        "view": "Смотреть",
        "alert": "Сообщить о снижении цены",
        "alert_on": "Включено: сообщу, если цена снизится (не чаще раза в день).",
        "alert_off": "Отменено.",
        "alerts_none": "Активных уведомлений нет.",
        "cancel": "Отменить",
        "drop": "Цена снизилась",
    },
}


class GlobalBotClient(Protocol):
    async def send(self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> bool:
        """`False` — xaridor botni bloklagan (403)."""
        ...


class HttpGlobalBotClient:
    def __init__(self, token: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"

    async def send(self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> bool:
        body: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if buttons:
            body["reply_markup"] = {"inline_keyboard": buttons}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self._url, json=body)
        except httpx.HTTPError:
            logger.warning("global_bot.send_failed")
            return True  # vaqtincha xato — keyingi safar
        return response.status_code != 403


@dataclass
class FakeGlobalBotClient:
    sent: list[tuple[int, str, list[list[dict[str, str]]] | None]] = field(default_factory=list)
    blocked: set[int] = field(default_factory=set)

    async def send(self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> bool:
        if chat_id in self.blocked:
            return False
        self.sent.append((chat_id, text, buttons))
        return True


def _money(minor: int | None, words: dict[str, str]) -> str:
    return f"{minor // 100:,}".replace(",", " ") + f" {words['price']}" if minor else "—"


class GlobalBotService:
    def __init__(self, port: NetworkQueryPortImpl, site_url: str, bot_username: str | None) -> None:
        self.port = port
        self.site_url = site_url.rstrip("/")
        self.bot_username = bot_username
        self.client: GlobalBotClient | None = None

    def connect(self, client: GlobalBotClient | None) -> None:
        self.client = client

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def handle(self, database: Database, update: dict[str, Any]) -> None:
        assert self.client is not None
        message = update.get("message") or {}
        callback = update.get("callback_query") or {}
        chat = (message.get("chat") or (callback.get("message") or {}).get("chat") or {}) if update else {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int) or chat.get("type", "private") != "private":
            return
        sender = message.get("from") or callback.get("from") or {}
        lang = "ru" if str(sender.get("language_code") or "").startswith("ru") else "uz"
        words = TEXTS[lang]
        async with database.transaction() as db:
            ref = await self._chat(db, chat_id, lang)
            text = str(message.get("text") or "").strip()[:200]
            data = str(callback.get("data") or "")
            if data.startswith("alert:") or text.startswith("/start alert_"):
                raw = data.removeprefix("alert:") if data else text.removeprefix("/start alert_")
                reply = await self._alert_on(db, ref, raw, words)
                await self.client.send(chat_id, reply)
                return
            if data.startswith("cancel:"):
                await self._alert_off(db, ref, data.removeprefix("cancel:"))
                await self.client.send(chat_id, words["alert_off"])
                return
            if text in ("/alerts", "/ogohlantirishlar"):
                await self._list_alerts(db, ref, chat_id, words)
                return
            if not text or text.startswith("/"):
                await self.client.send(chat_id, words["hello"])
                return
            results = await self.port.search(
                db, q=text, category=None, max_price_uzs_minor=None, in_stock=False, sort="relevance", limit=5
            )
        if not results:
            await self.client.send(chat_id, words["none"])
            return
        for r in results:
            line = f"{r.title}\n{_money(r.min_price_uzs_minor, words)} · {r.offers_count} {words['shops']}"
            buttons: list[list[dict[str, str]]] = []
            if r.canonical_id:
                buttons.append([{"text": words["view"], "url": f"{self.site_url}/p/{r.canonical_id}"}])
                buttons.append([{"text": words["alert"], "callback_data": f"alert:{r.canonical_id}"}])
            await self.client.send(chat_id, line, buttons or None)

    async def check_alerts(self, database: Database) -> int:
        """Rejali ish: narx tushgan va 24 soat o'tgan ogohlantirishlar (BL-103) — yuborilgan xabarlar soni."""
        if self.client is None:
            return 0
        sent = 0
        async with database.transaction() as db:
            alerts = list(
                (
                    await db.execute(select(PriceAlert).where(PriceAlert.status == "ACTIVE").limit(5000))
                ).scalars()
            )
            now = utcnow()
            for alert in alerts:
                if alert.last_notified_at is not None and now - alert.last_notified_at < ALERT_EVERY:
                    continue
                product = await self.port.product(db, alert.canonical_id)
                prices = [o.price_uzs_minor for o in product.offers if o.price_uzs_minor] if product else []
                if not prices or product is None:
                    continue
                low = min(prices)
                if alert.baseline_price_uzs_minor is None or low >= alert.baseline_price_uzs_minor:
                    if alert.baseline_price_uzs_minor is None:
                        alert.baseline_price_uzs_minor = low
                    continue
                chat = await db.get(GlobalBotChat, alert.chat_ref)
                if chat is None or chat.blocked_at is not None:
                    continue
                words = TEXTS.get(chat.language or "uz", TEXTS["uz"])
                text = (
                    f"{words['drop']}: {product.title}\n"
                    f"{_money(alert.baseline_price_uzs_minor, words)} → {_money(low, words)}"
                )
                ok = await self.client.send(
                    int(chat.chat_id_enc),
                    text,
                    [
                        [{"text": words["view"], "url": f"{self.site_url}/p/{alert.canonical_id}"}],
                        [{"text": words["cancel"], "callback_data": f"cancel:{alert.id}"}],
                    ],
                )
                if not ok:
                    chat.blocked_at = now
                    continue
                alert.baseline_price_uzs_minor, alert.last_notified_at = low, now
                sent += 1
        return sent

    # ------------------------------------------------------------------ yordamchilar
    async def _chat(self, db: AsyncSession, chat_id: int, lang: str) -> GlobalBotChat:
        digest = search_hmac(f"global-bot:{chat_id}")
        chat = (
            await db.execute(select(GlobalBotChat).where(GlobalBotChat.chat_hash == digest))
        ).scalar_one_or_none()
        if chat is None:
            chat = GlobalBotChat(chat_hash=digest, chat_id_enc=str(chat_id), language=lang)
            db.add(chat)
            await db.flush()
        chat.blocked_at = None  # yozdi — demak bloklamagan
        return chat

    async def _alert_on(self, db: AsyncSession, chat: GlobalBotChat, raw: str, words: dict[str, str]) -> str:
        try:
            canonical_id = UUID(raw)
        except ValueError:
            return words["none"]
        product = await self.port.product(db, canonical_id)
        if product is None:
            return words["none"]
        prices = [o.price_uzs_minor for o in product.offers if o.price_uzs_minor]
        alert = (
            await db.execute(
                select(PriceAlert).where(
                    PriceAlert.chat_ref == chat.id, PriceAlert.canonical_id == canonical_id
                )
            )
        ).scalar_one_or_none()
        if alert is None:
            alert = PriceAlert(chat_ref=chat.id, canonical_id=canonical_id)
            db.add(alert)
        alert.status, alert.baseline_price_uzs_minor = "ACTIVE", min(prices) if prices else None
        await db.flush()
        return f"{words['alert_on']}\n{product.title}"

    async def _alert_off(self, db: AsyncSession, chat: GlobalBotChat, raw: str) -> None:
        try:
            alert_id = UUID(raw)
        except ValueError:
            return
        alert = await db.get(PriceAlert, alert_id)
        if alert is not None and alert.chat_ref == chat.id:  # faqat o'zining ogohlantirishi
            alert.status = "CANCELLED"

    async def _list_alerts(
        self, db: AsyncSession, chat: GlobalBotChat, chat_id: int, words: dict[str, str]
    ) -> None:
        assert self.client is not None
        alerts = list(
            (
                await db.execute(
                    select(PriceAlert).where(PriceAlert.chat_ref == chat.id, PriceAlert.status == "ACTIVE")
                )
            ).scalars()
        )
        if not alerts:
            await self.client.send(chat_id, words["alerts_none"])
            return
        for alert in alerts[:20]:
            product = await self.port.product(db, alert.canonical_id)
            title = product.title if product else str(alert.canonical_id)
            await self.client.send(
                chat_id,
                f"{title}\n{_money(alert.baseline_price_uzs_minor, words)}",
                [[{"text": words["cancel"], "callback_data": f"cancel:{alert.id}"}]],
            )
