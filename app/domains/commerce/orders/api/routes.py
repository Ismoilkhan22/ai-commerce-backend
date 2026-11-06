"""Shop paneli: buyurtmalar (11 §9.4, §9.11; FSM-08, DEC-108, DEC-110, DEC-134).

Yozish so'rovlari idempotent. Javobda xaridor telefoni va manzili bor, shuning uchun takroriy so'rov himoyasi
(`platform.idempotency_keys`) faqat buyurtma ID'sini saqlaydi — takroriy so'rov buyurtmaning joriy holatini
qaytaradi (PII ochiq holda boshqa jadvalga yozilmaydi, 26 §4).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, BeforeValidator

from app.domains.commerce import permissions as perm
from app.domains.commerce.orders.schemas import (
    AssignIn,
    DiscountDecisionIn,
    DiscountIn,
    LineQtyIn,
    OptionalReasonIn,
    OrderCounts,
    OrderCreate,
    OrderHistory,
    OrderLineIn,
    OrderList,
    OrderNoteIn,
    OrderNoteOut,
    OrderOut,
    OrderReviewQueue,
    OrderSort,
    OrderStatus,
    OrderUpdate,
    PaidMarkIn,
    ReasonIn,
    RefreshPricesIn,
    ResolveExceptionIn,
    ReviewDecisionIn,
)
from app.domains.commerce.providers import CommerceServices, commerce_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, set_location, split_commas
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(prefix="/orders", tags=["commerce"])

Commerce = Annotated[CommerceServices, Depends(commerce_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]

CanView = Annotated[RequestContext, Depends(require_permission(perm.ORDER_VIEW))]
CanCreate = Annotated[RequestContext, Depends(require_permission(perm.ORDER_CREATE))]
CanConfirm = Annotated[RequestContext, Depends(require_permission(perm.ORDER_CONFIRM))]
CanProcess = Annotated[RequestContext, Depends(require_permission(perm.ORDER_PROCESS))]
CanComplete = Annotated[RequestContext, Depends(require_permission(perm.ORDER_COMPLETE))]
CanCancel = Annotated[RequestContext, Depends(require_permission(perm.ORDER_CANCEL))]
CanAssign = Annotated[RequestContext, Depends(require_permission(perm.ORDER_ASSIGN))]
CanPaidMark = Annotated[RequestContext, Depends(require_permission(perm.ORDER_PAID_MARK))]
CanNote = Annotated[RequestContext, Depends(require_permission(perm.ORDER_NOTE))]
CanApproveDiscount = Annotated[RequestContext, Depends(require_permission(perm.DISCOUNT_APPROVE))]


def _with_etag(response: Response, order: OrderOut) -> OrderOut:
    response.headers["ETag"] = etag(order.version)
    return order


async def _command(
    ctx: RequestContext,
    svc: CommerceServices,
    response: Response,
    operation: str,
    key: str,
    body: BaseModel | dict[str, Any] | None,
    produce: Callable[[], Awaitable[OrderOut]],
) -> OrderOut:
    """Idempotent buyurtma amali: saqlanadi faqat ID, takrorda — joriy holat (PII saqlanmaydi)."""

    async def replay(saved: Any) -> OrderOut:
        return await svc.orders.get(ctx.db, ctx.actor, UUID(str(saved["id"])))

    order = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        operation,
        key,
        body,
        produce,
        stored=lambda out: {"id": str(out.id)},
        on_replay=replay,
    )
    assert isinstance(order, OrderOut)
    return _with_etag(response, order)


def _body(body: BaseModel | None, version: int) -> dict[str, Any]:
    return {"body": body.model_dump(mode="json") if body else None, "if_match": version}


# ------------------------------------------------------------------ o'qish


@router.get("", response_model=OrderList)
async def list_orders(
    ctx: CanView,
    svc: Commerce,
    status: Annotated[list[OrderStatus] | None, BeforeValidator(split_commas), Query()] = None,
    branch_id: UUID | None = None,
    assigned: Annotated[
        str | None, Query(max_length=40, description='"me", "unassigned" yoki xodim (membership) ID')
    ] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Raqam (#1042), telefon yoki xaridor ismi")
    ] = None,
    needs_review: Annotated[bool, Query(description='"Ko\'rib chiqish kerak" — 24/72 soat')] = False,
    number: Annotated[int | None, Query(ge=1, le=2_147_483_647, description="Aniq buyurtma raqami")] = None,
    sort: OrderSort = "-created_at",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> OrderList:
    """Operator — o'ziga biriktirilganlar va biriktirilmagan navbat; omborchi — tasdiqlanganlar (10 §6.8)."""
    return await svc.orders.list_orders(
        ctx.db,
        ctx.actor,
        statuses=status or [],
        branch_id=branch_id,
        assigned=assigned,
        q=q,
        needs_review=needs_review,
        sort=sort,
        limit=limit,
        cursor=cursor,
        number=number,
    )


