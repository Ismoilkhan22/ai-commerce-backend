"""Platforma botining webhook'i (DEC-129): faqat `/start <kod>` — xodimni botga ulash.

Telegram `X-Telegram-Bot-Api-Secret-Token` sarlavhasini yuboradi (setWebhook `secret_token`); u sozlamadagi
sir bilan doimiy vaqtda solishtiriladi. Sir sozlanmagan bo'lsa — 404 (webhook o'chiq).
Javob doim 200: Telegram xato javobda qayta-qayta yuboradi. Xabar matni logga tushmaydi.
"""

from __future__ import annotations

import hmac
import re
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, Request

from app.platform.notifications.providers import NotificationServices, notification_services
from app.platform.notifications.telegram import TelegramSendError
from app.shared.db.session import Database
from app.shared.errors.base import NotFoundError

router = APIRouter(tags=["webhooks"])
logger = structlog.get_logger(__name__)

Services = Annotated[NotificationServices, Depends(notification_services)]

LINKED_TEXT = "✅ Ulandi. Endi buyurtma va vazifa xabarlari shu yerga keladi. / Подключено. / Connected."
INVALID_TEXT = "Kod noto'g'ri yoki eskirgan. Paneldan yangi kod oling. / Код неверный или устарел."


_INT64 = (-(2**63), 2**63 - 1)
# Aynan "/start <kod>" (bot nomi bilan "/start@bot <kod>" ham); "/startXYZ kod" — yo'q (QA 5a I3)
_START = re.compile(r"/start(?:@[A-Za-z0-9_]{1,64})? +([A-Za-z0-9]{4,32})", re.ASCII)


def _telegram_id(value: Any) -> int | None:
    """Telegram ID — butun son (bool emas: JSON `true` Python'da int), int64 chegarasida."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if _INT64[0] <= value <= _INT64[1] else None


def _start_code(update: dict[str, Any]) -> tuple[str, int, int] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text, chat, sender = message.get("text"), message.get("chat"), message.get("from")
    if not isinstance(text, str) or not isinstance(chat, dict) or not isinstance(sender, dict):
        return None
    if chat.get("type") != "private":
        return None
    match = _START.fullmatch(text.strip())
    user_id, chat_id = _telegram_id(sender.get("id")), _telegram_id(chat.get("id"))
    if match is None or user_id is None or chat_id is None:
        return None
    return match.group(1), user_id, chat_id


@router.post("/platform-telegram")
async def platform_telegram_webhook(
    request: Request,
    svc: Services,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    expected = svc.webhook_secret
    if not expected or not secret or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise NotFoundError("Not found")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    parsed = _start_code(update) if isinstance(update, dict) else None
    if parsed is None:
        return {"ok": True}
    code, user_id, chat_id = parsed
    database: Database = request.app.state.db
    async with database.transaction() as db:
        principal_id = await svc.telegram_link.redeem(db, code, user_id, chat_id)
    logger.info("platform_bot.start", linked=principal_id is not None)
    try:  # javob tranzaksiyadan keyin — tashqi chaqiruv TX ichida emas
        await svc.sender.send_message(chat_id, LINKED_TEXT if principal_id else INVALID_TEXT)
    except TelegramSendError as exc:
        logger.warning("platform_bot.reply_failed", code=exc.code)
    return {"ok": True}
