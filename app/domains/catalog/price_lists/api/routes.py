"""Shop paneli: yetkazib beruvchi narx ro'yxati (DEC-149, 1-qism).

POST /shop/files?purpose=PRICE_LIST (XLSX, CSV, PDF yoki surat) → POST /catalog/price-lists {file_id}
→ GET .../{id} (READING → READY) → PATCH .../{id} (ustama, yaxlitlash), PATCH .../items/{item_id}
→ POST .../{id}/apply
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.domains.catalog.price_lists.schemas import (
    PriceListCreateIn,
    PriceListItemIn,
    PriceListList,
    PriceListOut,
    PriceListSettingsIn,
)
from app.domains.catalog.price_lists.services.price_list_service import PriceListService
from app.domains.catalog.providers import catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/catalog/price-lists", tags=["catalog-price-lists"])


def price_list_service(request: Request) -> PriceListService:
    return catalog_services(request).price_lists


PriceLists = Annotated[PriceListService, Depends(price_list_service)]
CanRun = Annotated[RequestContext, Depends(require_permission("catalog.price_list.run"))]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]


def _etag(response: Response, out: PriceListOut) -> PriceListOut:
    response.headers["ETag"] = etag(out.version)
    return out


@router.post("", response_model=PriceListOut, status_code=status.HTTP_201_CREATED)
async def create_price_list(
    body: PriceListCreateIn, request: Request, response: Response, ctx: CanRun, svc: PriceLists, key: IdemKey
) -> Any:
    """Ro'yxat `READING` holatida ochiladi, AI fonda o'qiydi. AI sozlanmagan yoki limit tugagan — 422
    (`ai_unavailable`)."""

    async def replay(body: Any) -> PriceListOut:
        return await svc.get(ctx.db, ctx.actor, UUID(str(body["id"])))

    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.price_list.create",
        key,
        body,
        lambda: svc.create(ctx.db, ctx.actor, body),
        stored=lambda o: {"id": str(o.id)},
        on_replay=replay,
        status=201,
    )
    set_location(request, response, "get_price_list", price_list_id=result_field(out))
    return out


@router.get("", response_model=PriceListList)
async def list_price_lists(ctx: CanRun, svc: PriceLists) -> PriceListList:
    """Oxirgi 20 ta ro'yxat."""
    return await svc.list_runs(ctx.db, ctx.actor)


@router.get("/{price_list_id}", response_model=PriceListOut)
async def get_price_list(
    price_list_id: UUID, response: Response, ctx: CanRun, svc: PriceLists
) -> PriceListOut:
    return _etag(response, await svc.get(ctx.db, ctx.actor, price_list_id))


@router.patch("/{price_list_id}", response_model=PriceListOut)
async def update_price_list(
    price_list_id: UUID,
    body: PriceListSettingsIn,
    response: Response,
    ctx: CanRun,
    svc: PriceLists,
    version: IfMatch,
) -> PriceListOut:
    """Ustama foizi va so'm yaxlitlash qadami — taklif narxlari qayta hisoblanadi."""
    return _etag(response, await svc.update_settings(ctx.db, ctx.actor, price_list_id, version, body))


@router.patch("/{price_list_id}/items/{item_id}", response_model=PriceListOut)
async def update_price_list_item(
    price_list_id: UUID,
    item_id: UUID,
    body: PriceListItemIn,
    response: Response,
    ctx: CanRun,
    svc: PriceLists,
    version: IfMatch,
) -> PriceListOut:
    """Qatorni tanlash, qo'lda moslash yoki moslashni olib tashlash, narxni qo'lda yozish."""
    return _etag(response, await svc.update_item(ctx.db, ctx.actor, price_list_id, item_id, version, body))


@router.post("/{price_list_id}/apply", response_model=PriceListOut)
async def apply_price_list(
    price_list_id: UUID, response: Response, ctx: CanRun, svc: PriceLists, version: IfMatch, key: IdemKey
) -> Any:
    """Tanlangan qatorlar narxi yangilanadi (har biri alohida narx versiyasi va audit)."""

    async def replay(_body: Any) -> PriceListOut:
        return await svc.get(ctx.db, ctx.actor, price_list_id)

    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.price_list.apply",
        key,
        {"id": str(price_list_id)},
        lambda: svc.apply(ctx.db, ctx.actor, price_list_id, version),
        stored=lambda o: {"id": str(o.id)},
        on_replay=replay,
    )
    return out


@router.post("/{price_list_id}/cancel", response_model=PriceListOut)
async def cancel_price_list(
    price_list_id: UUID, response: Response, ctx: CanRun, svc: PriceLists, version: IfMatch
) -> PriceListOut:
    return _etag(response, await svc.cancel(ctx.db, ctx.actor, price_list_id, version))
