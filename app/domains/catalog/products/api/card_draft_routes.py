"""Shop paneli: rasm yoki nomdan mahsulot kartochkasi qoralamasi (DEC-149, 3-qism).

POST /shop/files?purpose=PRODUCT_IMAGE → POST /products/ai-draft {file_id?, name?} → forma to'ldiriladi
→ ega tekshiradi → odatdagi POST /products (QORALAMA). Hech narsa saqlanmaydi, narx AI'dan olinmaydi.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.domains.catalog.products.services.card_draft import CardDraftIn, CardDraftOut
from app.domains.catalog.providers import catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(tags=["catalog"])

CanEdit = Annotated[RequestContext, Depends(require_permission("catalog.product.edit"))]
PER_USER_PER_MIN = 10
PER_SHOP_PER_MIN = 30


@router.post("/products/ai-draft", response_model=CardDraftOut)
async def product_ai_draft(body: CardDraftIn, request: Request, ctx: CanEdit) -> CardDraftOut:
    """AI sozlanmagan yoki limit tugagan — 422 (`ai_unavailable`); provayder xatosi — 503."""
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"card-draft:{ctx.actor.shop_id}:{ctx.actor.actor_id}", limit=PER_USER_PER_MIN)
    await enforce(limiter, f"card-draft:{ctx.actor.shop_id}", limit=PER_SHOP_PER_MIN)
    return await catalog_services(request).card_drafts.draft(request.app.state.db, ctx.actor, body)
