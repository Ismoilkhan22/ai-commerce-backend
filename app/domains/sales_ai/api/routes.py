"""Shop paneli: AI sotuvchi — `/api/v1/shop/ai/*` va suhbat ichidagi AI —
`/api/v1/shop/conversations/{id}/ai/*`.

Sozlamalar va bilim bazasi — ega o'zgartiradi (menejer ko'radi); sinov oynasi — ega va menejer; takliflar va
navbat izi — inbox'dagi xodim (operator — o'z suhbatlarida). O'zgartirish (sozlama, bilim bandi, e'lon,
chiqarish) — `If-Match`; yaratish va taklifni yuborish — `Idempotency-Key`. Sinov oynasi va taklifni rad
etish — kalitsiz: birinchisi bazaga hech narsa yozmaydi, ikkinchisi holat bo'yicha o'z-o'zidan idempotent.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.domains.sales_ai import permissions as perm
from app.domains.sales_ai.eval.schemas import QualityOut
from app.domains.sales_ai.providers import SalesAiServices, sales_ai_services
from app.domains.sales_ai.schemas import (
    AiSettingsOut,
    AiSettingsPatch,
    AiStatusOut,
    KnowledgeIn,
    KnowledgeList,
    KnowledgeOut,
    KnowledgePatch,
    SandboxIn,
    SandboxOut,
    SuggestionDiscardIn,
    SuggestionList,
    SuggestionSendIn,
    SuggestionSentOut,
    TurnList,
)
from app.domains.sales_ai.services.review import AiReviewService
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.ratelimit import RateLimiter, enforce

SANDBOX_PER_USER_PER_MIN = 20
SANDBOX_PER_SHOP_PER_MIN = 60

router = APIRouter(prefix="/ai", tags=["sales_ai"])
conversation_router = APIRouter(prefix="/conversations/{conversation_id}/ai", tags=["sales_ai"])

SalesAi = Annotated[SalesAiServices, Depends(sales_ai_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.SETTINGS_VIEW))]
CanEdit = Annotated[RequestContext, Depends(require_permission(perm.SETTINGS_EDIT))]
CanTest = Annotated[RequestContext, Depends(require_permission(perm.KNOWLEDGE_TEST))]
CanReview = Annotated[RequestContext, Depends(require_permission(perm.SUGGESTION_REVIEW))]


def _review(svc: SalesAiServices) -> AiReviewService:
    assert svc.review is not None
    return svc.review


# ------------------------------------------------------------------ sozlamalar va holat
@router.get("/settings", response_model=AiSettingsOut)
async def get_settings(response: Response, ctx: CanView, svc: SalesAi) -> AiSettingsOut:
    """Rejim, ish vaqti, limitlar, profil va AUTO'ga tayyorlik (`auto_readiness` — maslahat)."""
    out = await svc.panel.get_settings(ctx.db, ctx.actor)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("/quality", response_model=QualityOut)
async def get_quality(
    ctx: CanView, svc: SalesAi, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> QualityOut:
    """ "AI sifati" (6c): operator bahosi (tahrirsiz / tahrirlangan / rad etilgan), operatorga uzatishlar va
    sabablari, javob tekshiruvi (validator) urilishlari, xarajat (suhbatga), kunma-kun; AUTO tayyorligi."""
    assert ctx.actor.shop_id is not None
    return await svc.quality.quality(ctx.db, ctx.actor.shop_id, days)


@router.patch("/settings", response_model=AiSettingsOut)
async def update_settings(
    body: AiSettingsPatch, response: Response, ctx: CanEdit, svc: SalesAi, version: IfMatch
) -> AiSettingsOut:
    """Faqat yuborilgan maydonlar. Provayder sozlanmagan bo'lsa rejimni yoqib bo'lmaydi
    (409 `AI_NOT_CONFIGURED`)."""
    out = await svc.panel.patch_settings(ctx.db, ctx.actor, version, body)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("/status", response_model=AiStatusOut)
async def get_status(ctx: CanView, svc: SalesAi) -> AiStatusOut:
    """Hozir AI ishlayaptimi (yo'q bo'lsa — sabab), bugungi navbatlar va xarajat (USD micros)."""
    return await svc.panel.status(ctx.db, ctx.actor)


# ------------------------------------------------------------------ bilim bazasi
@router.get("/knowledge", response_model=KnowledgeList)
async def list_knowledge(ctx: CanView, svc: SalesAi) -> KnowledgeList:
    return await svc.panel.list_knowledge(ctx.db, ctx.actor)


@router.post("/knowledge", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    body: KnowledgeIn, response: Response, ctx: CanEdit, svc: SalesAi, key: IdemKey
) -> KnowledgeOut:
    """Yangi band — DRAFT (AI hali ko'rmaydi)."""
    assert ctx.actor.shop_id is not None
    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "sales_ai.knowledge.create",
        key,
        body,
        lambda: svc.panel.create_knowledge(ctx.db, ctx.actor, body),
    )
    out = result if isinstance(result, KnowledgeOut) else KnowledgeOut.model_validate(result)
    response.headers["ETag"] = etag(out.version)
    return out


