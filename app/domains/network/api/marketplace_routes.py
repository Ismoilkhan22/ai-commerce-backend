"""Xaridor uchun global qidiruv (Stage 3: M31, M32, M35) — `/api/v1/public/marketplace/*`, db/marketplace.md.

Faqat ommaviy ma'lumot (NetworkQueryPort). Yo'naltirish: taklif hozir ham ACTIVE ekani qayta tekshiriladi
(read-time deny), yozuvda xaridor shaxsi yo'q — faqat taklif, shop, vaqt va IP xeshi. Limit: IP bo'yicha
qidiruv 120/daq, yo'naltirish 30/daq.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import Referral
from app.domains.network.query_port import NetworkQueryPortImpl
from app.domains.network.services.trust import ReportIn
from app.shared.client_ip import client_ip
from app.shared.contracts.network import MarketOffer, MarketProduct, MarketResult
from app.shared.db.session import Database, set_shop_context
from app.shared.errors.base import NotFoundError
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(prefix="/marketplace", tags=["marketplace"])
_port = NetworkQueryPortImpl()


class MarketOfferView(BaseModel):
    offer_id: UUID
    shop_name: str
    shop_slug: str
    shop_verified: bool
    title: str
    price_uzs_minor: int | None
    condition: str | None
    warranty_months: int | None
    availability: str | None
    last_verified_at: str


class MarketResultView(BaseModel):
    canonical_id: UUID | None
    title: str
    brand: str | None
    category_code: str
    offers_count: int
    in_stock_count: int
    min_price_uzs_minor: int | None
    max_price_uzs_minor: int | None
    offer: MarketOfferView | None


class MarketSearchOut(BaseModel):
    items: list[MarketResultView]


class MarketProductOut(BaseModel):
    canonical_id: UUID
    title: str
    brand: str | None
    category_code: str
    offers: list[MarketOfferView]


class MarketVisitOut(BaseModel):
    url: str


def _offer(o: MarketOffer) -> MarketOfferView:
    return MarketOfferView(
        offer_id=o.offer_id,
        shop_name=o.shop_name,
        shop_slug=o.shop_slug,
        shop_verified=o.shop_verified,
        title=o.title,
        price_uzs_minor=o.price_uzs_minor,
        condition=o.condition,
        warranty_months=o.warranty_months,
        availability=o.availability,
        last_verified_at=o.last_verified_at.isoformat(),
    )


def _result(r: MarketResult) -> MarketResultView:
    return MarketResultView(
        canonical_id=r.canonical_id,
        title=r.title,
        brand=r.brand,
        category_code=r.category_code,
        offers_count=r.offers_count,
        in_stock_count=r.in_stock_count,
        min_price_uzs_minor=r.min_price_uzs_minor,
        max_price_uzs_minor=r.max_price_uzs_minor,
        offer=_offer(r.offer) if r.offer else None,
    )


def _product(p: MarketProduct) -> MarketProductOut:
    return MarketProductOut(
        canonical_id=p.canonical_id,
        title=p.title,
        brand=p.brand,
        category_code=p.category_code,
        offers=[_offer(o) for o in p.offers],
    )


async def read_db(request: Request) -> AsyncIterator[AsyncSession]:
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"market-read:{client_ip(request)}", limit=120)
    database: Database = request.app.state.db
    async with database.transaction(read_only=True) as db:
        yield db


ReadDb = Annotated[AsyncSession, Depends(read_db, scope="function")]


@router.get("/search", response_model=MarketSearchOut)
async def marketplace_search(
    db: ReadDb,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Z0-9_]+$")] = None,
    max_price_uzs_minor: Annotated[int | None, Query(ge=1, le=10**15)] = None,
    in_stock: bool = False,
    sort: Literal["relevance", "price_asc", "price_desc"] = "relevance",
    limit: Annotated[int, Query(ge=1, le=48)] = 24,
) -> MarketSearchOut:
    """Barcha shoplarning ommaviy takliflari. Bir xil mahsulot (umumiy mahsulot) — bitta natija, narx oralig'i
    va takliflar soni bilan. "Eng arzon" yorlig'i yo'q (yetkazish narxi noma'lum, BL-092)."""
    results = await _port.search(
        db,
        q=q,
        category=category,
        max_price_uzs_minor=max_price_uzs_minor,
        in_stock=in_stock,
        sort=sort,
        limit=limit,
    )
    return MarketSearchOut(items=[_result(r) for r in results])


@router.get("/products/{canonical_id}", response_model=MarketProductOut)
async def marketplace_product(canonical_id: UUID, db: ReadDb) -> MarketProductOut:
    """Narx solishtirish: shu mahsulotning hamma ommaviy takliflari narx bo'yicha (M32)."""
    product = await _port.product(db, canonical_id)
    if product is None:
        raise NotFoundError("Product not found")
    return _product(product)


@router.post("/offers/{offer_id}/visit", response_model=MarketVisitOut)
async def marketplace_visit(offer_id: UUID, request: Request) -> MarketVisitOut:
    """ "Do'konga o'tish" (M35): taklif hozir ham ACTIVE bo'lsa — yozuv va shop saytidagi mahsulot manzili;
    qaytarib olingan bo'lsa — 404."""
    ip = client_ip(request)
    await enforce(request.app.state.rate_limiter, f"market-visit:{ip}", limit=30)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        target = await _port.visit_target(db, offer_id)
        if target is None:
            raise NotFoundError("Offer is no longer available")
        await set_shop_context(db, target.shop_id)  # yozuv shop jadvalida (RLS)
        db.add(
            Referral(
                shop_id=target.shop_id,
                offer_id=target.offer_id,
                ip_hash=hashlib.sha256(ip.encode()).hexdigest()[:32],
            )
        )
    template: str = request.app.state.storefront_public_url
    base = template.replace("{slug}", target.shop_slug).rstrip("/")
    return MarketVisitOut(url=f"{base}/p/{target.product_id}" if target.product_id else base)


@router.post("/offers/{offer_id}/report", status_code=202)
async def marketplace_report(offer_id: UUID, body: ReportIn, request: Request) -> None:
    """Xaridor shikoyati (M29, BL-088): noto'g'ri narx, mavjud emas, soxta mahsulot, firibgarlik. Shaxsiz."""
    ip = client_ip(request)
    await enforce(request.app.state.rate_limiter, f"market-report:{ip}", limit=5, window_seconds=3600)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        target = await _port.visit_target(db, offer_id)
        if target is None:
            raise NotFoundError("Offer is no longer available")
        await request.app.state.network.trust.report(
            db, target.offer_id, target.shop_id, body, hashlib.sha256(ip.encode()).hexdigest()[:32]
        )