@router.get("/counts", response_model=OrderCounts)
async def order_counts(ctx: CanView, svc: Commerce) -> OrderCounts:
    return await svc.orders.counts(ctx.db, ctx.actor)


@router.get("/review-queue", response_model=OrderReviewQueue)
async def review_queue(ctx: CanView, svc: Commerce) -> OrderReviewQueue:
    """24 soat tasdiqlanmagan va 72 soat olib ketilmagan buyurtmalar (DEC-104, DEC-134)."""
    return await svc.orders.review_queue(ctx.db, ctx.actor)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: UUID, response: Response, ctx: CanView, svc: Commerce) -> OrderOut:
    return _with_etag(response, await svc.orders.get(ctx.db, ctx.actor, order_id))


# ------------------------------------------------------------------ qoralama


@router.get("/{order_id}/history", response_model=OrderHistory)
async def order_history(order_id: UUID, ctx: CanView, svc: Commerce) -> OrderHistory:
    """Holat tarixi: kim, qachon, qaysi o'tish va sabab (`platform.transition_log`). Xaridor ma'lumotisiz."""
    return await svc.orders.history(ctx.db, ctx.actor, order_id)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate, request: Request, response: Response, ctx: CanCreate, svc: Commerce, key: IdemKey
) -> OrderOut:
    """Qoralama: mahsulot band qilinmaydi (DEC-100b). Yaratgan xodim — mas'ul."""
    order = await _command(
        ctx,
        svc,
        response,
        "commerce.order.create",
        key,
        body,
        lambda: svc.orders.create(ctx.db, ctx.actor, body),
    )
    set_location(request, response, "get_order", order_id=order.id)
    return order


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: UUID, body: OrderUpdate, response: Response, ctx: CanCreate, svc: Commerce, version: IfMatch
) -> OrderOut:
    """Xaridor, filial va yetkazish — faqat qoralama va tasdiq kutilayotganda (DEC-134)."""
    return _with_etag(response, await svc.orders.update(ctx.db, ctx.actor, order_id, version, body))


@router.post("/{order_id}/lines", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def add_order_line(
    order_id: UUID,
    body: OrderLineIn,
    request: Request,
    response: Response,
    ctx: CanCreate,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> OrderOut:
    """If-Match — buyurtma versiyasi. Javob — butun buyurtma; `Location` — buyurtma."""
    order = await _command(
        ctx,
        svc,
        response,
        f"commerce.order.line_add:{order_id}",
        key,
        _body(body, version),
        lambda: svc.orders.add_line(ctx.db, ctx.actor, order_id, version, body),
    )
    set_location(request, response, "get_order", order_id=order_id)
    return order


@router.patch("/{order_id}/lines/{line_id}", response_model=OrderOut)
async def update_order_line(
    order_id: UUID,
    line_id: UUID,
    body: LineQtyIn,
    response: Response,
    ctx: CanCreate,
    svc: Commerce,
    version: IfMatch,
) -> OrderOut:
    return _with_etag(
        response, await svc.orders.update_line(ctx.db, ctx.actor, order_id, line_id, version, body.qty)
    )


@router.delete("/{order_id}/lines/{line_id}", response_model=OrderOut)
async def remove_order_line(
    order_id: UUID, line_id: UUID, response: Response, ctx: CanCreate, svc: Commerce, version: IfMatch
) -> OrderOut:
    return _with_etag(response, await svc.orders.remove_line(ctx.db, ctx.actor, order_id, line_id, version))


# ------------------------------------------------------------------ chegirma (DEC-110)


@router.put("/{order_id}/lines/{line_id}/discount", response_model=OrderOut)
async def set_line_discount(
    order_id: UUID,
    line_id: UUID,
    body: DiscountIn,
    response: Response,
    ctx: CanCreate,
    svc: Commerce,
    version: IfMatch,
) -> OrderOut:
    """O'z limiti ichida — darhol; undan ko'pi — tasdiq so'rovi (menejer ≤ limit, undan ko'pi — ega)."""
    order = await svc.orders.set_discount(ctx.db, ctx.actor, order_id, line_id, version, body.discount_pct)
    return _with_etag(response, order)


@router.post("/{order_id}/lines/{line_id}/discount/approve", response_model=OrderOut)
async def approve_line_discount(
    order_id: UUID,
    line_id: UUID,
    response: Response,
    ctx: CanApproveDiscount,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
    body: DiscountDecisionIn | None = None,
) -> OrderOut:
    note = body.note if body else None
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.discount_approve:{line_id}",
        key,
        _body(body, version),
        lambda: svc.orders.decide_discount(
            ctx.db, ctx.actor, order_id, line_id, version, approve=True, note=note
        ),
    )


@router.post("/{order_id}/lines/{line_id}/discount/reject", response_model=OrderOut)
async def reject_line_discount(
    order_id: UUID,
    line_id: UUID,
    response: Response,
    ctx: CanApproveDiscount,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
    body: DiscountDecisionIn | None = None,
) -> OrderOut:
    note = body.note if body else None
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.discount_reject:{line_id}",
        key,
        _body(body, version),
        lambda: svc.orders.decide_discount(
            ctx.db, ctx.actor, order_id, line_id, version, approve=False, note=note
        ),
    )


