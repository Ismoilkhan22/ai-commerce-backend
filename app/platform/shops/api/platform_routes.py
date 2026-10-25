"""Platforma paneli: shoplarni yaratish va holatlarini boshqarish (11 §9.10, DEC-122).

Platforma jamoasi shopning ichki ma'lumotini (suhbatlar, savdo) ko'rmaydi — faqat holat va meta.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.platform.shops.platform_schemas import (
    ActivityList,
    PlatformShopUpdate,
    ShopList,
    ShopMemberList,
    ShopNoteIn,
    ShopNoteList,
    ShopNoteOut,
    ShopSort,
    TransitionList,
)
from app.platform.shops.schemas import (
    BranchList,
    PlatformShopOut,
    ReasonIn,
    ShopCreatedOut,
    ShopCreateIn,
    ShopOut,
    ShopStatus,
)
from app.platform.shops.services.platform_queries import PlatformQueryService
from app.platform.shops.services.shop_service import ShopService
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.platform.staff.infrastructure.providers import platform_queries, shop_service
from app.platform.staff.schemas import LinkOut
from app.shared.http import etag, require_if_match
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/shops", tags=["platform"])

Shops = Annotated[ShopService, Depends(shop_service)]
Queries = Annotated[PlatformQueryService, Depends(platform_queries)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


CanCreate = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.create"))]
CanView = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.view_meta"))]
CanActivate = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.activate"))]
CanSuspend = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.suspend"))]
CanClose = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.close"))]
CanEdit = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.edit"))]
CanNote = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.note"))]
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
async def list_shops(
    ctx: CanView,
    queries: Queries,
    q: Annotated[str | None, Query(max_length=100, description="Nomi, slug, STIR yoki ega telefoni")] = None,
    status: Annotated[list[ShopStatus] | None, Query()] = None,
    sort: ShopSort = "created_desc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> ShopList:
    return await queries.list_shops(ctx.db, q=q, statuses=status or [], sort=sort, limit=limit, offset=offset)


@router.get("/{shop_id}", response_model=PlatformShopOut)
async def get_shop(shop_id: UUID, response: Response, ctx: CanView, svc: Shops) -> PlatformShopOut:
    shop = await svc.get_shop(ctx.db, shop_id)
    response.headers["ETag"] = etag(shop.version)
    return shop


@router.patch("/{shop_id}", response_model=PlatformShopOut)
async def update_shop(
    shop_id: UUID, body: PlatformShopUpdate, response: Response, ctx: CanEdit, svc: Shops, version: IfMatch
) -> PlatformShopOut:
    """Shop ma'lumotini tuzatish: sabab majburiy, slug o'zgarmaydi (business/15 §3)."""
    shop = await svc.platform_update(ctx.db, ctx.actor, shop_id, version, body)
    response.headers["ETag"] = etag(shop.version)
    return shop


@router.get("/{shop_id}/members", response_model=ShopMemberList)
async def list_shop_members(shop_id: UUID, ctx: CanView, queries: Queries) -> ShopMemberList:
    return await queries.members(ctx.db, shop_id)


@router.get("/{shop_id}/branches", response_model=BranchList)
async def list_shop_branches(shop_id: UUID, ctx: CanView, queries: Queries) -> BranchList:
    return await queries.branches(ctx.db, shop_id)


@router.get("/{shop_id}/history", response_model=TransitionList)
async def shop_history(shop_id: UUID, ctx: CanView, queries: Queries) -> TransitionList:
    return await queries.history(ctx.db, shop_id)


@router.get("/{shop_id}/audit", response_model=ActivityList)
async def shop_audit(
    shop_id: UUID, ctx: CanView, queries: Queries, limit: Limit = 50, offset: Offset = 0
) -> ActivityList:
    """Shopdagi o'zgarishlar jurnali: kim, nima, nega — qiymatlarsiz, faqat maydon nomlari."""
    return await queries.shop_audit(ctx.db, shop_id, limit, offset)


@router.get("/{shop_id}/notes", response_model=ShopNoteList)
async def shop_notes(shop_id: UUID, ctx: CanView, queries: Queries) -> ShopNoteList:
    """Platformaning ichki izohlari — shop ko'rmaydi (business/15 §3)."""
    return await queries.notes(ctx.db, shop_id)


@router.post("/{shop_id}/notes", response_model=ShopNoteOut, status_code=status.HTTP_201_CREATED)
async def add_shop_note(shop_id: UUID, body: ShopNoteIn, ctx: CanNote, svc: Shops, key: IdemKey) -> Any:
    """Izoh faqat qo'shiladi — tahrirlash va o'chirish yo'q (kim nima yozgani tarix bo'lib qoladi)."""
    return await run_idempotent(
        ctx.db,
        None,
        f"platform.shop.note:{shop_id}",
        key,
        body,
        lambda: svc.add_note(ctx.db, ctx.actor, shop_id, body),
        status=201,
    )


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


@router.post("/{shop_id}/members/{membership_id}/invite", response_model=LinkOut)
async def resend_owner_invite(
    shop_id: UUID, membership_id: UUID, ctx: CanCreate, svc: Shops, _: IdemKey
) -> LinkOut:
    """Ega taklifini qayta berish (muddati o'tgan bo'lsa). Har chaqiruv yangi havola, eskisi bekor."""
    return await svc.owner_invite_link(ctx.db, ctx.actor, shop_id, membership_id)