@router.patch("/knowledge/{item_id}", response_model=KnowledgeOut)
async def update_knowledge(
    item_id: UUID, body: KnowledgePatch, response: Response, ctx: CanEdit, svc: SalesAi, version: IfMatch
) -> KnowledgeOut:
    """Tahrir bandni yana DRAFT qiladi — qayta e'lon qilinmaguncha AI eski matnni ham ko'rmaydi."""
    out = await svc.panel.update_knowledge(ctx.db, ctx.actor, item_id, version, body)
    response.headers["ETag"] = etag(out.version)
    return out


@router.post("/knowledge/{item_id}/publish", response_model=KnowledgeOut)
async def publish_knowledge(
    item_id: UUID, response: Response, ctx: CanEdit, svc: SalesAi, version: IfMatch
) -> KnowledgeOut:
    """DRAFT → APPROVED: keyingi navbatdan promptga kiradi. Umumiy hajm chegarasi — 422 `RULE_BLOCK`."""
    out = await svc.panel.publish_knowledge(ctx.db, ctx.actor, item_id, version)
    response.headers["ETag"] = etag(out.version)
    return out


@router.post("/knowledge/{item_id}/retire", response_model=KnowledgeOut)
async def retire_knowledge(
    item_id: UUID, response: Response, ctx: CanEdit, svc: SalesAi, version: IfMatch
) -> KnowledgeOut:
    out = await svc.panel.retire_knowledge(ctx.db, ctx.actor, item_id, version)
    response.headers["ETag"] = etag(out.version)
    return out


# ------------------------------------------------------------------ sinov oynasi
@router.post("/sandbox/messages", response_model=SandboxOut)
async def sandbox_message(body: SandboxIn, request: Request, ctx: CanTest, svc: SalesAi) -> SandboxOut:
    """AI bilan gaplashib ko'rish: haqiqiy suhbat yo'q, qoralamalar yaratilmaydi. Javob va to'liq iz (model,
    token, xarajat, tool chaqiruvlari, validator kodlari). Xodimga 20/daq, shopga 60/daq; xarajat alohida
    sinov limitida — jonli AI limitini yemaydi."""
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(
        limiter, f"ai-sandbox:{ctx.actor.shop_id}:{ctx.actor.actor_id}", limit=SANDBOX_PER_USER_PER_MIN
    )
    await enforce(limiter, f"ai-sandbox:{ctx.actor.shop_id}", limit=SANDBOX_PER_SHOP_PER_MIN)
    return await svc.sandbox.message(request.app.state.db, ctx.actor, body)


@router.delete("/sandbox/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def sandbox_reset(session_id: UUID, ctx: CanTest, svc: SalesAi) -> Response:
    await svc.sandbox.reset(ctx.actor, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ suhbat ichida: takliflar va iz
@conversation_router.get("/suggestions", response_model=SuggestionList)
async def list_suggestions(conversation_id: UUID, ctx: CanReview, svc: SalesAi) -> SuggestionList:
    """SUGGEST: kutilayotgan AI takliflari (`stale` — suhbat o'zgargan, yuborib bo'lmaydi)."""
    return await _review(svc).suggestions(ctx.db, ctx.actor, conversation_id)


@conversation_router.post("/suggestions/{reply_id}/send", response_model=SuggestionSentOut)
async def send_suggestion(
    conversation_id: UUID,
    reply_id: UUID,
    body: SuggestionSendIn,
    ctx: CanReview,
    svc: SalesAi,
    key: IdemKey,
) -> SuggestionSentOut:
    """Taklifni xaridorga yuborish — o'zgartirmay yoki `body` bilan tahrirlab (operator bahosi avtomatik)."""
    assert ctx.actor.shop_id is not None
    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"sales_ai.suggestion.send:{reply_id}",
        key,
        body,
        lambda: _review(svc).send(ctx.db, ctx.actor, conversation_id, reply_id, body),
    )
    return result if isinstance(result, SuggestionSentOut) else SuggestionSentOut.model_validate(result)


@conversation_router.post("/suggestions/{reply_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
async def discard_suggestion(
    conversation_id: UUID,
    reply_id: UUID,
    ctx: CanReview,
    svc: SalesAi,
    body: SuggestionDiscardIn | None = None,
) -> Response:
    await _review(svc).discard(ctx.db, ctx.actor, conversation_id, reply_id, body or SuggestionDiscardIn())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conversation_router.get("/turns", response_model=TurnList)
async def list_turns(conversation_id: UUID, ctx: CanReview, svc: SalesAi) -> TurnList:
    """AI navbatlari izi (oxirgi 50): natija, sabab, model, xarajat, tool chaqiruvlari — shaxsiy
    ma'lumotsiz."""
    return await _review(svc).turns(ctx.db, ctx.actor, conversation_id)
