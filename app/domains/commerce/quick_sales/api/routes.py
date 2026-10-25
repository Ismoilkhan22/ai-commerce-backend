"""Shop paneli: tez sotuv — peshtaxtadan sotuv (DEC-123, 11 §9.4)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.domains.commerce import permissions as perm
from app.domains.commerce.providers import CommerceServices, commerce_services
from app.domains.commerce.quick_sales.schemas import QuickSaleIn, QuickSaleList, QuickSaleOut
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(tags=["commerce"])

Commerce = Annotated[CommerceServices, Depends(commerce_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
CanSell = Annotated[RequestContext, Depends(require_permission(perm.QUICK_SALE))]


@router.post("/quick-sales", response_model=QuickSaleOut, status_code=status.HTTP_201_CREATED)
async def create_quick_sale(
    body: QuickSaleIn, request: Request, response: Response, ctx: CanSell, svc: Commerce, key: IdemKey
) -> Any:
    """Mahsulot + miqdor → qoldiq darhol kamayadi; band mahsulotni sotib bo'lmaydi (BL-109, TC-027).

    Ikki marta bosish — bir sotuv (bir xil `Idempotency-Key`).
    """
    sale = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "commerce.quick_sale.create",
        key,
        body,
        lambda: svc.quick_sales.create(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_quick_sale", sale_id=result_field(sale))
    return sale


@router.get("/quick-sales", response_model=QuickSaleList)
async def list_quick_sales(
    ctx: CanSell,
    svc: Commerce,
    branch_id: UUID | None = None,
    mine: Annotated[bool, Query(description="Faqat o'zim sotganlarim")] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> QuickSaleList:
    return await svc.quick_sales.list_sales(
        ctx.db, ctx.actor, branch_id=branch_id, mine=mine, limit=limit, cursor=cursor
    )


@router.get("/quick-sales/{sale_id}", response_model=QuickSaleOut)
async def get_quick_sale(sale_id: UUID, ctx: CanSell, svc: Commerce) -> QuickSaleOut:
    return await svc.quick_sales.get(ctx.db, ctx.actor, sale_id)
