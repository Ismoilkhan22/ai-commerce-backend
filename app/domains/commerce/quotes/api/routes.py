"""Shop paneli: leadlar, PC takliflari va "PC yig'ish" sahifasi (6a; FSM-05, FSM-06; DEC-142 taklif).

Yozish so'rovlari idempotent: takror himoyasi jadvaliga faqat ID yoziladi (lead kontakti va havola tokeni
saqlanmaydi, 26 §4) — takroriy so'rov joriy holatni qaytaradi. "Yuborish" ning takrori — yangi havola.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from pydantic import BaseModel, BeforeValidator

from app.domains.commerce import permissions as perm
from app.domains.commerce.providers import CommerceServices, commerce_services
from app.domains.commerce.quotes.schemas import (
    BuildCheckIn,
    BuildCheckOut,
    CandidatesIn,
    CandidatesOut,
    History,
    LeadAssignIn,
    LeadCounts,
    LeadCreate,
    LeadList,
    LeadLoseIn,
    LeadOut,
    LeadStatus,
    LeadUpdate,
    QuoteAcceptOut,
    QuoteApproveIn,
    QuoteCreate,
    QuoteLinesIn,
    QuoteList,
    QuoteOptionalReasonIn,
    QuoteOut,
    QuoteSendOut,
    QuoteStatus,
    ReasonIn,
    RevisionOut,
)
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, set_location, split_commas
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

leads_router = APIRouter(prefix="/leads", tags=["commerce_leads"])
quotes_router = APIRouter(prefix="/quotes", tags=["commerce_quotes"])
builds_router = APIRouter(prefix="/pc-builds", tags=["commerce_quotes"])

Commerce = Annotated[CommerceServices, Depends(commerce_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]

CanViewLeads = Annotated[RequestContext, Depends(require_permission(perm.LEAD_VIEW))]
CanManageLeads = Annotated[RequestContext, Depends(require_permission(perm.LEAD_MANAGE))]
CanAssignLeads = Annotated[RequestContext, Depends(require_permission(perm.LEAD_ASSIGN))]
CanViewQuotes = Annotated[RequestContext, Depends(require_permission(perm.QUOTE_VIEW))]
CanEditQuotes = Annotated[RequestContext, Depends(require_permission(perm.QUOTE_EDIT))]
CanApproveQuotes = Annotated[RequestContext, Depends(require_permission(perm.QUOTE_APPROVE))]
CanSendQuotes = Annotated[RequestContext, Depends(require_permission(perm.QUOTE_SEND))]


def _etag(response: Response, out: Any) -> Any:
    response.headers["ETag"] = etag(out.version)
    return out


def _body(body: BaseModel | None, version: int) -> dict[str, Any]:
    return {"body": body.model_dump(mode="json") if body else None, "if_match": version}


async def _idempotent(
    ctx: RequestContext,
    operation: str,
    key: str,
    body: BaseModel | dict[str, Any] | None,
    produce: Callable[[], Awaitable[Any]],
    replay: Callable[[UUID], Awaitable[Any]],
    *,
    code: int = status.HTTP_200_OK,
) -> Any:
    async def on_replay(saved: Any) -> Any:
        return await replay(UUID(str(saved["id"])))

    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        operation,
        key,
        body,
        produce,
        stored=lambda out: {"id": str(out.id)},
        on_replay=on_replay,
        status=code,
    )


# ================================================================== leadlar


@leads_router.get("", response_model=LeadList)
async def list_leads(
    ctx: CanViewLeads,
    svc: Commerce,
    status: Annotated[list[LeadStatus] | None, BeforeValidator(split_commas), Query()] = None,
    assigned: Annotated[
        str | None, Query(max_length=40, description='"me", "unassigned" yoki xodim ID')
    ] = None,
    q: Annotated[str | None, Query(max_length=100, description="Raqam (L-57) yoki xaridor ismi")] = None,
    source: Annotated[Literal["AI", "STAFF"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> LeadList:
    """Kanban/ro'yxat: operator — o'ziga biriktirilgan va biriktirilmaganlar; ega/menejer — hammasi."""
    return await svc.leads.list_leads(
        ctx.db,
        ctx.actor,
        statuses=list(status or []),
        assigned=assigned,
        q=q,
        source=source,
        limit=limit,
        cursor=cursor,
    )


@leads_router.get("/counts", response_model=LeadCounts)
async def lead_counts(ctx: CanViewLeads, svc: Commerce) -> LeadCounts:
    return await svc.leads.counts(ctx.db, ctx.actor)


@leads_router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate, request: Request, response: Response, ctx: CanManageLeads, svc: Commerce, key: IdemKey
) -> LeadOut:
    """Qo'lda yoki suhbatdan. Suhbatda ochiq lead bo'lsa — o'sha qaytadi (bitta suhbat — bitta ochiq lead)."""

    async def produce() -> LeadOut:
        lead = await svc.leads.create(ctx.db, ctx.actor, body)
        return await svc.leads.detail(ctx.db, ctx.actor, lead)

    out = await _idempotent(
        ctx,
        "commerce.lead.create",
        key,
        body,
        produce,
        lambda lead_id: svc.leads.get(ctx.db, ctx.actor, lead_id),
        code=status.HTTP_201_CREATED,
    )
    set_location(request, response, "get_lead", lead_id=out.id)
    return _etag(response, out)  # type: ignore[no-any-return]


