"""Shop paneli: texnik kutubxonadan qidirish, SKU'ni bog'lash, "yangi model" so'rovi (11 §9.3, DEC-120)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.domains.catalog.pc_specs.schemas import (
    AutoLinkResult,
    SpecCandidates,
    SpecLinkIn,
    SpecRequestIn,
    SpecRequestList,
    SpecRequestOut,
    SpecRequestStatus,
)
from app.domains.catalog.products.schemas import SpecCategory, SpecLinkOut
from app.domains.catalog.providers import CatalogServices, catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(tags=["catalog"])

Catalog = Annotated[CatalogServices, Depends(catalog_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]

CanView = Annotated[RequestContext, Depends(require_permission("catalog.product.view"))]
CanLink = Annotated[RequestContext, Depends(require_permission("catalog.spec.link"))]


@router.get("/hardware-specs", response_model=SpecCandidates)
async def search_hardware_specs(
    ctx: CanView,
    svc: Catalog,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: SpecCategory | None = None,
) -> SpecCandidates:
    """Kutubxonadagi tasdiqlangan modellar (ko'pi bilan 20 ta) — SKU'ni qo'lda bog'lash uchun."""
    return await svc.links.search(ctx.db, q, category)


@router.get("/skus/{sku_id}/spec-candidates", response_model=SpecCandidates)
async def spec_candidates(sku_id: UUID, ctx: CanView, svc: Catalog) -> SpecCandidates:
    """MPN yoki brend + model bo'yicha aniq mos kelganlar. Bittadan ko'p bo'lsa — xodim tanlaydi."""
    return await svc.links.candidates(ctx.db, ctx.actor, sku_id)


@router.put("/skus/{sku_id}/spec-link", response_model=SpecLinkOut)
async def set_spec_link(sku_id: UUID, body: SpecLinkIn, ctx: CanLink, svc: Catalog) -> SpecLinkOut:
    """Qo'lda bog'lash (MANUAL) — avtomatika uni o'zgartirmaydi. Faqat tasdiqlangan, shu turdagi model."""
    return await svc.links.set_link(ctx.db, ctx.actor, sku_id, body.spec_id)


@router.delete("/skus/{sku_id}/spec-link", status_code=status.HTTP_204_NO_CONTENT)
async def remove_spec_link(sku_id: UUID, ctx: CanLink, svc: Catalog) -> None:
    await svc.links.remove_link(ctx.db, ctx.actor, sku_id)


@router.post("/skus/auto-link", response_model=AutoLinkResult)
async def auto_link_skus(ctx: CanLink, svc: Catalog, key: IdemKey) -> Any:
    """Bog'lanmagan faol SKU'larni kutubxona bo'yicha qayta tekshirish (yangi modellar qo'shilgach)."""
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.sku.auto_link",
        key,
        None,
        lambda: svc.links.auto_link_all(ctx.db, ctx.actor),
    )


@router.get("/hardware-spec-requests", response_model=SpecRequestList)
async def list_spec_requests(
    ctx: CanLink, svc: Catalog, status: SpecRequestStatus | None = None
) -> SpecRequestList:
    return await svc.links.list_requests(ctx.db, ctx.actor, status)


@router.get("/hardware-spec-requests/{request_id}", response_model=SpecRequestOut)
async def get_spec_request(request_id: UUID, ctx: CanLink, svc: Catalog) -> SpecRequestOut:
    return await svc.links.get_request(ctx.db, ctx.actor, request_id)


@router.post("/hardware-spec-requests", response_model=SpecRequestOut, status_code=status.HTTP_201_CREATED)
async def create_spec_request(
    body: SpecRequestIn, request: Request, response: Response, ctx: CanLink, svc: Catalog, key: IdemKey
) -> Any:
    """Kutubxonada yo'q model uchun so'rov — platforma jamoasi 2 ish kunida qo'shadi (DEC-120)."""
    created = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.spec_request.create",
        key,
        body,
        lambda: svc.links.create_request(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_spec_request", request_id=result_field(created))
    return created
