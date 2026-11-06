"""Xaridor akkaunti (Stage 3 davomi) — `/api/v1/public/marketplace/{auth,me}/*`, db/marketplace.md.

SMS kod bilan kirish, sessiya (Bearer), tarix, sevimlilar, maslahatchi suhbati. Hamma `/me/*` so'rov joriy
xaridor bilan cheklangan (boshqa xaridorning ma'lumoti ko'rinmaydi va o'chirilmaydi). Limit: kod so'rash IP
bo'yicha 10/soat, tasdiqlash 30/soat.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domains.network.models.orm import (
    Buyer,
    BuyerAdvisorMessage,
    BuyerFavorite,
    BuyerSearch,
    BuyerView,
)
from app.domains.network.query_port import NetworkQueryPortImpl
from app.domains.network.services.buyers import (
    ADVISOR_SHOWN,
    MAX_FAVORITES,
    BuyerCtx,
    BuyerOut,
    BuyerPatchIn,
    BuyerService,
    BuyerStartIn,
    BuyerStartOut,
    BuyerVerifyIn,
    BuyerVerifyOut,
)
from app.shared.client_ip import client_ip
from app.shared.db.session import Database
from app.shared.errors.base import NotFoundError, UnauthenticatedError, ValidationError
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(prefix="/marketplace", tags=["marketplace-buyer"])
_port = NetworkQueryPortImpl()
HOUR = 3600
HISTORY_SHOWN = 50  # tarixda ko'rsatiladigan ko'rilgan mahsulot va qidiruvlar soni


def _svc(request: Request) -> BuyerService:
    return request.app.state.network.buyers  # type: ignore[no-any-return]


def _db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


async def optional_buyer(request: Request) -> BuyerCtx | None:
    """Token yo'q yoki yaroqsiz bo'lsa — anonim (xato yo'q)."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return await _svc(request).authenticate(_db(request), token.strip())


async def require_buyer(request: Request) -> BuyerCtx:
    ctx = await optional_buyer(request)
    if ctx is None:
        raise UnauthenticatedError("Buyer session is missing or invalid")
    return ctx


OptionalBuyer = Annotated[BuyerCtx | None, Depends(optional_buyer, scope="function")]
CurrentBuyer = Annotated[BuyerCtx, Depends(require_buyer, scope="function")]


# ------------------------------------------------------------------ kirish
@router.post("/auth/start", response_model=BuyerStartOut, status_code=202)
async def buyer_start(body: BuyerStartIn, request: Request) -> BuyerStartOut:
    ip = client_ip(request)
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"buyer-start:{ip}", limit=10, window_seconds=HOUR)
    async with _db(request).transaction() as db:
        return await _svc(request).start(db, body.phone, ip)


@router.post("/auth/verify", response_model=BuyerVerifyOut)
async def buyer_verify(body: BuyerVerifyIn, request: Request) -> BuyerVerifyOut:
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"buyer-verify:{client_ip(request)}", limit=30, window_seconds=HOUR)
    async with _db(request).transaction() as db:  # noto'g'ri urinish hisoblagichi COMMIT bo'lishi uchun
        result = await _svc(request).verify(db, body.request_id, body.code, request.headers.get("user-agent"))
    if isinstance(result, ValidationError):
        raise result
    return result


@router.post("/auth/logout", status_code=204)
async def buyer_logout(request: Request, ctx: CurrentBuyer) -> Response:
    async with _db(request).transaction() as db:
        await _svc(request).logout(db, ctx)
    return Response(status_code=204)


# ------------------------------------------------------------------ profil
@router.get("/me", response_model=BuyerOut)
async def buyer_me(request: Request, ctx: CurrentBuyer) -> BuyerOut:
    async with _db(request).transaction() as db:
        return await _svc(request).me(db, ctx)


@router.patch("/me", response_model=BuyerOut)
async def buyer_patch(body: BuyerPatchIn, request: Request, ctx: CurrentBuyer) -> BuyerOut:
    async with _db(request).transaction() as db:
        return await _svc(request).patch(db, ctx, body)


@router.delete("/me", status_code=204)
async def buyer_delete(request: Request, ctx: CurrentBuyer) -> Response:
    """Akkauntni va hamma tarixni butunlay o'chiradi."""
    async with _db(request).transaction() as db:
        await _svc(request).delete_account(db, ctx)
    return Response(status_code=204)


