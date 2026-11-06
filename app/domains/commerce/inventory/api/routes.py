"""Shop paneli: qoldiq, mahsulot tarixi, kirim va qo'lda tuzatish (11 §9.4, S1-05)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BeforeValidator

from app.domains.commerce import permissions as perm
from app.domains.commerce.inventory.schemas import (
    AdjustmentIn,
    AdjustmentList,
    AdjustmentOut,
    AdjustmentStatus,
    ApproveIn,
    LedgerList,
    ReceiptIn,
    ReceiptList,
    ReceiptOut,
    RejectIn,
    SkuCostHistory,
    SkuCostList,
    SkuCostOut,
    SkuCostSetIn,
    SkuPickList,
    StockList,
)
from app.domains.commerce.providers import CommerceServices, commerce_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, result_field, set_location, split_commas
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(tags=["commerce"])

Commerce = Annotated[CommerceServices, Depends(commerce_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Cursor = Annotated[str | None, Query(max_length=500)]

CanView = Annotated[RequestContext, Depends(require_permission(perm.STOCK_VIEW))]
CanReceive = Annotated[RequestContext, Depends(require_permission(perm.STOCK_RECEIVE))]
CanRequest = Annotated[RequestContext, Depends(require_permission(perm.ADJUST_REQUEST))]
CanApprove = Annotated[RequestContext, Depends(require_permission(perm.ADJUST_APPROVE))]


def _with_etag(response: Response, result: Any) -> Any:
    response.headers["ETag"] = etag(int(result_field(result, "version")))
    return result


async def _adjustment_command(
    ctx: RequestContext,
    svc: CommerceServices,
    operation: str,
    key: str,
    body: Any,
    produce: Callable[[], Awaitable[AdjustmentOut]],
    *,
    status_code: int = 200,
) -> AdjustmentOut:
    """Tuzatish javobida dalil rasmining imzoli havolasi bor — bazaga yozilmaydi (havola 5 daqiqada
    eskiradi): saqlanadi faqat ID, takroriy so'rovda yangi havola bilan joriy holat (QA F7)."""

    async def replay(saved: Any) -> AdjustmentOut:
        return await svc.stock.get_adjustment(ctx.db, ctx.actor, UUID(str(saved["id"])))

    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        operation,
        key,
        body,
        produce,
        stored=lambda out: {"id": str(out.id)},
        on_replay=replay,
        status=status_code,
    )
    assert isinstance(result, AdjustmentOut)
    return result


CanViewCost = Annotated[RequestContext, Depends(require_permission(perm.COST_VIEW))]
CanEditCost = Annotated[RequestContext, Depends(require_permission(perm.COST_EDIT))]

CanPickSku = Annotated[RequestContext, Depends(require_permission(perm.CATALOG_VIEW))]

# ------------------------------------------------------------------ qoldiq


