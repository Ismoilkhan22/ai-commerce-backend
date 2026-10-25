"""Shop paneli: toifalar, mahsulotlar, SKU va rasmlar (11 §9.3, FSM-02)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BeforeValidator

from app.domains.catalog.products.schemas import (
    CategoryList,
    MediaAttachIn,
    MediaOrderIn,
    ProductCounts,
    ProductCreate,
    ProductList,
    ProductOut,
    ProductSort,
    ProductStatus,
    ProductUpdate,
    SkuIn,
    SkuUpdate,
    TransitionIn,
)
from app.domains.catalog.providers import CatalogServices, catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, result_field, set_location, split_commas
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(tags=["catalog"])

Catalog = Annotated[CatalogServices, Depends(catalog_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]

CanView = Annotated[RequestContext, Depends(require_permission("catalog.product.view"))]
CanEdit = Annotated[RequestContext, Depends(require_permission("catalog.product.edit"))]
CanPublish = Annotated[RequestContext, Depends(require_permission("catalog.product.publish"))]
CanArchive = Annotated[RequestContext, Depends(require_permission("catalog.product.archive"))]


def _with_etag(response: Response, product: ProductOut) -> ProductOut:
    response.headers["ETag"] = etag(product.version)
    return product


# ------------------------------------------------------------------ toifalar


@router.get("/categories", response_model=CategoryList)
async def list_categories(ctx: CanView, svc: Catalog) -> CategoryList:
    """Platforma toifalari (3 tilda). Faol emaslari ham qaytadi — eski mahsulotlarni ko'rsatish uchun."""
    return await svc.categories.listing(ctx.db)


# ------------------------------------------------------------------ mahsulotlar


@router.get("/products", response_model=ProductList)
async def list_products(
    ctx: CanView,
    svc: Catalog,
    status: Annotated[list[ProductStatus] | None, BeforeValidator(split_commas), Query()] = None,
    category: Annotated[str | None, Query(max_length=40)] = None,
    q: Annotated[str | None, Query(max_length=100, description="Nomi, brend, SKU kodi yoki MPN")] = None,
    sort: ProductSort = "-updated_at",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> ProductList:
    return await svc.products.list_products(
        ctx.db,
        ctx.actor,
        statuses=status or [],
        category=category,
        q=q,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )


@router.get("/products/counts", response_model=ProductCounts)
async def product_counts(ctx: CanView, svc: Catalog) -> ProductCounts:
    return await svc.products.counts(ctx.db, ctx.actor)


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate, request: Request, response: Response, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    """Kartochka (qoralama), ixtiyoriy ravishda variantlar va narxlari bilan — bitta so'rovda."""
    product = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.product.create",
        key,
        body,
        lambda: svc.products.create(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_product", product_id=result_field(product))
    return product


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: UUID, response: Response, ctx: CanView, svc: Catalog) -> ProductOut:
    return _with_etag(response, await svc.products.get(ctx.db, ctx.actor, product_id))


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: UUID, body: ProductUpdate, response: Response, ctx: CanEdit, svc: Catalog, version: IfMatch
) -> ProductOut:
    return _with_etag(response, await svc.products.update(ctx.db, ctx.actor, product_id, version, body))


async def _transition(
    ctx: RequestContext,
    svc: CatalogServices,
    key: str,
    product_id: UUID,
    command: str,
    body: TransitionIn | None,
) -> Any:
    reason = body.reason if body else None
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"catalog.product.{command.lower()}:{product_id}",
        key,
        body,
        lambda: svc.products.transition(ctx.db, ctx.actor, product_id, command, reason),
    )


@router.post("/products/{product_id}/publish", response_model=ProductOut)
async def publish_product(
    product_id: UUID, ctx: CanPublish, svc: Catalog, key: IdemKey, body: TransitionIn | None = None
) -> Any:
    """Qoralamani yoki yashirilganini saytga chiqarish (narx va majburiy maydonlar tekshiriladi)."""
    return await _transition(ctx, svc, key, product_id, "PUBLISH", body)


@router.post("/products/{product_id}/hide", response_model=ProductOut)
async def hide_product(
    product_id: UUID, ctx: CanPublish, svc: Catalog, key: IdemKey, body: TransitionIn | None = None
) -> Any:
    return await _transition(ctx, svc, key, product_id, "HIDE", body)


@router.post("/products/{product_id}/archive", response_model=ProductOut)
async def archive_product(
    product_id: UUID, ctx: CanArchive, svc: Catalog, key: IdemKey, body: TransitionIn | None = None
) -> Any:
    """Faqat ega (DEC-133). Arxivdagi mahsulot o'zgartirilmaydi, eski buyurtmalarda ma'lumoti qoladi."""
    return await _transition(ctx, svc, key, product_id, "ARCHIVE", body)


# ------------------------------------------------------------------ SKU


@router.post("/products/{product_id}/skus", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def add_sku(
    product_id: UUID,
    body: SkuIn,
    request: Request,
    response: Response,
    ctx: CanEdit,
    svc: Catalog,
    key: IdemKey,
) -> Any:
    """Javob — butun mahsulot; `Location` — mahsulot (SKU alohida o'qilmaydi)."""
    product = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"catalog.sku.create:{product_id}",
        key,
        body,
        lambda: svc.products.add_sku(ctx.db, ctx.actor, product_id, body),
        status=201,
    )
    set_location(request, response, "get_product", product_id=product_id)
    return product


@router.patch("/skus/{sku_id}", response_model=ProductOut)
async def update_sku(
    sku_id: UUID, body: SkuUpdate, response: Response, ctx: CanEdit, svc: Catalog, version: IfMatch
) -> ProductOut:
    """If-Match — SKU versiyasi. Javob — butun mahsulot (yangi versiyalar bilan); ETag — SKU versiyasi."""
    product = await svc.products.update_sku(ctx.db, ctx.actor, sku_id, version, body)
    sku = next(s for s in product.skus if s.id == sku_id)
    response.headers["ETag"] = etag(sku.version)
    return product


@router.post("/skus/{sku_id}/archive", response_model=ProductOut)
async def archive_sku(sku_id: UUID, ctx: CanEdit, svc: Catalog, key: IdemKey) -> Any:
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"catalog.sku.archive:{sku_id}",
        key,
        None,
        lambda: svc.products.archive_sku(ctx.db, ctx.actor, sku_id),
    )


# ------------------------------------------------------------------ rasmlar


@router.post("/products/{product_id}/media", response_model=ProductOut)
async def attach_media(
    product_id: UUID, body: MediaAttachIn, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    """Avval `POST /files?purpose=PRODUCT_IMAGE`, keyin shu yerda mahsulotga ulanadi (ko'pi bilan 10 ta)."""
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"catalog.product.media:{product_id}",
        key,
        body,
        lambda: svc.products.attach_media(ctx.db, ctx.actor, product_id, body.file_id),
    )


@router.delete("/products/{product_id}/media/{media_id}", response_model=ProductOut)
async def remove_media(product_id: UUID, media_id: UUID, ctx: CanEdit, svc: Catalog) -> ProductOut:
    return await svc.products.remove_media(ctx.db, ctx.actor, product_id, media_id)


@router.put("/products/{product_id}/media/order", response_model=ProductOut)
async def reorder_media(product_id: UUID, body: MediaOrderIn, ctx: CanEdit, svc: Catalog) -> ProductOut:
    """Rasmlar tartibi: ro'yxatdagi birinchisi — asosiy rasm."""
    return await svc.products.reorder_media(ctx.db, ctx.actor, product_id, body.media_ids)