@leads_router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: UUID, response: Response, ctx: CanViewLeads, svc: Commerce) -> LeadOut:
    return _etag(response, await svc.leads.get(ctx.db, ctx.actor, lead_id))  # type: ignore[no-any-return]


@leads_router.get("/{lead_id}/history", response_model=History)
async def lead_history(lead_id: UUID, ctx: CanViewLeads, svc: Commerce) -> History:
    return await svc.leads.history(ctx.db, ctx.actor, lead_id)


@leads_router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID, body: LeadUpdate, response: Response, ctx: CanManageLeads, svc: Commerce, version: IfMatch
) -> LeadOut:
    return _etag(response, await svc.leads.update(ctx.db, ctx.actor, lead_id, version, body))  # type: ignore[no-any-return]


@leads_router.post("/{lead_id}/qualify", response_model=LeadOut)
async def qualify_lead(
    lead_id: UUID, response: Response, ctx: CanManageLeads, svc: Commerce, version: IfMatch
) -> LeadOut:
    return _etag(response, await svc.leads.qualify(ctx.db, ctx.actor, lead_id, version))  # type: ignore[no-any-return]


@leads_router.post("/{lead_id}/lose", response_model=LeadOut)
async def lose_lead(
    lead_id: UUID, body: LeadLoseIn, response: Response, ctx: CanManageLeads, svc: Commerce, version: IfMatch
) -> LeadOut:
    """Yo'qotildi — faqat xodim, sabab bilan (DEC-142 Q2)."""
    out = await svc.quotes.lose_lead(ctx.db, ctx.actor, lead_id, version, body.reason, body.note)
    return _etag(response, out)  # type: ignore[no-any-return]


@leads_router.post("/{lead_id}/reopen", response_model=LeadOut)
async def reopen_lead(
    lead_id: UUID, response: Response, ctx: CanManageLeads, svc: Commerce, version: IfMatch
) -> LeadOut:
    return _etag(response, await svc.leads.reopen(ctx.db, ctx.actor, lead_id, version))  # type: ignore[no-any-return]


@leads_router.post("/{lead_id}/take", response_model=LeadOut)
async def take_lead(
    lead_id: UUID, response: Response, ctx: CanManageLeads, svc: Commerce, version: IfMatch
) -> LeadOut:
    """Biriktirilmagan lead — o'ziga olish (operator navbati)."""
    return _etag(response, await svc.leads.take(ctx.db, ctx.actor, lead_id, version))  # type: ignore[no-any-return]