@router.get("/skus", response_model=SkuPickList)
async def search_skus(
    ctx: CanPickSku,
    svc: Commerce,
    q: Annotated[
        str | None, Query(max_length=100, description="Nom, brend, SKU kodi, MPN yoki variant")
    ] = None,
    branch_id: Annotated[UUID | None, Query(description="Berilsa — shu filialda sotuvga mavjud son")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SkuPickList:
    """SKU tanlash (buyurtma qatori, tez sotuv, kirim): arxivda bo'lmaganlar, joriy narx va holat bilan.
    `orderable` / `quick_sellable` — qaysi amalga yaroqli."""
    return await svc.stock.pick_skus(ctx.db, ctx.actor, q=q, branch_id=branch_id, limit=limit)


@router.get("/stock", response_model=StockList)
async def list_stock(
    ctx: CanView,
    svc: Commerce,
    branch_id: UUID | None = None,
    sku_id: UUID | None = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Mahsulot nomi, brend, SKU kodi yoki MPN")
    ] = None,
    low_only: Annotated[bool, Query(description="Faqat kam qolgan va tugaganlar")] = False,
    limit: Limit = DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> StockList:
    """Filial × SKU: qoldiq, band, ajratilgan, tekshiruvda va sotuvga mavjud (BL-019)."""
    return await svc.stock.list_balances(
        ctx.db,
        ctx.actor,
        branch_id=branch_id,
        sku_id=sku_id,
        q=q,
        low_only=low_only,
        limit=limit,
        cursor=cursor,
    )


@router.get("/stock/history", response_model=LedgerList)
async def stock_history(
    ctx: CanView,
    svc: Commerce,
    sku_id: UUID,
    branch_id: UUID | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> LedgerList:
    """ "Mahsulot tarixi" — ombor daftari: kim, qachon, nima sababdan (BL-022)."""
    return await svc.stock.history(
        ctx.db, ctx.actor, sku_id=sku_id, branch_id=branch_id, limit=limit, cursor=cursor
    )


# ------------------------------------------------------------------ kirim


@router.post("/stock/receipts", response_model=ReceiptOut, status_code=status.HTTP_201_CREATED)
async def create_receipt(
    body: ReceiptIn, request: Request, response: Response, ctx: CanReceive, svc: Commerce, key: IdemKey
) -> Any:
    """Kirim: bir nechta mahsulot bitta hujjatda. Tasdiq kerak emas (12 §6)."""
    receipt = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "commerce.stock.receive",
        key,
        body,
        lambda: svc.stock.create_receipt(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_receipt", receipt_id=result_field(receipt))
    return receipt


@router.get("/stock/receipts", response_model=ReceiptList)
async def list_receipts(
    ctx: CanView,
    svc: Commerce,
    branch_id: UUID | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> ReceiptList:
    return await svc.stock.list_receipts(ctx.db, ctx.actor, branch_id=branch_id, limit=limit, cursor=cursor)


@router.get("/stock/receipts/{receipt_id}", response_model=ReceiptOut)
async def get_receipt(receipt_id: UUID, ctx: CanView, svc: Commerce) -> ReceiptOut:
    return await svc.stock.receipt(ctx.db, ctx.actor, receipt_id)


# ------------------------------------------------------------------ tuzatish


@router.post("/stock/adjustments", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    body: AdjustmentIn, request: Request, response: Response, ctx: CanRequest, svc: Commerce, key: IdemKey
) -> Any:
    """Omborchi — so'rov (ega yoki menejer tasdiqlaydi); ega va menejer — darhol qo'llanadi (DEC-134)."""
    adjustment = await _adjustment_command(
        ctx,
        svc,
        "commerce.stock.adjust",
        key,
        body,
        lambda: svc.stock.create_adjustment(ctx.db, ctx.actor, body),
        status_code=201,
    )
    set_location(request, response, "get_adjustment", adjustment_id=adjustment.id)
    return _with_etag(response, adjustment)


@router.get("/stock/adjustments", response_model=AdjustmentList)
async def list_adjustments(
    ctx: CanRequest,
    svc: Commerce,
    status: Annotated[list[AdjustmentStatus] | None, BeforeValidator(split_commas), Query()] = None,
    branch_id: UUID | None = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> AdjustmentList:
    return await svc.stock.list_adjustments(
        ctx.db, ctx.actor, statuses=status or [], branch_id=branch_id, limit=limit, cursor=cursor
    )


@router.get("/stock/adjustments/{adjustment_id}", response_model=AdjustmentOut)
async def get_adjustment(adjustment_id: UUID, response: Response, ctx: CanRequest, svc: Commerce) -> Any:
    return _with_etag(response, await svc.stock.get_adjustment(ctx.db, ctx.actor, adjustment_id))


@router.post("/stock/adjustments/{adjustment_id}/approve", response_model=AdjustmentOut)
async def approve_adjustment(
    adjustment_id: UUID,
    response: Response,
    ctx: CanApprove,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
    body: ApproveIn | None = None,
) -> Any:
    """Tasdiqda qoldiq qayta tekshiriladi: band + ajratilgandan pastga tushmaydi (TC-CON-12)."""
    note = body.note if body else None
    result = await _adjustment_command(
        ctx,
        svc,
        f"commerce.stock.adjustment_approve:{adjustment_id}",
        key,
        {"note": note, "if_match": version},
        lambda: svc.stock.approve_adjustment(ctx.db, ctx.actor, adjustment_id, version, note),
    )
    return _with_etag(response, result)


@router.post("/stock/adjustments/{adjustment_id}/reject", response_model=AdjustmentOut)
async def reject_adjustment(
    adjustment_id: UUID,
    body: RejectIn,
    response: Response,
    ctx: CanApprove,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> Any:
    result = await _adjustment_command(
        ctx,
        svc,
        f"commerce.stock.adjustment_reject:{adjustment_id}",
        key,
        {"note": body.note, "if_match": version},
        lambda: svc.stock.reject_adjustment(ctx.db, ctx.actor, adjustment_id, version, body.note),
    )
    return _with_etag(response, result)


# ------------------------------------------------------------------ tannarx (DEC-146): faqat ega


@router.get("/costs", response_model=SkuCostList)
async def list_costs(
    ctx: CanViewCost, svc: Commerce, limit: Limit = DEFAULT_LIMIT, cursor: Cursor = None
) -> SkuCostList:
    """Mahsulotlarning joriy o'rtacha tannarxi (so'mda). Ro'yxatda yo'q mahsulot — tannarx noma'lum."""
    return await svc.stock.costs.list_costs(ctx.db, ctx.actor, limit=limit, cursor=cursor)


@router.get("/costs/{sku_id}", response_model=SkuCostOut)
async def get_cost(sku_id: UUID, ctx: CanViewCost, svc: Commerce) -> SkuCostOut:
    return await svc.stock.costs.get(ctx.db, ctx.actor, sku_id)


@router.get("/costs/{sku_id}/history", response_model=SkuCostHistory)
async def cost_history(
    sku_id: UUID, ctx: CanViewCost, svc: Commerce, limit: Limit = DEFAULT_LIMIT, cursor: Cursor = None
) -> SkuCostHistory:
    """ "Nega tannarx o'zgardi?": har kirim va qo'lda to'g'rilash — oldingi va keyingi o'rtacha bilan."""
    return await svc.stock.costs.history(ctx.db, ctx.actor, sku_id, limit=limit, cursor=cursor)


@router.put("/costs/{sku_id}", response_model=SkuCostOut)
async def set_cost(sku_id: UUID, body: SkuCostSetIn, ctx: CanEditCost, svc: Commerce, key: IdemKey) -> Any:
    """Tizimgacha bo'lgan qoldiq yoki xato o'rtachani qo'lda qo'yish; izoh majburiy (`MANUAL_SET`)."""
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"commerce.cost.set:{sku_id}",
        key,
        body,
        lambda: svc.stock.costs.set_manual(ctx.db, ctx.actor, sku_id, body),
    )