# ------------------------------------------------------------------ tarix
class HistoryViewOut(BaseModel):
    canonical_id: UUID
    title: str
    brand: str | None
    min_price_uzs_minor: int | None
    offers_count: int
    viewed_at: datetime


class HistorySearchOut(BaseModel):
    id: UUID
    query: str
    category: str | None
    searched_at: datetime


class HistoryOut(BaseModel):
    views: list[HistoryViewOut]
    searches: list[HistorySearchOut]


@router.get("/me/history", response_model=HistoryOut)
async def buyer_history(request: Request, ctx: CurrentBuyer) -> HistoryOut:
    """Eng yangi ko'rilgan mahsulotlar (hozir ommaviy bo'lmaganlari tushib qoladi) va qidiruvlar."""
    async with _db(request).transaction() as db:
        views = (
            (
                await db.execute(
                    select(BuyerView)
                    .where(BuyerView.buyer_id == ctx.buyer_id)
                    .order_by(BuyerView.viewed_at.desc())
                    .limit(HISTORY_SHOWN * 2)  # ommaviy bo'lmaganlari tushganda ham to'lib chiqsin
                )
            )
            .scalars()
            .all()
        )
        searches = (
            (
                await db.execute(
                    select(BuyerSearch)
                    .where(BuyerSearch.buyer_id == ctx.buyer_id)
                    .order_by(BuyerSearch.searched_at.desc(), BuyerSearch.id.desc())
                    .limit(HISTORY_SHOWN)
                )
            )
            .scalars()
            .all()
        )
        current = await _port.summaries(db, [v.canonical_id for v in views])
    return HistoryOut(
        views=[
            HistoryViewOut(
                canonical_id=v.canonical_id,
                title=current[v.canonical_id].title,
                brand=current[v.canonical_id].brand,
                min_price_uzs_minor=current[v.canonical_id].min_price_uzs_minor,
                offers_count=current[v.canonical_id].offers_count,
                viewed_at=v.viewed_at,
            )
            for v in views
            if v.canonical_id in current
        ][:HISTORY_SHOWN],
        searches=[
            HistorySearchOut(id=s.id, query=s.query, category=s.category, searched_at=s.searched_at)
            for s in searches
        ],
    )


@router.delete("/me/history", status_code=204)
async def buyer_history_clear(request: Request, ctx: CurrentBuyer) -> Response:
    async with _db(request).transaction() as db:
        await db.execute(delete(BuyerView).where(BuyerView.buyer_id == ctx.buyer_id))
        await db.execute(delete(BuyerSearch).where(BuyerSearch.buyer_id == ctx.buyer_id))
    return Response(status_code=204)


@router.delete("/me/history/searches/{search_id}", status_code=204)
async def buyer_search_delete(search_id: UUID, request: Request, ctx: CurrentBuyer) -> Response:
    async with _db(request).transaction() as db:
        await db.execute(
            delete(BuyerSearch).where(BuyerSearch.buyer_id == ctx.buyer_id, BuyerSearch.id == search_id)
        )
    return Response(status_code=204)


@router.delete("/me/history/views/{canonical_id}", status_code=204)
async def buyer_view_delete(canonical_id: UUID, request: Request, ctx: CurrentBuyer) -> Response:
    async with _db(request).transaction() as db:
        await db.execute(
            delete(BuyerView).where(
                BuyerView.buyer_id == ctx.buyer_id, BuyerView.canonical_id == canonical_id
            )
        )
    return Response(status_code=204)


# ------------------------------------------------------------------ sevimlilar
class FavoriteOut(BaseModel):
    canonical_id: UUID
    title: str | None  # hozir ommaviy bo'lmasa — null
    brand: str | None
    saved_price_uzs_minor: int | None
    current_min_price_uzs_minor: int | None
    offers_count: int | None
    in_stock_count: int | None
    saved_at: datetime


class FavoritesOut(BaseModel):
    items: list[FavoriteOut]


