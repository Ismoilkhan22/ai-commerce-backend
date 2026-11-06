"""Shop paneli: kafolat murojaatlari (11 §9.4, FSM-11, DEC-130, DEC-145).

Yozish so'rovlari idempotent. Javobda xaridor telefoni bor, shuning uchun takroriy so'rov himoyasi faqat
murojaat ID'sini saqlaydi — takrorda murojaatning joriy holati qaytadi (PII boshqa jadvalga yozilmaydi).
Holat o'tishlari `If-Match` bilan (optimistik qulf).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, BeforeValidator

from app.domains.support import permissions as perm
from app.domains.support.providers import SupportServices, support_services
from app.domains.support.schemas import (
    CaseApproveIn,
    CaseAssignIn,
    CaseAttachmentIn,
    CaseDetail,
    CaseList,
    CaseNoteIn,
    CaseOpenIn,
    CaseReceiveItemIn,
    CaseRejectIn,
    CaseResolutionChangeIn,
    CaseResolveIn,
    CaseSource,
    CaseStartReviewIn,
    CaseStatus,
    Resolution,
)
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, set_location, split_commas
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(prefix="/support/cases", tags=["support"])

Support = Annotated[SupportServices, Depends(support_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]

CanView = Annotated[RequestContext, Depends(require_permission(perm.CASE_VIEW))]
CanOpen = Annotated[RequestContext, Depends(require_permission(perm.CASE_OPEN))]
CanService = Annotated[RequestContext, Depends(require_permission(perm.CASE_SERVICE))]
CanFulfil = Annotated[RequestContext, Depends(require_permission(perm.CASE_FULFIL))]
CanDecide = Annotated[RequestContext, Depends(require_permission(perm.CASE_DECIDE))]


def _with_etag(response: Response, case: CaseDetail) -> CaseDetail:
    response.headers["ETag"] = etag(case.version)
    return case


async def _command(
    ctx: RequestContext,
    svc: SupportServices,
    response: Response,
    operation: str,
    key: str,
    body: BaseModel | dict[str, Any] | None,
    produce: Callable[[], Awaitable[CaseDetail]],
    *,
    status_code: int = 200,
) -> CaseDetail:
    """Idempotent amal: saqlanadi faqat ID, takrorda — joriy holat."""

    async def replay(saved: Any) -> CaseDetail:
        return await svc.cases.get(ctx.db, ctx.actor, UUID(str(saved["id"])))

    case = await run_idempotent(
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
    assert isinstance(case, CaseDetail)
    return _with_etag(response, case)


def _body(body: BaseModel | None, version: int | None = None) -> dict[str, Any]:
    return {"body": body.model_dump(mode="json") if body else None, "if_match": version}


# ------------------------------------------------------------------ o'qish


@router.get("", response_model=CaseList)
async def list_cases(
    ctx: CanView,
    svc: Support,
    status: Annotated[list[CaseStatus] | None, BeforeValidator(split_commas), Query()] = None,
    resolution: Resolution | None = None,
    source: CaseSource | None = None,
    branch_id: UUID | None = None,
    sku_id: UUID | None = None,
    assigned: Annotated[
        str | None, Query(max_length=40, description='"me", "unassigned" yoki xodim (membership) ID')
    ] = None,
    q: Annotated[
        str | None,
        Query(max_length=100, description="Raqam (K-12), telefon, xaridor ismi yoki mahsulot nomi"),
    ] = None,
    number: Annotated[int | None, Query(ge=1, le=2_147_483_647, description="Aniq murojaat raqami")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> CaseList:
    return await svc.cases.list_cases(
        ctx.db,
        ctx.actor,
        status=list(status) if status else None,
        resolution=resolution,
        branch_id=branch_id,
        source=source,
        assigned=assigned,
        q=q,
        sku_id=sku_id,
        number=number,
        limit=limit,
        cursor=cursor,
    )


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: UUID, response: Response, ctx: CanView, svc: Support) -> CaseDetail:
    """Murojaat kartochkasi: sotuv va kafolat nusxasi, izohlar, rasmlar, ombor holati, tarix."""
    return _with_etag(response, await svc.cases.get(ctx.db, ctx.actor, case_id))


# ------------------------------------------------------------------ ochish


@router.post("", response_model=CaseDetail, status_code=status.HTTP_201_CREATED)
async def open_case(
    body: CaseOpenIn, request: Request, response: Response, ctx: CanOpen, svc: Support, key: IdemKey
) -> CaseDetail:
    """Buyurtma qatori, tez sotuv qatori yoki tizimdan oldingi sotuv (chek) bo'yicha ochiladi.

    Kafolat muddati tugagan bo'lsa — 422 `WARRANTY_EXPIRED`; menejer/ega `warranty_override_reason` bilan
    ochishi mumkin.
    """
    case = await _command(
        ctx,
        svc,
        response,
        "support.case.open",
        key,
        body,
        lambda: svc.cases.open(ctx.db, ctx.actor, body),
        status_code=201,
    )
    set_location(request, response, "get_case", case_id=case.id)
    return case


# ------------------------------------------------------------------ holat o'tishlari (FSM-11)


@router.post("/{case_id}/start-review", response_model=CaseDetail)
async def start_review(
    case_id: UUID,
    response: Response,
    ctx: CanService,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
    body: CaseStartReviewIn | None = None,
) -> CaseDetail:
    data = body or CaseStartReviewIn()
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.start_review:{case_id}",
        key,
        _body(data, version),
        lambda: svc.lifecycle.start_review(ctx.db, ctx.actor, case_id, version, data),
    )


@router.post("/{case_id}/approve", response_model=CaseDetail)
async def approve(
    case_id: UUID,
    body: CaseApproveIn,
    response: Response,
    ctx: CanDecide,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
) -> CaseDetail:
    """Qabul qilish + qaror turi (REPAIR / REPLACE / REFUND). Faqat menejer yoki ega (DEC-130)."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.approve:{case_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.approve(ctx.db, ctx.actor, case_id, version, body),
    )


