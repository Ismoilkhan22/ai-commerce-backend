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
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.domains.messaging.channels.instagram import parse_comment_events, parse_webhook, verify_signature
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


@router.get("/instagram/oauth", include_in_schema=False)
async def instagram_oauth_callback(
    request: Request,
    svc: Messaging,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=2048)] = None,
) -> RedirectResponse:
    """Meta OAuth qaytishi: kod → token → ulash → panelga (`?instagram=connected|error`)."""
    target = await svc.ig.oauth.complete(request.app.state.db, code, state)
    return RedirectResponse(target, status_code=303)


async def _signed_request(request: Request) -> str | None:
    raw = await request.body()
    if len(raw) > 16 * 1024:
        return None
    values = parse_qs(raw.decode("utf-8", "replace")).get("signed_request")
    return values[0] if values else None


@router.post("/instagram/deauthorize", include_in_schema=False)
async def instagram_deauthorize(request: Request, svc: Messaging) -> dict[str, bool]:
    """Meta: foydalanuvchi app'ni o'chirdi — uning ulagan Instagram akkauntlari uziladi."""
    code = await svc.ig.oauth.revoke(request.app.state.db, await _signed_request(request))
    if code is None:
        raise NotFoundError("Not found")
    return {"ok": True}


@router.post("/instagram/data-deletion", include_in_schema=False)
async def instagram_data_deletion(request: Request, svc: Messaging) -> dict[str, str]:
    """Meta "Data deletion request" callback'i: `{url, confirmation_code}` — holat sahifasi va kod."""
    code = await svc.ig.oauth.revoke(request.app.state.db, await _signed_request(request))
    if code is None:
        raise NotFoundError("Not found")
    return {"url": svc.ig.oauth.deletion_status_url(code), "confirmation_code": code}


@router.get("/instagram/data-deletion/{code}", response_class=PlainTextResponse, include_in_schema=False)
async def instagram_data_deletion_status(code: str) -> str:
    if not code.isalnum() or len(code) != 20:
        raise NotFoundError("Not found")
    return (
        f"Data deletion request {code}: completed.\n"
        "Instagram connections authorized by this Facebook account were disconnected and their access "
        "tokens deleted.\n"
    )


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
    if isinstance(payload, dict):  # tuzilma (matnsiz): qaysi hodisa kelgani va nechtasi tanildi
        entries = payload.get("entry") or []
        logger.info(
            "instagram.webhook.received",
            object=payload.get("object"),
            entry_ids=[str(e.get("id")) for e in entries if isinstance(e, dict)],
            messaging_keys=sorted(
                {k for e in entries if isinstance(e, dict) for m in e.get("messaging") or [] for k in m}
            ),
            change_fields=[
                c.get("field") for e in entries if isinstance(e, dict) for c in e.get("changes") or []
            ],
            parsed_messages=len(parse_webhook(payload)),
            parsed_comments=len(parse_comment_events(payload)),
        )
    for account_id, inbound in parse_webhook(payload) if isinstance(payload, dict) else []:
        async with database.transaction() as db:
            account = await svc.channels.by_external(db, "INSTAGRAM", account_id)
            if account is not None:
                await svc.inbound.ingest(db, account, inbound)
    # Izohlar (DEC-148): o'sha manzil, imzo va dedup; har izoh alohida tranzaksiyada
    for account_id, comment in parse_comment_events(payload) if isinstance(payload, dict) else []:
        async with database.transaction() as db:
            account = await svc.channels.by_external(db, "INSTAGRAM", account_id)
            if account is not None:
                await svc.ig.ingest.ingest(db, account, comment)
    return {"ok": True}
