"""Platforma paneli: shoplarni yaratish va holatlarini boshqarish (11 §9.10, DEC-122).

Platforma jamoasi shopning ichki ma'lumotini (suhbatlar, savdo) ko'rmaydi — faqat holat va meta.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.platform.shops.schemas import ReasonIn, ShopCreatedOut, ShopCreateIn, ShopList, ShopOut
from app.platform.shops.services.shop_service import ShopService
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.platform.staff.infrastructure.providers import shop_service
from app.platform.staff.schemas import LinkOut
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/shops", tags=["platform"])

Shops = Annotated[ShopService, Depends(shop_service)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]


CanCreate = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.create"))]
CanView = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.view_meta"))]
CanActivate = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.activate"))]
CanSuspend = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.suspend"))]
CanClose = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.close"))]
CanResetPassword = Annotated[
    RequestContext, Depends(require_platform_permission("platform.member.password_reset"))
]


@router.post("", response_model=ShopCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_shop(body: ShopCreateIn, ctx: CanCreate, svc: Shops, key: IdemKey) -> Any:
    async def replay(saved: Any) -> ShopCreatedOut:
        # Ega havolasi bazada saqlanmagan — takroriy so'rovga yangisi (eskisi bekor)
        shop_id, owner_id = UUID(saved["shop"]["id"]), UUID(saved["owner_membership_id"])
        link = await svc.owner_invite_link(ctx.db, ctx.actor, shop_id, owner_id)
        return ShopCreatedOut(
            shop=await svc.get_shop(ctx.db, shop_id), owner_membership_id=owner_id, owner_invite=link
        )

    return await run_idempotent(
        ctx.db,
        None,
        "platform.shop.create",
        key,
        body,
        lambda: svc.create_shop(ctx.db, ctx.actor, body),
        stored=lambda out: {"shop": out.shop, "owner_membership_id": out.owner_membership_id},
        on_replay=replay,
        status=201,
    )


@router.get("", response_model=ShopList)
async def list_shops(ctx: CanView, svc: Shops, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> ShopList:
    return ShopList(items=await svc.list_shops(ctx.db, limit))


@router.get("/{shop_id}", response_model=ShopOut)
async def get_shop(shop_id: UUID, ctx: CanView, svc: Shops) -> ShopOut:
    return await svc.get_shop(ctx.db, shop_id)


async def _transition(
    ctx: RequestContext, svc: ShopService, key: str, shop_id: UUID, command: str, reason: str | None
) -> Any:
    body = {"reason": reason} if reason else None
    return await run_idempotent(
        ctx.db, None, f"platform.shop.{command.lower()}:{shop_id}", key, body,
        lambda: svc.platform_transition(ctx.db, ctx.actor, shop_id, command, reason),
    )  # fmt: skip


@router.post("/{shop_id}/activate", response_model=ShopOut)
async def activate_shop(shop_id: UUID, ctx: CanActivate, svc: Shops, key: IdemKey) -> Any:
    return await _transition(ctx, svc, key, shop_id, "ACTIVATE", None)


@router.post("/{shop_id}/suspend", response_model=ShopOut)
async def suspend_shop(shop_id: UUID, body: ReasonIn, ctx: CanSuspend, svc: Shops, key: IdemKey) -> Any:
    return await _transition(ctx, svc, key, shop_id, "SUSPEND", body.reason)


@router.post("/{shop_id}/reactivate", response_model=ShopOut)
async def reactivate_shop(shop_id: UUID, body: ReasonIn, ctx: CanActivate, svc: Shops, key: IdemKey) -> Any:
    return await _transition(ctx, svc, key, shop_id, "REACTIVATE", body.reason)


@router.post("/{shop_id}/close", response_model=ShopOut)
async def close_shop(shop_id: UUID, body: ReasonIn, ctx: CanClose, svc: Shops, key: IdemKey) -> Any:
    return await _transition(ctx, svc, key, shop_id, "CLOSE", body.reason)


@router.post("/{shop_id}/members/{membership_id}/password-reset", response_model=LinkOut)
async def owner_password_reset(
    shop_id: UUID, membership_id: UUID, ctx: CanResetPassword, svc: Shops, _: IdemKey
) -> LinkOut:
    return await svc.member_password_reset(ctx.db, ctx.actor, shop_id, membership_id)
