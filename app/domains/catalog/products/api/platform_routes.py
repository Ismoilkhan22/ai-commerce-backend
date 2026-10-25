"""Platforma paneli: toifalar ro'yxatini yuritish (DEC-133 — hamma shop uchun bitta ro'yxat)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response, status

from app.domains.catalog.products.schemas import (
    CATEGORY_CODE,
    CategoryIn,
    CategoryList,
    CategoryOut,
    CategoryUpdate,
)
from app.domains.catalog.providers import CatalogServices, catalog_services
from app.platform.staff.infrastructure.guard import (
    PlatformContext,
    RequestContext,
    require_platform_permission,
)
from app.shared.http import result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/catalog/categories", tags=["platform"])

Catalog = Annotated[CatalogServices, Depends(catalog_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
CanEdit = Annotated[RequestContext, Depends(require_platform_permission("platform.category.edit"))]
CategoryCode = Annotated[str, Path(pattern=CATEGORY_CODE)]


@router.get("", response_model=CategoryList)
async def list_categories(ctx: PlatformContext, svc: Catalog) -> CategoryList:
    return await svc.categories.listing(ctx.db)


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryIn, request: Request, response: Response, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    category = await run_idempotent(
        ctx.db,
        None,
        "catalog.category.create",
        key,
        body,
        lambda: svc.categories.create(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_category", code=result_field(category, "code"))
    return category


@router.get("/{code}", response_model=CategoryOut)
async def get_category(code: CategoryCode, ctx: PlatformContext, svc: Catalog) -> CategoryOut:
    return await svc.categories.get(ctx.db, code)


@router.patch("/{code}", response_model=CategoryOut)
async def update_category(
    code: CategoryCode, body: CategoryUpdate, ctx: CanEdit, svc: Catalog
) -> CategoryOut:
    """Nom, tartib, ota toifa, faollik. Faol emas toifaga yangi mahsulot qo'shilmaydi, eskilari qoladi."""
    return await svc.categories.update(ctx.db, ctx.actor, code, body)
