"""Platforma paneli: bosh sahifa va jamoa faoliyati jurnali (business/15 §1, §6)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.platform.shops.platform_schemas import ActivityList, PlatformDashboard
from app.platform.shops.services.platform_queries import PlatformQueryService
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.platform.staff.infrastructure.providers import platform_queries

router = APIRouter(tags=["platform"])

Queries = Annotated[PlatformQueryService, Depends(platform_queries)]
CanView = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.view_meta"))]


@router.get("/dashboard", response_model=PlatformDashboard)
async def dashboard(ctx: CanView, queries: Queries) -> PlatformDashboard:
    return await queries.dashboard(ctx.db)


@router.get("/audit", response_model=ActivityList)
async def platform_audit(
    ctx: CanView,
    queries: Queries,
    shop_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: Annotated[
        str | None, Query(max_length=100, description="Amal nomi boshlanishi: shops.shop")
    ] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActivityList:
    """Platforma jamoasining hamma amallari (kim, qachon, qaysi shop, nega)."""
    return await queries.platform_audit(
        ctx.db,
        shop_id=shop_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
