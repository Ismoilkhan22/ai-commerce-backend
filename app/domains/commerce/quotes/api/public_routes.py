"""Sayt (anonim): PC taklifi havolasi — `/api/v1/storefront/{slug}/quotes/{token}` (DEC-142 Q5).

So'rov chegarasi: ko'rish — IP bo'yicha daqiqasiga 30 ta (token taxmin qilinmasin); qabul va rad — IP bo'yicha
10 daqiqada 10 ta. Sayt vaqtincha yopilgan bo'lsa ham xaridor o'z taklifini ko'radi; shop yopilgan — 404.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.domains.commerce.providers import CommerceServices, commerce_services
from app.domains.commerce.quotes.schemas import PublicAcceptOut, PublicQuoteOut, PublicRejectIn
from app.domains.commerce.quotes.services.public_service import Accepted
from app.shared.client_ip import client_ip
from app.shared.db.session import Database
from app.shared.errors.base import DomainError
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(tags=["storefront_quotes"])

Commerce = Annotated[CommerceServices, Depends(commerce_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]

VIEW_LIMIT_PER_MINUTE = 30
ACTION_LIMIT = 10
ACTION_WINDOW_S = 600


def _strip_internal(exc: DomainError) -> None:
    """Xaridorga ichki ID ko'rsatilmaydi (11 §6.3): qatorda nom va narx qoladi, `sku_id` olib tashlanadi."""
    details = {k: v for k, v in exc.details.items() if not (k.endswith("_id") or k.endswith("_ids"))}
    lines = details.get("lines")
    if isinstance(lines, list):
        details["lines"] = [
            {k: v for k, v in item.items() if not k.endswith("_id")}
            for item in lines
            if isinstance(item, dict)
        ]
    exc.details = details


@router.get("/quotes/{token}", response_model=PublicQuoteOut)
async def view_quote(
    slug: str, token: str, request: Request, response: Response, svc: Commerce
) -> PublicQuoteOut:
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"sf-quote:{client_ip(request)}", VIEW_LIMIT_PER_MINUTE)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    database: Database = request.app.state.db
    async with database.transaction(read_only=True) as db:
        access = await svc.site.resolve(db, slug)
        return await svc.public_quotes.view(db, access.shop_id, token)


@router.post("/quotes/{token}/accept", response_model=PublicAcceptOut)
async def accept_quote(
    slug: str, token: str, request: Request, response: Response, svc: Commerce, key: IdemKey
) -> Any:
    """ "Qabul qilaman": narx va moslik qayta tekshiriladi; o'zgargan bo'lsa QUOTE_CHANGED (yangi versiyani
    kuting). Aks holda buyurtma qoralamasi — operator bog'lanadi. Javobda buyurtma holati havolasi."""
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"sf-quote-act:{client_ip(request)}", ACTION_LIMIT, ACTION_WINDOW_S)
    response.headers["Cache-Control"] = "no-store"
    database: Database = request.app.state.db
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)

        async def replay(saved: Any) -> PublicAcceptOut:
            return (await svc.public_quotes.reissue(db, access.shop_id, UUID(str(saved["order_id"])))).out

        try:
            result = await run_idempotent(
                db,
                access.shop_id,
                "storefront.quote_accept",
                key,
                {"token": token},  # so'rov xeshi kalitli (HMAC) — token jadvalga yozilmaydi
                lambda: svc.public_quotes.accept(db, access.shop_id, token),
                stored=lambda accepted: {"order_id": str(accepted.order_id)},
                on_replay=replay,
            )
        except DomainError as exc:
            _strip_internal(exc)
            raise
    return result.out if isinstance(result, Accepted) else result


@router.post("/quotes/{token}/reject", response_model=PublicQuoteOut)
async def reject_quote(
    slug: str, token: str, body: PublicRejectIn, request: Request, response: Response, svc: Commerce
) -> PublicQuoteOut:
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"sf-quote-act:{client_ip(request)}", ACTION_LIMIT, ACTION_WINDOW_S)
    response.headers["Cache-Control"] = "no-store"
    database: Database = request.app.state.db
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)
        return await svc.public_quotes.reject(db, access.shop_id, token, body.reason)
