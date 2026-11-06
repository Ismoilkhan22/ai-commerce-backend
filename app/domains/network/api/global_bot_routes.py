"""M39: global Telegram bot webhook'i — `/api/v1/webhooks/global-telegram` (BL-108, shop botlaridan alohida).

`X-Telegram-Bot-Api-Secret-Token` sozlamadagi sir bilan doimiy vaqtda solishtiriladi; noto'g'ri yoki bot
o'chiq — 404. Javob doim tez va 200 (Telegram xato javobda qayta-qayta yuboradi). Xom update logga tushmaydi.
"""

from __future__ import annotations

import hmac
import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Header, Request

from app.domains.network.services.global_bot import GlobalBotService
from app.shared.errors.base import NotFoundError

router = APIRouter(tags=["webhooks"])
logger = structlog.get_logger(__name__)


@router.post("/global-telegram")
async def global_telegram_webhook(
    request: Request,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token", max_length=256)] = None,
) -> dict[str, bool]:
    bot: GlobalBotService = request.app.state.network.global_bot
    expected: str | None = request.app.state.global_bot_secret
    if not bot.enabled or not expected or not secret or not hmac.compare_digest(secret, expected):
        raise NotFoundError("Not found")
    raw = await request.body()
    try:
        update = json.loads(raw) if len(raw) <= 256 * 1024 else None
    except ValueError:
        update = None
    if isinstance(update, dict):
        try:
            await bot.handle(request.app.state.db, update)
        except Exception:
            logger.exception("global_bot.update_failed")
    return {"ok": True}
