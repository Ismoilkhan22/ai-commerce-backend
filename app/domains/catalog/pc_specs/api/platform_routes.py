"""Platforma paneli: texnik ma'lumotlar kutubxonasi va shop so'rovlari navbati (17 §10, DEC-120)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.domains.catalog.pc_specs.schemas import (
    HardwareSpecDetail,
    HardwareSpecIn,
    HardwareSpecList,
    NoteIn,
    PlatformSpecRequestList,
    ResolveIn,
    ReviewQueue,
    SpecRequestOut,
    SpecRequestStatus,
    SpecStatus,
    SpecVersionIn,
)
from app.domains.catalog.products.schemas import SpecCategory
from app.domains.catalog.providers import CatalogServices, catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.shared.http import result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(tags=["platform"])

Catalog = Annotated[CatalogServices, Depends(catalog_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
Limit = Annotated[int, Query(ge=1, le=100)]
# Platforma navbatlari kichik — offset vaqtincha (11 §4.1 cursor talab qiladi; M02 "keyinga qoldirildi")
Offset = Annotated[int, Query(ge=0, le=100_000)]
VersionNo = Annotated[int, Path(ge=1, le=1_000_000)]
CanView = Annotated[RequestContext, Depends(require_platform_permission("platform.spec.view"))]
CanEdit = Annotated[RequestContext, Depends(require_platform_permission("platform.spec.edit"))]


# ------------------------------------------------------------------ kutubxona


@router.get("/hardware-specs", response_model=HardwareSpecList)
async def list_hardware_specs(
    ctx: CanView,
    svc: Catalog,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: SpecCategory | None = None,
    status: SpecStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> HardwareSpecList:
    return await svc.specs.list_specs(
        ctx.db, q=q, category=category, status=status, limit=limit, offset=offset
    )


@router.get("/hardware-specs/review-queue", response_model=ReviewQueue)
async def hardware_spec_review_queue(ctx: CanView, svc: Catalog) -> ReviewQueue:
    """Tasdiq kutayotgan takliflar — eng uzoq kutayotgan birinchi. O'z taklifini tasdiqlab bo'lmaydi."""
    return await svc.specs.review_queue(ctx.db)


@router.post("/hardware-specs", response_model=HardwareSpecDetail, status_code=status.HTTP_201_CREATED)
async def create_hardware_spec(
    body: HardwareSpecIn, request: Request, response: Response, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    """Yangi model: qoralama + 1-taklif. Boshqa xodim tasdiqlagach shoplarga ko'rinadi."""
    spec = await run_idempotent(
        ctx.db,
        None,
        "catalog.spec.create",
        key,
        body,
        lambda: svc.specs.create(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_hardware_spec", spec_id=result_field(spec))
    return spec


@router.get("/hardware-specs/{spec_id}", response_model=HardwareSpecDetail)
async def get_hardware_spec(spec_id: UUID, ctx: CanView, svc: Catalog) -> HardwareSpecDetail:
    return await svc.specs.get(ctx.db, spec_id)


@router.post(
    "/hardware-specs/{spec_id}/versions",
    response_model=HardwareSpecDetail,
    status_code=status.HTTP_201_CREATED,
)
async def propose_hardware_spec_change(
    spec_id: UUID,
    body: SpecVersionIn,
    request: Request,
    response: Response,
    ctx: CanEdit,
    svc: Catalog,
    key: IdemKey,
) -> Any:
    """O'zgarish taklifi (to'liq nusxa). Tasdiqlanguncha eski ma'lumot ishlayveradi."""
    spec = await run_idempotent(
        ctx.db,
        None,
        f"catalog.spec.propose:{spec_id}",
        key,
        body,
        lambda: svc.specs.propose(ctx.db, ctx.actor, spec_id, body),
        status=201,
    )
    set_location(request, response, "get_hardware_spec", spec_id=spec_id)
    return spec


@router.post("/hardware-specs/{spec_id}/versions/{version}/approve", response_model=HardwareSpecDetail)
async def approve_hardware_spec_version(
    spec_id: UUID, version: VersionNo, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    return await run_idempotent(
        ctx.db,
        None,
        f"catalog.spec.approve:{spec_id}:{version}",
        key,
        None,
        lambda: svc.specs.approve(ctx.db, ctx.actor, spec_id, version),
    )


@router.post("/hardware-specs/{spec_id}/versions/{version}/reject", response_model=HardwareSpecDetail)
async def reject_hardware_spec_version(
    spec_id: UUID, version: VersionNo, body: NoteIn, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    return await run_idempotent(
        ctx.db,
        None,
        f"catalog.spec.reject:{spec_id}:{version}",
        key,
        body,
        lambda: svc.specs.reject(ctx.db, ctx.actor, spec_id, version, body.note),
    )


@router.post("/hardware-specs/{spec_id}/retire", response_model=HardwareSpecDetail)
async def retire_hardware_spec(spec_id: UUID, body: NoteIn, ctx: CanEdit, svc: Catalog, key: IdemKey) -> Any:
    """Eskirgan model: yangi bog'lanish yo'q, mavjud bog'lanishlar qoladi."""
    return await run_idempotent(
        ctx.db,
        None,
        f"catalog.spec.retire:{spec_id}",
        key,
        body,
        lambda: svc.specs.retire(ctx.db, ctx.actor, spec_id, body.note),
    )


# ------------------------------------------------------------------ shop so'rovlari


@router.get("/hardware-spec-requests", response_model=PlatformSpecRequestList)
async def list_spec_requests(
    ctx: CanView,
    svc: Catalog,
    status: SpecRequestStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> PlatformSpecRequestList:
    """Hamma shoplardan kelgan "yangi model" so'rovlari — eng eskisi birinchi (maqsad: 2 ish kuni)."""
    return await svc.specs.list_requests(ctx.db, status=status, limit=limit, offset=offset)


@router.post("/hardware-spec-requests/{request_id}/resolve", response_model=SpecRequestOut)
async def resolve_spec_request(
    request_id: UUID, body: ResolveIn, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    """So'rovni hal qilish: model ko'rsatiladi, so'ralgan SKU unga bog'lanadi (bog'lanmagan bo'lsa)."""
    return await run_idempotent(
        ctx.db,
        None,
        f"catalog.spec_request.resolve:{request_id}",
        key,
        body,
        lambda: svc.specs.resolve_request(ctx.db, ctx.actor, request_id, body.spec_id),
    )


@router.post("/hardware-spec-requests/{request_id}/reject", response_model=SpecRequestOut)
async def reject_spec_request(
    request_id: UUID, body: NoteIn, ctx: CanEdit, svc: Catalog, key: IdemKey
) -> Any:
    return await run_idempotent(
        ctx.db,
        None,
        f"catalog.spec_request.reject:{request_id}",
        key,
        body,
        lambda: svc.specs.reject_request(ctx.db, ctx.actor, request_id, body.note),
    )
