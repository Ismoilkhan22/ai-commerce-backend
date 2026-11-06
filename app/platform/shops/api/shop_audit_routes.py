"""Shop paneli: "O'zgarishlar tarixi" va CSV eksport (M20, `audit.view` — ega va menejer)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.platform.audit.schemas import ShopAuditList
from app.platform.audit.services.history import ShopAuditQueries
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(prefix="/audit", tags=["shop"])

AUDIT_VIEW = "audit.view"
CanView = Annotated[RequestContext, Depends(require_permission(AUDIT_VIEW))]
_queries = ShopAuditQueries()

ActorId = Annotated[UUID | None, Query()]
EntityType = Annotated[str | None, Query(max_length=100)]
Action = Annotated[str | None, Query(max_length=100, description="Amal kodi boshlanishi: commerce.order")]


@router.get("", response_model=ShopAuditList)
async def list_audit(
    ctx: CanView,
    actor_id: ActorId = None,
    entity_type: EntityType = None,
    action: Action = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> ShopAuditList:
    """Shu shopdagi o'zgarishlar: kim, qachon, nima (amal kodi), qaysi maydonlar. Qiymatlar yo'q."""
    assert ctx.actor.shop_id is not None
    return await _queries.page(
        ctx.db,
        ctx.actor.shop_id,
        actor_id=actor_id,
        entity_type=entity_type,
        action=action,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
async def export_audit(
    ctx: CanView,
    actor_id: ActorId = None,
    entity_type: EntityType = None,
    action: Action = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Response:
    """CSV (eng ko'pi bilan 5000 qator): shaxsiy ma'lumotsiz, formula belgilariga qarshi himoyalangan."""
    assert ctx.actor.shop_id is not None
    body = await _queries.export_csv(
        ctx.db,
        ctx.actor.shop_id,
        actor_id=actor_id,
        entity_type=entity_type,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit.csv"', "Cache-Control": "no-store"},
    )
