"""Shop paneli: "Shop sayti" — sozlamalar, sahifalar, ochish/yopish, ko'rib chiqish (storefront.md §1)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from app.domains.storefront import permissions as perm
from app.domains.storefront.providers import StorefrontServices, storefront_services
from app.domains.storefront.schemas import (
    PageKind,
    PageList,
    PageOut,
    PageUpdate,
    PreviewTokenOut,
    SiteOut,
    SiteUpdate,
)
from app.platform.shops.models.orm import Shop
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, result_field
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/storefront", tags=["storefront"])

Storefront = Annotated[StorefrontServices, Depends(storefront_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.SITE_VIEW))]
CanEdit = Annotated[RequestContext, Depends(require_permission(perm.SITE_EDIT))]


def _with_etag(response: Response, result: Any) -> Any:
    response.headers["ETag"] = etag(int(result_field(result, "version")))
    return result


@router.get("", response_model=SiteOut)
async def get_site(response: Response, ctx: CanView, svc: Storefront) -> SiteOut:
    """Sayt sozlamalari, holati va xaridor nima ko'rishi (`state`). Saqlanmagan bo'lsa — `version: 0`."""
    return _with_etag(response, await svc.sites.get(ctx.db, ctx.actor))  # type: ignore[no-any-return]


@router.patch("", response_model=SiteOut)
async def update_site(
    body: SiteUpdate, response: Response, ctx: CanEdit, svc: Storefront, version: IfMatch
) -> SiteOut:
    """Faqat ega. Yuborilmagan maydon o'zgarmaydi. Birinchi saqlash — `If-Match: "v0"`."""
    result = await svc.sites.update(ctx.db, ctx.actor, version, body)
    return _with_etag(response, result)  # type: ignore[no-any-return]


async def _transition(
    ctx: RequestContext, svc: StorefrontServices, command: str, key: str, version: int
) -> Any:
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"storefront.site.{command.lower()}",
        key,
        {"version": version},
        lambda: svc.sites.transition(ctx.db, ctx.actor, command, version),
    )


@router.post("/publish", response_model=SiteOut)
async def publish_site(
    response: Response, ctx: CanEdit, svc: Storefront, key: IdemKey, version: IfMatch
) -> Any:
    """Qoralama → Ochiq. Telefon majburiy. Shop hali faol bo'lmasa, xaridor ko'rmaydi ("tez orada")."""
    return _with_etag(response, await _transition(ctx, svc, "PUBLISH", key, version))


@router.post("/pause", response_model=SiteOut)
async def pause_site(
    response: Response, ctx: CanEdit, svc: Storefront, key: IdemKey, version: IfMatch
) -> Any:
    """Ochiq → Vaqtincha yopilgan: xaridor "vaqtincha ishlamayapti" ko'radi, buyurtma qabul qilinmaydi."""
    return _with_etag(response, await _transition(ctx, svc, "PAUSE", key, version))


@router.post("/resume", response_model=SiteOut)
async def resume_site(
    response: Response, ctx: CanEdit, svc: Storefront, key: IdemKey, version: IfMatch
) -> Any:
    return _with_etag(response, await _transition(ctx, svc, "RESUME", key, version))


@router.post("/preview", response_model=PreviewTokenOut)
async def create_preview(ctx: CanView, svc: Storefront, key: IdemKey) -> Any:
    """Saytni xaridor ko'rganidek ko'rish — 30 daqiqalik imzoli havola (bazada saqlanmaydi).
    Takroriy so'rovga yangi havola beriladi: token idempotency jadvaliga yozilmaydi."""
    shop = await ctx.db.get(Shop, ctx.actor.shop_id)
    assert shop is not None

    async def issue() -> PreviewTokenOut:
        return svc.sites.preview_token(ctx.actor, shop.slug)

    async def replay(_saved: Any) -> PreviewTokenOut:
        return await issue()

    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "storefront.site.preview",
        key,
        None,
        issue,
        stored=lambda _out: {"issued": True},
        on_replay=replay,
    )


@router.get("/pages", response_model=PageList)
async def list_pages(ctx: CanView, svc: Storefront) -> PageList:
    """Uchala tayyor sahifa; yozilmagani — standart sarlavha va `version: 0`."""
    return await svc.sites.pages(ctx.db, ctx.actor)


@router.put("/pages/{kind}", response_model=PageOut)
async def save_page(
    kind: PageKind, body: PageUpdate, response: Response, ctx: CanEdit, svc: Storefront, version: IfMatch
) -> PageOut:
    """Faqat ega. Markdown; HTML qabul qilinmaydi. Birinchi saqlash — `If-Match: "v0"`."""
    return _with_etag(  # type: ignore[no-any-return]
        response, await svc.sites.save_page(ctx.db, ctx.actor, kind, version, body)
    )
