"""Realtime (08 §6, ADR-023): bir martalik ticket va xodim WebSocket'i.

    POST /api/v1/auth/ws-ticket  (Bearer)  → {"ticket": "...", "expires_in": 30, "path": "/api/v1/ws"}
                                             shop yoki platforma tokeni (6c: platforma paneli — kanal
                                             principal_id bo'yicha, masalan `ai_eval.run.changed`)
    WS   /api/v1/ws?ticket=...             → {"type": "hello", "seq": 41, "heartbeat_seconds": 25}
                                             {"type": "order.changed", "resource": {...}, "seq": 42, ...}
                                             {"type": "ping"}  (har heartbeat'da)

JWT URL'da yuborilmaydi — faqat 30 soniyalik bir martalik ticket (Redis db2, xeshi bilan).
Ulanish har heartbeat'da BAZADAN qayta tekshiriladi: sessiya bekor qilinsa yoki xodim o'chirilsa — `4401`,
shop yopilsa — `4403`. Signalda matn va xaridor ma'lumoti yo'q; bo'shliq bo'lsa (seq sakradi) klient
ro'yxatlarni REST'dan qayta yuklaydi.

Cheklovlar (QA 5a F11, I1):
- ticket — xodimga daqiqasiga 30 ta;
- bir xodimda bir vaqtda ko'pi bilan 5 ta ulanish; oshsa YANGI ulanish `4429` bilan yopiladi (eski tablar
  ishlab turadi, klient uzoqroq kutib qayta urinadi);
- `Origin` sarlavhasi bo'lsa, panel manzillaridan biri bo'lishi shart (aks holda handshake rad etiladi —
  1008). Sarlavhasiz (brauzer emas) mijoz — ruxsat: u baribir Bearer bilan olingan ticket'ga muhtoj.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from uuid import UUID

import structlog
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.platform.auth.tokens import AccessClaims, hash_token
from app.platform.staff.infrastructure.guard import AnyContext, resolve_platform_actor, resolve_shop_actor
from app.shared.db.session import Database
from app.shared.errors.base import ShopNotActiveError, UnauthenticatedError
from app.shared.ratelimit import enforce
from app.shared.realtime import RealtimeBroker
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

TICKET_TTL_SECONDS = 30
TICKETS_PER_MINUTE = 30
MAX_SOCKETS_PER_MEMBER = 5
CLOSE_UNAUTHENTICATED = 4401
CLOSE_SHOP_CLOSED = 4403
CLOSE_TOO_MANY = 4429
CLOSE_POLICY = 1008  # Origin ruxsat etilmagan — handshake rad etiladi

ticket_router = APIRouter(tags=["auth"])
ws_router = APIRouter()


class WsTicketOut(BaseModel):
    ticket: str
    expires_in: int
    path: str


@ticket_router.post("/ws-ticket", response_model=WsTicketOut)
async def ws_ticket(request: Request, response: Response, ctx: AnyContext) -> WsTicketOut:
    """Shop paneli (a'zolik kanali) va platforma paneli (principal kanali, 6c)."""
    broker: RealtimeBroker = request.app.state.realtime
    await enforce(request.app.state.rate_limiter, f"ws-ticket:{ctx.actor.actor_id}", TICKETS_PER_MINUTE)
    ticket = secrets.token_urlsafe(32)
    session_id: UUID = request.state.session_id
    await broker.put_ticket(
        hash_token(ticket),
        {
            "principal_id": str(ctx.actor.actor_id),
            "session_id": str(session_id),
            "shop_id": str(ctx.actor.shop_id) if ctx.actor.shop_id else "",
            "audience": "platform" if ctx.actor.surface == "platform" else "shop",
        },
        TICKET_TTL_SECONDS,
    )
    response.headers["Cache-Control"] = "no-store"
    return WsTicketOut(ticket=ticket, expires_in=TICKET_TTL_SECONDS, path="/api/v1/ws")


async def _actor(websocket: WebSocket, claims: AccessClaims) -> ActorContext | int:
    """Faol xodim — ActorContext; aks holda yopish kodi."""
    database: Database = websocket.app.state.db
    try:
        async with database.transaction() as db:
            if claims.audience == "platform":
                return await resolve_platform_actor(db, claims)
            return await resolve_shop_actor(db, claims, websocket.app.state.permissions)
    except ShopNotActiveError:
        return CLOSE_SHOP_CLOSED
    except UnauthenticatedError:
        return CLOSE_UNAUTHENTICATED


async def _drain(websocket: WebSocket) -> None:
    """Klient xabarlari (pong) e'tiborsiz; uzilsa — tugaydi."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        return True  # brauzer emas — ticket baribir Bearer token bilan olingan
    allowed: list[str] = getattr(websocket.app.state, "ws_allowed_origins", [])
    return origin.rstrip("/") in allowed


@ws_router.websocket("/ws")
async def realtime_socket(websocket: WebSocket) -> None:
    broker: RealtimeBroker = websocket.app.state.realtime
    heartbeat: float = websocket.app.state.realtime_heartbeat_seconds
    if not _origin_allowed(websocket):
        await websocket.close(code=CLOSE_POLICY)  # accept'dan oldin — handshake 403
        return
    ticket = websocket.query_params.get("ticket", "")
    data = await broker.take_ticket(hash_token(ticket)) if 16 <= len(ticket) <= 128 else None
    await websocket.accept()
    if data is None:
        await websocket.close(code=CLOSE_UNAUTHENTICATED)
        return
    platform = data.get("audience") == "platform"
    claims = AccessClaims(
        principal_id=UUID(data["principal_id"]),
        session_id=UUID(data["session_id"]),
        shop_id=UUID(data["shop_id"]) if data.get("shop_id") else None,
        audience="platform" if platform else "shop",
    )
    actor = await _actor(websocket, claims)
    channel = (actor.actor_id if platform else actor.membership_id) if not isinstance(actor, int) else None
    if isinstance(actor, int) or channel is None:
        await websocket.close(code=actor if isinstance(actor, int) else CLOSE_UNAUTHENTICATED)
        return
    member, conn_id = channel, secrets.token_hex(8)
    if not await broker.claim_socket(
        member, conn_id, now=time.time(), stale_after=heartbeat * 3, limit=MAX_SOCKETS_PER_MEMBER
    ):
        await websocket.close(code=CLOSE_TOO_MANY)
        return
    try:
        await _serve(websocket, broker, claims, member, conn_id, heartbeat)
    finally:
        await broker.release_socket(member, conn_id)


async def _serve(
    websocket: WebSocket,
    broker: RealtimeBroker,
    claims: AccessClaims,
    member: UUID,
    conn_id: str,
    heartbeat: float,
) -> None:
    subscription = await broker.subscribe(member)
    receiver = asyncio.create_task(_drain(websocket))
    loop = asyncio.get_running_loop()
    try:
        await websocket.send_json(
            {"type": "hello", "seq": await broker.current_seq(member), "heartbeat_seconds": heartbeat}
        )
        next_check = loop.time() + heartbeat
        while not receiver.done():
            wait = min(1.0, max(0.05, next_check - loop.time()))
            message = await subscription.next(wait)
            if message is not None:
                await websocket.send_json(message)
            if loop.time() >= next_check:
                verdict = await _actor(websocket, claims)
                if isinstance(verdict, int):
                    await websocket.close(code=verdict)
                    return
                await broker.touch_socket(member, conn_id, now=time.time())
                await websocket.send_json({"type": "ping"})
                next_check = loop.time() + heartbeat
    except (WebSocketDisconnect, RuntimeError):
        pass  # klient uzildi
    finally:
        receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await receiver
        await subscription.close()