@leads_router.post("/{lead_id}/assign", response_model=LeadOut)
async def assign_lead(
    lead_id: UUID,
    body: LeadAssignIn,
    response: Response,
    ctx: CanAssignLeads,
    svc: Commerce,
    version: IfMatch,
) -> LeadOut:
    out = await svc.leads.assign(ctx.db, ctx.actor, lead_id, version, body.membership_id)
    return _etag(response, out)  # type: ignore[no-any-return]


# ================================================================== takliflar


@quotes_router.get("", response_model=QuoteList)
async def list_quotes(
    ctx: CanViewQuotes,
    svc: Commerce,
    status: Annotated[list[QuoteStatus] | None, BeforeValidator(split_commas), Query()] = None,
    lead_id: UUID | None = None,
    mine: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> QuoteList:
    """Tasdiq navbati: `status=REVIEW`."""
    return await svc.quotes.list_quotes(
        ctx.db, ctx.actor, statuses=list(status or []), lead_id=lead_id, mine=mine, limit=limit, cursor=cursor
    )


@quotes_router.post("", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
async def create_quote(
    body: QuoteCreate, request: Request, response: Response, ctx: CanEditQuotes, svc: Commerce, key: IdemKey
) -> QuoteOut:
    """Qoralama (DRAFT). Lead berilmasa — avtomatik ochiladi. Narx katalogdan (BL-041)."""
    out = await _idempotent(
        ctx,
        "commerce.quote.create",
        key,
        body,
        lambda: svc.quotes.create(ctx.db, ctx.actor, body),
        lambda quote_id: svc.quotes.get(ctx.db, ctx.actor, quote_id),
        code=status.HTTP_201_CREATED,
    )
    set_location(request, response, "get_quote", quote_id=out.id)
    return _etag(response, out)  # type: ignore[no-any-return]


@quotes_router.get("/{quote_id}", response_model=QuoteOut)
async def get_quote(quote_id: UUID, response: Response, ctx: CanViewQuotes, svc: Commerce) -> QuoteOut:
    """Qoralamada moslik jonli tekshiriladi; keyin — muzlagan natija (BL-030)."""
    return _etag(response, await svc.quotes.get(ctx.db, ctx.actor, quote_id))  # type: ignore[no-any-return]


@quotes_router.get("/{quote_id}/revisions/{revision}", response_model=RevisionOut)
async def get_quote_revision(
    quote_id: UUID,
    revision: Annotated[int, Path(ge=1, le=10_000)],
    ctx: CanViewQuotes,
    svc: Commerce,
) -> RevisionOut:
    """Eski versiya: qatorlar, jami va har bosqichdagi muzlagan moslik."""
    return await svc.quotes.revision_detail(ctx.db, ctx.actor, quote_id, revision)


@quotes_router.get("/{quote_id}/history", response_model=History)
async def quote_history(quote_id: UUID, ctx: CanViewQuotes, svc: Commerce) -> History:
    return await svc.quotes.history(ctx.db, ctx.actor, quote_id)


@quotes_router.put("/{quote_id}/lines", response_model=QuoteOut)
async def set_quote_lines(
    quote_id: UUID,
    body: QuoteLinesIn,
    response: Response,
    ctx: CanEditQuotes,
    svc: Commerce,
    version: IfMatch,
) -> QuoteOut:
    """Qoralama qatorlarini almashtiradi (to'liq ro'yxat). Chegirma — faqat xodim; limit — tasdiqda."""
    out = await svc.quotes.set_lines(ctx.db, ctx.actor, quote_id, version, body.lines)
    return _etag(response, out)  # type: ignore[no-any-return]


async def _quote_cmd(
    ctx: RequestContext,
    svc: CommerceServices,
    response: Response,
    name: str,
    key: str,
    quote_id: UUID,
    version: int,
    body: BaseModel | None,
    produce: Callable[[], Awaitable[QuoteOut]],
) -> QuoteOut:
    """Holat buyrug'i: If-Match + Idempotency-Key, takrorda — joriy holat."""
    out = await _idempotent(
        ctx,
        f"commerce.quote.{name}",
        key,
        {"quote_id": str(quote_id), **_body(body, version)},
        produce,
        lambda qid: svc.quotes.get(ctx.db, ctx.actor, qid),
    )
    return _etag(response, out)  # type: ignore[no-any-return]


@quotes_router.post("/{quote_id}/submit", response_model=QuoteOut)
async def submit_quote(
    quote_id: UUID, response: Response, ctx: CanEditQuotes, svc: Commerce, key: IdemKey, version: IfMatch
) -> QuoteOut:
    """Tekshiruvga: moslik BLOCK bo'lsa o'tmaydi; RISKY_ONLY + PASS + chegirmasiz — avto-tasdiq (DEC-102)."""
    return await _quote_cmd(
        ctx,
        svc,
        response,
        "submit",
        key,
        quote_id,
        version,
        None,
        lambda: svc.quotes.submit(ctx.db, ctx.actor, quote_id, version),
    )


@quotes_router.post("/{quote_id}/approve", response_model=QuoteOut)
async def approve_quote(
    quote_id: UUID,
    body: QuoteApproveIn,
    response: Response,
    ctx: CanApproveQuotes,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> QuoteOut:
    """Tasdiq: o'zi tuzganini emas (DEC-109), chegirma limitida (DEC-110); REVIEW_REQUIRED — dalil."""
    return await _quote_cmd(
        ctx,
        svc,
        response,
        "approve",
        key,
        quote_id,
        version,
        body,
        lambda: svc.quotes.approve(ctx.db, ctx.actor, quote_id, version, body.note),
    )


@quotes_router.post("/{quote_id}/return", response_model=QuoteOut)
async def return_quote(
    quote_id: UUID,
    body: ReasonIn,
    response: Response,
    ctx: CanApproveQuotes,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> QuoteOut:
    """Qaytarish: yangi versiya (qoralama), sabab bilan."""
    return await _quote_cmd(
        ctx,
        svc,
        response,
        "return",
        key,
        quote_id,
        version,
        body,
        lambda: svc.quotes.return_(ctx.db, ctx.actor, quote_id, version, body.reason),
    )


@quotes_router.post("/{quote_id}/reject", response_model=QuoteOut)
async def reject_quote(
    quote_id: UUID,
    body: ReasonIn,
    response: Response,
    ctx: CanSendQuotes,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> QuoteOut:
    """Xaridor rad etdi (xodim belgilaydi)."""
    return await _quote_cmd(
        ctx,
        svc,
        response,
        "reject",
        key,
        quote_id,
        version,
        body,
        lambda: svc.quotes.reject(ctx.db, ctx.actor, quote_id, version, body.reason),
    )


@quotes_router.post("/{quote_id}/revise", response_model=QuoteOut)
async def revise_quote(
    quote_id: UUID, response: Response, ctx: CanEditQuotes, svc: Commerce, key: IdemKey, version: IfMatch
) -> QuoteOut:
    """Yangi versiya (yuborilgan, rad etilgan yoki muddati o'tgan) — eski havola bekor."""
    return await _quote_cmd(
        ctx,
        svc,
        response,
        "revise",
        key,
        quote_id,
        version,
        None,
        lambda: svc.quotes.revise(ctx.db, ctx.actor, quote_id, version),
    )


@quotes_router.post("/{quote_id}/cancel", response_model=QuoteOut)
async def cancel_quote(
    quote_id: UUID,
    body: QuoteOptionalReasonIn,
    response: Response,
    ctx: CanEditQuotes,
    svc: Commerce,
    key: IdemKey,
    version: IfMatch,
) -> QuoteOut:
    return await _quote_cmd(
        ctx,
        svc,
        response,
        "cancel",
        key,
        quote_id,
        version,
        body,
        lambda: svc.quotes.cancel(ctx.db, ctx.actor, quote_id, version, body.reason),
    )


@quotes_router.post("/{quote_id}/send", response_model=QuoteSendOut)
async def send_quote(
    quote_id: UUID, response: Response, ctx: CanSendQuotes, svc: Commerce, key: IdemKey, version: IfMatch
) -> QuoteSendOut:
    """Tasdiqlangan taklif → xaridor havolasi (`/q/{token}`, sayt domenida). Token faqat shu javobda.
    Takroriy so'rov — yangi havola, eskisi ishlamaydi. Havolani suhbatga operator inbox orqali yuboradi."""

    async def produce() -> QuoteSendOut:
        out, token = await svc.quotes.send(ctx.db, ctx.actor, quote_id, version)
        return await _send_out(svc, ctx, out, token)

    async def replay(saved: Any) -> QuoteSendOut:
        out, token = await svc.quotes.reissue_link(ctx.db, ctx.actor, UUID(str(saved["id"])))
        return await _send_out(svc, ctx, out, token)

    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "commerce.quote.send",
        key,
        {"quote_id": str(quote_id), "if_match": version},
        produce,
        stored=lambda out: {"id": str(out.quote.id)},  # token jadvalga yozilmaydi
        on_replay=replay,
    )
    assert isinstance(result, QuoteSendOut)
    response.headers["ETag"] = etag(result.quote.version)
    response.headers["Cache-Control"] = "no-store"
    return result


async def _send_out(svc: CommerceServices, ctx: RequestContext, out: QuoteOut, token: str) -> QuoteSendOut:
    assert ctx.actor.shop_id is not None
    return QuoteSendOut(
        quote=out,
        public_path=f"/q/{token}",
        public_url=await svc.quotes.public_url(ctx.db, ctx.actor.shop_id, token),
    )


@quotes_router.post("/{quote_id}/accept", response_model=QuoteAcceptOut)
async def accept_quote(
    quote_id: UUID, response: Response, ctx: CanSendQuotes, svc: Commerce, key: IdemKey, version: IfMatch
) -> QuoteAcceptOut:
    """Xaridor chatda/telefonda "olaman" dedi — xodim qo'lda belgilaydi (Q5); narx va moslik qayta."""

    async def produce() -> QuoteAcceptOut:
        out, order = await svc.quotes.accept_by_staff(ctx.db, ctx.actor, quote_id, version)
        return QuoteAcceptOut(quote=out, order_id=order.id, order_number=order.number)

    async def replay(saved: Any) -> QuoteAcceptOut:
        out = await svc.quotes.get(ctx.db, ctx.actor, UUID(str(saved["id"])))
        order = (
            await svc.orders.get(ctx.db, ctx.actor, out.accepted_order_id) if out.accepted_order_id else None
        )
        assert order is not None
        return QuoteAcceptOut(quote=out, order_id=order.id, order_number=order.number)

    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "commerce.quote.accept",
        key,
        {"quote_id": str(quote_id), "if_match": version},
        produce,
        stored=lambda out: {"id": str(out.quote.id)},
        on_replay=replay,
    )
    assert isinstance(result, QuoteAcceptOut)
    response.headers["ETag"] = etag(result.quote.version)
    return result


# ================================================================== PC yig'ish sahifasi


@builds_router.post("/check", response_model=BuildCheckOut)
async def check_build(body: BuildCheckIn, ctx: CanEditQuotes, svc: Commerce) -> BuildCheckOut:
    """Yig'ma tekshiruvi: moslik (engine), narx, mavjudlik. Hech narsa saqlanmaydi."""
    return await svc.builds.check(ctx.db, ctx.actor, body)


@builds_router.post("/candidates", response_model=CandidatesOut)
async def build_candidates(body: CandidatesIn, ctx: CanEditQuotes, svc: Commerce) -> CandidatesOut:
    """Slot uchun nomzodlar: joriy yig'ma bilan tekshirilgan, mosi va mavjudi birinchi."""
    return await svc.builds.candidates(ctx.db, ctx.actor, body)
