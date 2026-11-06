"""Sayt chati (anonim mehmon) — `/api/v1/storefront/{slug}/chat/*` (S2-01, 13 §8).

Sayt faqat `LIVE` bo'lsa (ko'rib chiqish rejimida emas) va shopda sayt chati yoqilgan bo'lsa. Sessiya tokeni
`X-Chat-Session` sarlavhasida — sayt ilovasi uni o'z domenidagi httpOnly cookie'dan uzatadi (4-qaror).
Chegaralar (08 §5): sessiya — IP bo'yicha soatiga 10 ta; xabar — IP bo'yicha daqiqasiga 20 ta va sessiya
bo'yicha daqiqasiga 10 ta; o'qish (polling) — IP + sessiya bo'yicha daqiqasiga 120 ta (4 s polling ≈ 15/daq;
bitta NAT ortidagi bir nechta mehmon bir-birini to'smaydi, QA 5b kuzatuv).

Mehmon tili — `X-Customer-Locale` (sayt serveri `cos.locale` cookie'sidan) yoki `Accept-Language`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.domains.messaging.common import sha256
from app.domains.messaging.providers import MessagingServices, messaging_services
from app.domains.messaging.schemas import (
    ChatContactIn,
    ChatMessagesOut,
    ChatSendIn,
    ChatSendOut,
    ChatSessionOut,
)
from app.shared.client_ip import client_ip
from app.shared.contracts.storefront import ensure_open
from app.shared.db.session import Database
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(prefix="/chat", tags=["storefront_chat"])

Messaging = Annotated[MessagingServices, Depends(messaging_services)]
SessionToken = Annotated[str | None, Header(alias="X-Chat-Session", max_length=100)]

SESSIONS_PER_HOUR = 10
SENDS_PER_MINUTE_IP = 20
SENDS_PER_MINUTE_SESSION = 10
READS_PER_MINUTE = 120
_LOCALES = ("uz", "ru", "en")


def visitor_locale(request: Request) -> str | None:
    """Sayt tili: sayt serveri yuborgan `X-Customer-Locale`, bo'lmasa `Accept-Language` ning birinchi tili."""
    explicit = (request.headers.get("x-customer-locale") or "").strip().lower()[:2]
    if explicit in _LOCALES:
        return explicit
    for part in (request.headers.get("accept-language") or "").split(",")[:5]:
        code = part.split(";", 1)[0].strip().lower()[:2]
        if code in _LOCALES:
            return code
    return None


async def _limit(request: Request, key: str, limit: int, window: int = 60) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, key, limit, window)


@router.post("/sessions", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED)
async def create_chat_session(slug: str, request: Request, svc: Messaging) -> ChatSessionOut:
    """Yangi mehmon sessiyasi. Token faqat shu javobda — sayt serveri cookie'ga yozadi."""
    await _limit(request, f"sf-chat-session:{client_ip(request)}:{slug[:63]}", SESSIONS_PER_HOUR, 3600)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)
        ensure_open(access, for_order=True)
        return await svc.webchat.create_session(db, access)


@router.get("/messages", response_model=ChatMessagesOut)
async def poll_chat_messages(
    slug: str,
    request: Request,
    response: Response,
    svc: Messaging,
    token: SessionToken = None,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> ChatMessagesOut:
    """Yangi xabarlar `after_seq` dan keyin (polling, `poll_interval_seconds`). Sessiya yo'q yoki eskirgan —
    404: mehmon yangi sessiya oladi."""
    session_key = sha256(token)[:24] if token else "none"
    await _limit(request, f"sf-chat-read:{client_ip(request)}:{slug[:63]}:{session_key}", READS_PER_MINUTE)
    response.headers["Cache-Control"] = "no-store"
    database: Database = request.app.state.db
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)
        ensure_open(access, for_order=True)
        return await svc.webchat.messages(db, access, token, after_seq)


@router.post("/messages", response_model=ChatSendOut, status_code=status.HTTP_201_CREATED)
async def send_chat_message(
    slug: str, body: ChatSendIn, request: Request, svc: Messaging, token: SessionToken = None
) -> ChatSendOut:
    """Mehmon xabari. `client_message_id` takror himoyasi: tarmoq uzilib qayta yuborilsa — bitta xabar."""
    await _limit(request, f"sf-chat-send:{client_ip(request)}:{slug[:63]}", SENDS_PER_MINUTE_IP)
    if token:
        await _limit(request, f"sf-chat-send-s:{sha256(token)[:24]}", SENDS_PER_MINUTE_SESSION)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)
        ensure_open(access, for_order=True)
        return await svc.webchat.send(
            db, access, token, body.client_message_id, body.body, visitor_locale(request)
        )


@router.post("/contact", status_code=status.HTTP_204_NO_CONTENT)
async def save_chat_contact(
    slug: str, body: ChatContactIn, request: Request, svc: Messaging, token: SessionToken = None
) -> None:
    """Mehmon ismi va telefoni (rozilik bilan). Telefon shifrlangan saqlanadi, operator suhbatda ko'radi."""
    await _limit(request, f"sf-chat-send:{client_ip(request)}:{slug[:63]}", SENDS_PER_MINUTE_IP)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)
        ensure_open(access, for_order=True)
        await svc.webchat.contact(db, access, token, body.name, body.phone)