@router.get("/me/favorites", response_model=FavoritesOut)
async def buyer_favorites(request: Request, ctx: CurrentBuyer) -> FavoritesOut:
    """Hozir ommaviy bo'lmagan mahsulot ham ro'yxatda qoladi, hozirgi maydonlari null (frontend: "hozir
    sotuvda yo'q")."""
    async with _db(request).transaction() as db:
        rows = (
            (
                await db.execute(
                    select(BuyerFavorite)
                    .where(BuyerFavorite.buyer_id == ctx.buyer_id)
                    .order_by(BuyerFavorite.saved_at.desc())
                    .limit(MAX_FAVORITES)
                )
            )
            .scalars()
            .all()
        )
        current = await _port.summaries(db, [f.canonical_id for f in rows])
    return FavoritesOut(
        items=[
            FavoriteOut(
                canonical_id=f.canonical_id,
                title=c.title if (c := current.get(f.canonical_id)) else None,
                brand=c.brand if c else None,
                saved_price_uzs_minor=f.saved_price_uzs_minor,
                current_min_price_uzs_minor=c.min_price_uzs_minor if c else None,
                offers_count=c.offers_count if c else None,
                in_stock_count=c.in_stock_count if c else None,
                saved_at=f.saved_at,
            )
            for f in rows
        ]
    )


@router.put("/me/favorites/{canonical_id}", status_code=204)
async def buyer_favorite_add(canonical_id: UUID, request: Request, ctx: CurrentBuyer) -> Response:
    """Idempotent. Birinchi saqlashda hozirgi eng past narx yoziladi; mahsulot ommaviy bo'lmasa — 404."""
    async with _db(request).transaction() as db:
        current = (await _port.summaries(db, [canonical_id])).get(canonical_id)
        if current is None:
            raise NotFoundError("Product not found")
        await db.execute(select(Buyer.id).where(Buyer.id == ctx.buyer_id).with_for_update())  # parallel PUT
        exists = await _svc(request).is_favorite(db, ctx.buyer_id, canonical_id)
        if not exists:
            total = await db.scalar(select(func.count()).where(BuyerFavorite.buyer_id == ctx.buyer_id))
            if int(total or 0) >= MAX_FAVORITES:
                raise ValidationError(
                    "Too many favorites",
                    fields=[
                        {"field": "canonical_id", "code": "limit_reached", "params": {"max": MAX_FAVORITES}}
                    ],
                )
            await db.execute(
                pg_insert(BuyerFavorite)
                .values(
                    buyer_id=ctx.buyer_id,
                    canonical_id=canonical_id,
                    saved_price_uzs_minor=current.min_price_uzs_minor,
                )
                .on_conflict_do_nothing()
            )
    return Response(status_code=204)


@router.delete("/me/favorites/{canonical_id}", status_code=204)
async def buyer_favorite_delete(canonical_id: UUID, request: Request, ctx: CurrentBuyer) -> Response:
    async with _db(request).transaction() as db:
        await db.execute(
            delete(BuyerFavorite).where(
                BuyerFavorite.buyer_id == ctx.buyer_id, BuyerFavorite.canonical_id == canonical_id
            )
        )
    return Response(status_code=204)


# ------------------------------------------------------------------ maslahatchi suhbati
class AdvisorMessageOut(BaseModel):
    id: UUID
    role: str
    text: str
    sources: list[Any]
    created_at: datetime


class AdvisorHistoryOut(BaseModel):
    items: list[AdvisorMessageOut]


@router.get("/me/advisor", response_model=AdvisorHistoryOut)
async def buyer_advisor(request: Request, ctx: CurrentBuyer) -> AdvisorHistoryOut:
    """Oxirgi 100 xabar, eskisi birinchi."""
    async with _db(request).transaction() as db:
        rows = (
            (
                await db.execute(
                    select(BuyerAdvisorMessage)
                    .where(BuyerAdvisorMessage.buyer_id == ctx.buyer_id)
                    .order_by(BuyerAdvisorMessage.created_at.desc(), BuyerAdvisorMessage.id.desc())
                    .limit(ADVISOR_SHOWN)
                )
            )
            .scalars()
            .all()
        )
    return AdvisorHistoryOut(
        items=[
            AdvisorMessageOut(id=m.id, role=m.role, text=m.text, sources=m.sources, created_at=m.created_at)
            for m in reversed(rows)
        ]
    )


@router.delete("/me/advisor", status_code=204)
async def buyer_advisor_clear(request: Request, ctx: CurrentBuyer) -> Response:
    async with _db(request).transaction() as db:
        await db.execute(delete(BuyerAdvisorMessage).where(BuyerAdvisorMessage.buyer_id == ctx.buyer_id))
    return Response(status_code=204)