@router.post("/{case_id}/reject", response_model=CaseDetail)
async def reject(
    case_id: UUID,
    body: CaseRejectIn,
    response: Response,
    ctx: CanDecide,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
) -> CaseDetail:
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.reject:{case_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.reject(ctx.db, ctx.actor, case_id, version, body),
    )


@router.post("/{case_id}/start-service", response_model=CaseDetail)
async def start_service(
    case_id: UUID, response: Response, ctx: CanFulfil, svc: Support, key: IdemKey, version: IfMatch
) -> CaseDetail:
    """Xizmatni boshlash. Mahsulot do'konda bo'lishi shart. REPLACE/REFUND — qaytgan dona karantinga."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.start_service:{case_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.start_service(ctx.db, ctx.actor, case_id, version),
    )


@router.post("/{case_id}/resolve", response_model=CaseDetail)
async def resolve(
    case_id: UUID,
    response: Response,
    ctx: CanFulfil,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
    body: CaseResolveIn | None = None,
) -> CaseDetail:
    """Hal qilindi. REPLACE — yangi dona ombordan chiqadi (mavjud son yetmasa 409)."""
    data = body or CaseResolveIn()
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.resolve:{case_id}",
        key,
        _body(data, version),
        lambda: svc.lifecycle.resolve(ctx.db, ctx.actor, case_id, version, data),
    )


@router.post("/{case_id}/close", response_model=CaseDetail)
async def close(
    case_id: UUID, response: Response, ctx: CanService, svc: Support, key: IdemKey, version: IfMatch
) -> CaseDetail:
    """Xaridor tasdiqladi. Aks holda `RESOLVED` dan 7 kun o'tgach tizim yopadi."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.close:{case_id}",
        key,
        _body(None, version),
        lambda: svc.lifecycle.close(ctx.db, ctx.actor, case_id, version),
    )


# ------------------------------------------------------------------ holatsiz o'zgarishlar


@router.post("/{case_id}/resolution", response_model=CaseDetail)
async def change_resolution(
    case_id: UUID,
    body: CaseResolutionChangeIn,
    response: Response,
    ctx: CanDecide,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
) -> CaseDetail:
    """Qaror turini o'zgartirish ("ta'mirlab bo'lmadi, almashtiramiz"): `APPROVED` / `IN_SERVICE`."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.resolution:{case_id}",
        key,
        _body(body, version),
        lambda: svc.lifecycle.change_resolution(ctx.db, ctx.actor, case_id, version, body),
    )


@router.post("/{case_id}/receive-item", response_model=CaseDetail)
async def receive_item(
    case_id: UUID,
    response: Response,
    ctx: CanService,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
    body: CaseReceiveItemIn | None = None,
) -> CaseDetail:
    """Mahsulot do'konga jismonan topshirildi."""
    data = body or CaseReceiveItemIn()
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.receive_item:{case_id}",
        key,
        _body(data, version),
        lambda: svc.cases.receive_item(ctx.db, ctx.actor, case_id, version, data),
    )


@router.post("/{case_id}/assign", response_model=CaseDetail)
async def assign(
    case_id: UUID,
    body: CaseAssignIn,
    response: Response,
    ctx: CanDecide,
    svc: Support,
    key: IdemKey,
    version: IfMatch,
) -> CaseDetail:
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.assign:{case_id}",
        key,
        _body(body, version),
        lambda: svc.cases.assign(ctx.db, ctx.actor, case_id, version, body),
    )


@router.post("/{case_id}/notify-ready", response_model=CaseDetail)
async def notify_ready(
    case_id: UUID, response: Response, ctx: CanService, svc: Support, key: IdemKey
) -> CaseDetail:
    """ "Xaridorga xabar berish": mahsulot tayyor. Murojaat suhbatga bog'langan bo'lsa xabar ketadi."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.notify_ready:{case_id}",
        key,
        _body(None),
        lambda: svc.lifecycle.notify_ready(ctx.db, ctx.actor, case_id),
    )


@router.post("/{case_id}/notes", response_model=CaseDetail, status_code=status.HTTP_201_CREATED)
async def add_note(
    case_id: UUID, body: CaseNoteIn, response: Response, ctx: CanService, svc: Support, key: IdemKey
) -> CaseDetail:
    """Ichki izoh (xaridorga ko'rinmaydi). `DIAGNOSIS` — faqat `IN_REVIEW` da."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.note:{case_id}",
        key,
        _body(body),
        lambda: svc.cases.add_note(ctx.db, ctx.actor, case_id, body),
        status_code=201,
    )


@router.post("/{case_id}/attachments", response_model=CaseDetail, status_code=status.HTTP_201_CREATED)
async def add_attachment(
    case_id: UUID, body: CaseAttachmentIn, response: Response, ctx: CanService, svc: Support, key: IdemKey
) -> CaseDetail:
    """Rasm: avval `POST /files?purpose=SUPPORT_EVIDENCE`, keyin shu yerda biriktiriladi (ko'pi bilan 10)."""
    return await _command(
        ctx,
        svc,
        response,
        f"support.case.attachment:{case_id}",
        key,
        _body(body),
        lambda: svc.cases.add_attachment(ctx.db, ctx.actor, case_id, body),
        status_code=201,
    )
