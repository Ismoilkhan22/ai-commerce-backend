"""Shop paneli: narx va shop kursi (11 §9.3, DEC-121)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.domains.catalog.pricing.schemas import (
    ExchangeRateIn,
    ExchangeRateList,
    ExchangeRateOut,
    PriceHistory,
)
from app.domains.catalog.products.schemas import PriceIn, PriceOut
from app.domains.catalog.providers import CatalogServices, catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(tags=["catalog"])

Catalog = Annotated[CatalogServices, Depends(catalog_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]

CanViewPrice = Annotated[RequestContext, Depends(require_permission("catalog.price.view"))]
CanChangePrice = Annotated[RequestContext, Depends(require_permission("catalog.price.change"))]
CanEditRate = Annotated[RequestContext, Depends(require_permission("catalog.exchange_rate.edit"))]


@router.put("/skus/{sku_id}/price", response_model=PriceOut)
async def set_price(
    sku_id: UUID,
    body: PriceIn,
    response: Response,
    ctx: CanChangePrice,
    svc: Catalog,
    key: IdemKey,
    version: IfMatch,
) -> Any:
    """Yangi narx — yangi o'zgarmas versiya. If-Match — joriy narx versiyasi; birinchi narx uchun `"v0"`."""
    price = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"catalog.price.set:{sku_id}",
        key,
        {"price": body.model_dump(mode="json"), "if_match": version},
        lambda: svc.pricing.set_price(ctx.db, ctx.actor, sku_id, version, body),
    )
    current = price.version if isinstance(price, PriceOut) else int(price["version"])
    response.headers["ETag"] = etag(current)
    return price


@router.get("/skus/{sku_id}/price-history", response_model=PriceHistory)
async def price_history(sku_id: UUID, ctx: CanViewPrice, svc: Catalog) -> PriceHistory:
    return await svc.pricing.history(ctx.db, ctx.actor, sku_id)


@router.get("/exchange-rates", response_model=ExchangeRateList)
async def list_exchange_rates(ctx: CanViewPrice, svc: Catalog) -> ExchangeRateList:
    """Joriy kurs (`is_stale` — 3 kundan eski) va oxirgi o'zgarishlar."""
    return await svc.pricing.rates(ctx.db, ctx.actor)


@router.get("/exchange-rates/{rate_id}", response_model=ExchangeRateOut)
async def get_exchange_rate(rate_id: UUID, ctx: CanViewPrice, svc: Catalog) -> ExchangeRateOut:
    return await svc.pricing.rate(ctx.db, ctx.actor, rate_id)


@router.post("/exchange-rates", response_model=ExchangeRateOut, status_code=status.HTTP_201_CREATED)
async def add_exchange_rate(
    body: ExchangeRateIn, request: Request, response: Response, ctx: CanEditRate, svc: Catalog, key: IdemKey
) -> Any:
    """Yangi kurs — yangi qator (tarix o'zgarmaydi). Dollar narxlari so'mda shu kurs bilan ko'rsatiladi."""
    rate = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.exchange_rate.create",
        key,
        body,
        lambda: svc.pricing.add_rate(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_exchange_rate", rate_id=result_field(rate))
    return rate
