"""Kanal webhook'lari — `/api/v1/webhooks/*` (13 §3, 10 §2: shop faqat URL'dagi `account_ref` dan).

Telegram: `X-Telegram-Bot-Api-Secret-Token` — akkaunt sirining xeshi bilan doimiy vaqtda solishtiriladi;
noto'g'ri yoki noma'lum akkaunt — 404. Javob doim tez va 200 (Telegram xato javobda qayta-qayta yuboradi);
og'ir ish (rasm yuklash, yuborish) — fon vazifasida. Xom payload va matn logga tushmaydi.
Instagram — DEC-116a flag o'chiq bo'lsa yo'q (404).
"""

from __future__ import annotations

import hmac
import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse

from app.domains.messaging.channels.instagram import parse_webhook, verify_signature
from app.domains.messaging.channels.telegram import parse_update
from app.domains.messaging.common import sha256
from app.domains.messaging.providers import MessagingServices, messaging_services
from app.shared.db.session import Database
from app.shared.errors.base import NotFoundError

router = APIRouter(tags=["webhooks"])
logger = structlog.get_logger(__name__)

Messaging = Annotated[MessagingServices, Depends(messaging_services)]
MAX_BODY = 1024 * 1024


@router.post("/telegram/{account_ref}")
async def telegram_webhook(
    account_ref: str,
    request: Request,
    svc: Messaging,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token", max_length=256)] = None,
) -> dict[str, bool]:
    database: Database = request.app.state.db
    raw = await request.body()
    try:
        update = json.loads(raw) if len(raw) <= MAX_BODY else None
    except ValueError:
        update = None
    async with database.transaction() as db:
        account = await svc.channels.resolve_by_ref(db, "TELEGRAM", account_ref)
        expected = account.webhook_secret_hash if account is not None else None
        if account is None or not expected or not secret or not hmac.compare_digest(sha256(secret), expected):
            raise NotFoundError("Not found")
        try:
            inbound = parse_update(update) if isinstance(update, dict) else None
        except (TypeError, ValueError, KeyError, AttributeError):
            # Buzuq update — e'tiborsiz (200): Telegram 500 da qayta-qayta yuboraveradi (QA 5b L1)
            logger.warning("telegram.update_unparseable")
            inbound = None
        if inbound is None:
            return {"ok": True}
        result = await svc.inbound.ingest(db, account, inbound)
    logger.info("telegram.webhook", duplicate=result.duplicate, ignored=result.ignored)
    return {"ok": True}


@router.get("/instagram", response_class=PlainTextResponse)
async def instagram_verify(
    svc: Messaging,
    mode: Annotated[str | None, Query(alias="hub.mode", max_length=32)] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token", max_length=256)] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge", max_length=256)] = None,
) -> str:
    """Meta webhook obunasi tasdig'i (`hub.challenge` qaytariladi)."""
    expected = svc.config.instagram_verify_token
    if (
        not svc.config.instagram_enabled
        or not expected
        or mode != "subscribe"
        or not token
        or not hmac.compare_digest(token.encode(), expected.encode())
        or not challenge
    ):
        raise NotFoundError("Not found")
    return challenge


@router.post("/instagram")
async def instagram_webhook(
    request: Request,
    svc: Messaging,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256", max_length=256)] = None,
) -> dict[str, bool]:
    secret = svc.config.instagram_app_secret
    if not svc.config.instagram_enabled or not secret:
        raise NotFoundError("Not found")
    raw = await request.body()
    if len(raw) > MAX_BODY or not verify_signature(secret, raw, signature):
        raise NotFoundError("Not found")
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"ok": True}
    database: Database = request.app.state.db
    for account_id, inbound in parse_webhook(payload) if isinstance(payload, dict) else []:
        async with database.transaction() as db:
            account = await svc.channels.by_external(db, "INSTAGRAM", account_id)
            if account is not None:
                await svc.inbound.ingest(db, account, inbound)
    return {"ok": True}
