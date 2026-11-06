"""Shop paneli: kanallar — `/api/v1/shop/channels/*` (FSM-03, UAT-M09). Ulash va uzish — faqat ega;
ko'rish — ega va menejer. Token javobda hech qachon qaytmaydi."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.domains.messaging import permissions as perm
from app.domains.messaging.models.orm import ChannelAccount
from app.domains.messaging.providers import MessagingServices, messaging_services
from app.domains.messaging.schemas import (
    ChannelAccountOut,
    ChannelList,
    InstagramConnectIn,
    TelegramConnectIn,
)
from app.domains.messaging.services.channels import account_out
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.errors.base import NotFoundError
from app.shared.http import etag, require_if_match, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/channels", tags=["messaging_channels"])

Messaging = Annotated[MessagingServices, Depends(messaging_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.CHANNEL_VIEW))]
CanConnect = Annotated[RequestContext, Depends(require_permission(perm.CHANNEL_CONNECT))]


async def _replay(ctx: RequestContext, saved: Any) -> ChannelAccountOut:
    return await _get(ctx, UUID(str(saved["id"])))


async def _get(ctx: RequestContext, account_id: UUID) -> ChannelAccountOut:
    row = (
        await ctx.db.execute(
            select(ChannelAccount).where(
                ChannelAccount.shop_id == ctx.actor.shop_id, ChannelAccount.id == account_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Channel not found")
    return account_out(row)


@router.get("", response_model=ChannelList)
async def list_channels(ctx: CanView, svc: Messaging) -> ChannelList:
    """Ulangan va uzilgan kanallar; Telegram rejimi (lokalda polling) va Instagram mavjudmi (DEC-116a)."""
    return await svc.channels.list_accounts(ctx.db, ctx.actor)


@router.get("/{channel_account_id}", response_model=ChannelAccountOut)
async def get_channel(channel_account_id: UUID, response: Response, ctx: CanView) -> ChannelAccountOut:
    out = await _get(ctx, channel_account_id)
    response.headers["ETag"] = etag(out.version)
    return out


@router.post("/telegram", response_model=ChannelAccountOut, status_code=status.HTTP_201_CREATED)
async def connect_telegram(
    body: TelegramConnectIn,
    request: Request,
    response: Response,
    ctx: CanConnect,
    svc: Messaging,
    key: IdemKey,
) -> Any:
    """Shop botini ulash: @BotFather tokeni → tekshiruv (`getMe`) → webhook (prod) yoki polling (lokal).
    Boshqa bot ulangan bo'lsa — eskisi uziladi (REPLACED). Token shifrlangan saqlanadi."""
    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "messaging.channel.telegram",
        key,
        None,  # token takror jadvaliga (xeshi ham) yozilmaydi
        lambda: svc.channels.connect_telegram(ctx.db, ctx.actor, body.token),
        stored=lambda created: {"id": str(created.id)},
        on_replay=lambda saved: _replay(ctx, saved),
        status=status.HTTP_201_CREATED,
    )
    set_location(request, response, "get_channel", channel_account_id=out.id)
    return out


@router.post("/webchat", response_model=ChannelAccountOut, status_code=status.HTTP_201_CREATED)
async def enable_webchat(
    request: Request, response: Response, ctx: CanConnect, svc: Messaging
) -> ChannelAccountOut:
    """Saytdagi chatni yoqish (takrorlash xavfsiz — yoqilgan bo'lsa o'sha qaytadi)."""
    out = await svc.channels.enable_webchat(ctx.db, ctx.actor)
    set_location(request, response, "get_channel", channel_account_id=out.id)
    return out


@router.post("/instagram", response_model=ChannelAccountOut, status_code=status.HTTP_201_CREATED)
async def connect_instagram(
    body: InstagramConnectIn, request: Request, response: Response, ctx: CanConnect, svc: Messaging
) -> ChannelAccountOut:
    """Instagram Direct — Meta ruxsati kelguncha o'chiq (DEC-116a): flag o'chiq bo'lsa 404."""
    out = await svc.channels.connect_instagram(ctx.db, ctx.actor, body.access_token)
    set_location(request, response, "get_channel", channel_account_id=out.id)
    return out


@router.post("/{channel_account_id}/disconnect", response_model=ChannelAccountOut)
async def disconnect_channel(
    channel_account_id: UUID, response: Response, ctx: CanConnect, svc: Messaging, version: IfMatch
) -> ChannelAccountOut:
    """Kanalni uzish: xabar yuborish to'xtaydi; tarix saqlanadi."""
    out = await svc.channels.disconnect(ctx.db, ctx.actor, channel_account_id, version)
    response.headers["ETag"] = etag(out.version)
    return out
