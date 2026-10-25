"""Shop paneli: profil, sozlamalar, filiallar (11 §9.2)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.platform.shops.schemas import (
    BranchIn,
    BranchList,
    BranchOptionList,
    BranchOut,
    PolicyOut,
    PolicyUpdate,
    ShopOut,
    ShopProfileUpdate,
)
from app.platform.shops.services.shop_service import ShopService
from app.platform.staff.infrastructure.guard import RequestContext, ShopContext, require_permission
from app.platform.staff.infrastructure.providers import shop_service
from app.shared.http import etag, require_if_match
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(tags=["shop"])

Shops = Annotated[ShopService, Depends(shop_service)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]


SettingsView = Annotated[RequestContext, Depends(require_permission("shops.settings.view"))]
SettingsEdit = Annotated[RequestContext, Depends(require_permission("shops.settings.edit"))]
PolicyEdit = Annotated[RequestContext, Depends(require_permission("shops.policy.edit"))]
BranchEdit = Annotated[RequestContext, Depends(require_permission("shops.branch.edit"))]


@router.get("/profile", response_model=ShopOut)
async def get_profile(response: Response, ctx: SettingsView, svc: Shops) -> ShopOut:
    shop = await svc.profile(ctx.db, ctx.actor)
    response.headers["ETag"] = etag(shop.version)
    return shop


@router.patch("/profile", response_model=ShopOut)
async def update_profile(
    body: ShopProfileUpdate, response: Response, ctx: SettingsEdit, svc: Shops, version: IfMatch
) -> ShopOut:
    shop = await svc.update_profile(ctx.db, ctx.actor, version, body)
    response.headers["ETag"] = etag(shop.version)
    return shop


@router.post("/profile/submit-for-verification", response_model=ShopOut)
async def submit_for_verification(ctx: SettingsEdit, svc: Shops, key: IdemKey) -> Any:
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "shops.shop.submit",
        key,
        None,
        lambda: svc.submit_for_verification(ctx.db, ctx.actor),
    )


@router.get("/policies", response_model=PolicyOut)
async def get_policies(response: Response, ctx: SettingsView, svc: Shops) -> PolicyOut:
    policy = await svc.policies(ctx.db, ctx.actor)
    response.headers["ETag"] = etag(policy.version)
    return policy


@router.patch("/policies", response_model=PolicyOut)
async def update_policies(
    body: PolicyUpdate, response: Response, ctx: PolicyEdit, svc: Shops, version: IfMatch
) -> PolicyOut:
    policy = await svc.update_policies(ctx.db, ctx.actor, version, body)
    response.headers["ETag"] = etag(policy.version)
    return policy


@router.get("/branches", response_model=BranchList)
async def list_branches(ctx: SettingsView, svc: Shops) -> BranchList:
    return BranchList(items=await svc.branches(ctx.db, ctx.actor))


@router.get("/branches/options", response_model=BranchOptionList)
async def list_branch_options(ctx: ShopContext, svc: Shops) -> BranchOptionList:
    """Filial tanlash uchun (kirim, tez sotuv, buyurtma): har shop xodimiga ochiq — id, nom, holat,
    olib ketish joyi. Manzil va telefon yo'q (to'liq ro'yxat — `GET /branches`, sozlamalar ruxsati bilan)."""
    return BranchOptionList(items=await svc.branch_options(ctx.db, ctx.actor))


@router.post("/branches", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(body: BranchIn, ctx: BranchEdit, svc: Shops, key: IdemKey) -> Any:
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "shops.branch.create",
        key,
        body,
        lambda: svc.create_branch(ctx.db, ctx.actor, body),
        status=201,
    )


@router.patch("/branches/{branch_id}", response_model=BranchOut)
async def update_branch(
    branch_id: UUID, body: BranchIn, response: Response, ctx: BranchEdit, svc: Shops, version: IfMatch
) -> BranchOut:
    branch = await svc.update_branch(ctx.db, ctx.actor, branch_id, version, body)
    response.headers["ETag"] = etag(branch.version)
    return branch


@router.post("/branches/{branch_id}/close", response_model=BranchOut)
async def close_branch(branch_id: UUID, ctx: BranchEdit, svc: Shops, key: IdemKey) -> Any:
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"shops.branch.close:{branch_id}",
        key,
        None,
        lambda: svc.close_branch(ctx.db, ctx.actor, branch_id),
    )