# ------------------------------------------------------------------ holat o'tishlari (FSM-08)


@router.post("/{order_id}/submit", response_model=OrderOut)
async def submit_order(
    order_id: UUID, response: Response, ctx: CanCreate, svc: Commerce, key: IdemKey, version: IfMatch
) -> OrderOut:
    """Qoralama → tasdiq kutilmoqda. Xaridor ismi, telefoni va qatorlar kerak; yetkazishda — manzil."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.submit:{order_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.submit(ctx.db, ctx.actor, order_id, version),
    )


@router.post("/{order_id}/confirm", response_model=OrderOut)
async def confirm_order(
    order_id: UUID, response: Response, ctx: CanConfirm, svc: Commerce, key: IdemKey, version: IfMatch
) -> OrderOut:
    """Qoldiq qayta tekshiriladi va band qilinadi; narx (joriy narx × kurs) farq qilsa — `PRICE_CHANGED`."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.confirm:{order_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.confirm(ctx.db, ctx.actor, order_id, version),
    )


@router.post("/{order_id}/refresh-prices", response_model=OrderOut)
async def refresh_order_prices(
    order_id: UUID,
    response: Response,
    ctx: CanCreate,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
    body: RefreshPricesIn | None = None,
) -> OrderOut:
    """Xaridor yangi narxga rozi — qatorlar joriy narxga o'tadi; `note` — "qo'ng'iroq natijasi" izohi."""
    note = body.note if body else None
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.refresh_prices:{order_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.refresh_prices(ctx.db, ctx.actor, order_id, version, note),
    )


@router.post("/{order_id}/start-processing", response_model=OrderOut)
async def start_order_processing(
    order_id: UUID, response: Response, ctx: CanProcess, svc: Commerce, key: IdemKey, version: IfMatch
) -> OrderOut:
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.start_processing:{order_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.start_processing(ctx.db, ctx.actor, order_id, version),
    )


@router.post("/{order_id}/mark-ready", response_model=OrderOut)
async def mark_order_ready(
    order_id: UUID, response: Response, ctx: CanProcess, svc: Commerce, key: IdemKey, version: IfMatch
) -> OrderOut:
    """ "Olib ketishga tayyor" — holat o'zgarmaydi (`ready_at`)."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.mark_ready:{order_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.mark_ready(ctx.db, ctx.actor, order_id, version),
    )


@router.post("/{order_id}/complete", response_model=OrderOut)
async def complete_order(
    order_id: UUID, response: Response, ctx: CanComplete, svc: Commerce, key: IdemKey, version: IfMatch
) -> OrderOut:
    """Topshirildi: qoldiq bir marta kamayadi (TC-030)."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.complete:{order_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.complete(ctx.db, ctx.actor, order_id, version),
    )


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: UUID,
    response: Response,
    ctx: CanView,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
    body: OptionalReasonIn | None = None,
) -> OrderOut:
    """Qoralama — operator ham; tasdiq kutilayotgan va tasdiqlangan — faqat menejer/ega, sabab bilan
    (BL-049)."""
    reason = body.reason if body else None
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.cancel:{order_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.cancel(ctx.db, ctx.actor, order_id, version, reason),
    )


@router.post("/{order_id}/exception", response_model=OrderOut)
async def raise_order_exception(
    order_id: UUID,
    body: ReasonIn,
    response: Response,
    ctx: CanProcess,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> OrderOut:
    """Muammo: mahsulot shikastlangan, xaridor bosh tortdi… — menejer hal qiladi."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.exception:{order_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.raise_exception(ctx.db, ctx.actor, order_id, version, body.reason),
    )


@router.post("/{order_id}/resolve-exception", response_model=OrderOut)
async def resolve_order_exception(
    order_id: UUID,
    body: ResolveExceptionIn,
    response: Response,
    ctx: CanCancel,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> OrderOut:
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.resolve_exception:{order_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.resolve_exception(
            ctx.db, ctx.actor, order_id, version, body.resolution, body.reason
        ),
    )


@router.post("/{order_id}/review-decision", response_model=OrderOut)
async def order_review_decision(
    order_id: UUID,
    body: ReviewDecisionIn,
    response: Response,
    ctx: CanCancel,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> OrderOut:
    """72 soatlik vazifa: "kutamiz" — yana 72 soat; "bekor" — buyurtma bekor, band "muddati o'tdi"."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.review_decision:{order_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.review_decision(
            ctx.db, ctx.actor, order_id, version, body.decision, body.reason
        ),
    )


# ------------------------------------------------------------------ biriktirish, izoh, "to'landi"


@router.post("/{order_id}/take", response_model=OrderOut)
async def take_order(
    order_id: UUID, response: Response, ctx: CanConfirm, svc: Commerce, key: IdemKey, version: IfMatch
) -> OrderOut:
    """Biriktirilmagan buyurtmani o'ziga olish (operator)."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.take:{order_id}",
        key,
        _body(None, version),
        lambda: svc.orders.take(ctx.db, ctx.actor, order_id, version),
    )


@router.post("/{order_id}/assign", response_model=OrderOut)
async def assign_order(
    order_id: UUID,
    body: AssignIn,
    response: Response,
    ctx: CanAssign,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> OrderOut:
    """Menejer mas'ul operatorni biriktiradi yoki almashtiradi (`null` — navbatga qaytaradi)."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.assign:{order_id}",
        key,
        _body(body, version),
        lambda: svc.orders.assign(ctx.db, ctx.actor, order_id, version, body.membership_id),
    )


@router.post("/{order_id}/paid-mark", response_model=OrderOut)
async def mark_order_paid(
    order_id: UUID, body: PaidMarkIn, response: Response, ctx: CanPaidMark, svc: Commerce, key: IdemKey
) -> OrderOut:
    """ "To'landi" — xodim belgisi, tizim tekshirmaydi (DEC-100a). Bir marta."""
    return await _command(
        ctx,
        svc,
        response,
        f"commerce.order.paid_mark:{order_id}",
        key,
        body,
        lambda: svc.orders.paid_mark(ctx.db, ctx.actor, order_id, body.method),
    )


@router.post("/{order_id}/notes", response_model=OrderNoteOut, status_code=status.HTTP_201_CREATED)
async def add_order_note(
    order_id: UUID,
    body: OrderNoteIn,
    request: Request,
    response: Response,
    ctx: CanNote,
    svc: Commerce,
    key: IdemKey,
) -> OrderNoteOut:
    """Izoh yoki qo'ng'iroq natijasi (DEC-100g). Faqat qo'shiladi. `Location` — buyurtma kartochkasi
    (izohlar shu yerda; alohida izoh manzili yo'q)."""

    async def replay(saved: Any) -> OrderNoteOut:
        return await svc.orders.note(ctx.db, ctx.actor, order_id, UUID(str(saved["id"])))

    note = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"commerce.order.note:{order_id}",
        key,
        body,
        lambda: svc.orders.add_note(ctx.db, ctx.actor, order_id, body),
        stored=lambda out: {"id": str(out.id)},  # matnda PII bo'lishi mumkin — saqlanmaydi
        on_replay=replay,
        status=201,
    )
    assert isinstance(note, OrderNoteOut)
    set_location(request, response, "get_order", order_id=order_id)
    return note
