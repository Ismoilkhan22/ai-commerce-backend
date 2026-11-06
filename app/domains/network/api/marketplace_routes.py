"""Xaridor uchun global qidiruv (Stage 3: M31, M32, M35) — `/api/v1/public/marketplace/*`, db/marketplace.md.

Faqat ommaviy ma'lumot (NetworkQueryPort). Yo'naltirish: taklif hozir ham ACTIVE ekani qayta tekshiriladi
(read-time deny), yozuvda xaridor shaxsi yo'q — faqat taklif, shop, vaqt va IP xeshi. Limit: IP bo'yicha
qidiruv 120/daq, yo'naltirish 30/daq.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.api.buyer_routes import OptionalBuyer
from app.domains.network.models.orm import Referral
from app.domains.network.query_port import NetworkQueryPortImpl
from app.domains.network.services.ads import AdService
from app.domains.network.services.advisor import AdvisorIn, AdvisorOut, AdvisorService
from app.domains.network.services.buyers import BuyerService
from app.domains.network.services.trust import ReportIn
from app.shared.client_ip import client_ip
from app.shared.contracts.network import MarketOffer, MarketProduct, MarketResult
from app.shared.db.session import Database, set_shop_context
from app.shared.errors.base import NotFoundError
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(prefix="/marketplace", tags=["marketplace"])
_port = NetworkQueryPortImpl()


class MarketBranchView(BaseModel):
    name: str
    address: str
    lat: float | None
    lon: float | None
    availability: str | None
    distance_km: float | None  # to'g'ri chiziq bo'yicha (BL-096), xaridor joyini bergan bo'lsa


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
    branches: list[MarketBranchView] = []


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


class SponsoredView(BaseModel):
    ad_id: UUID
    label: Literal["Reklama"] = "Reklama"  # BL-104: aniq belgilanadi
    offer: MarketOfferView


class MarketSearchOut(BaseModel):
    items: list[MarketResultView]  # oddiy natijalar — reklamadan mustaqil (BL-099)
    sponsored: list[SponsoredView] = []


class MarketProductOut(BaseModel):
    canonical_id: UUID
    title: str
    brand: str | None
    category_code: str
    offers: list[MarketOfferView]
    is_favorite: bool | None = None  # null — xaridor kirmagan


class MarketVisitOut(BaseModel):
    url: str


def _distance(lat: float | None, lon: float | None, here: tuple[float, float] | None) -> float | None:
    """Haversine, km, 0.1 gacha — "to'g'ri chiziq bo'yicha" (yo'l masofasi emas, BL-096)."""
    if here is None or lat is None or lon is None:
        return None
    p1, p2 = math.radians(here[0]), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - here[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(a)), 1)


def _branches(o: MarketOffer, here: tuple[float, float] | None) -> list[MarketBranchView]:
    items = [
        MarketBranchView(
            name=str(b.get("name") or ""),
            address=str(b.get("address") or ""),
            lat=b.get("lat") if isinstance(b.get("lat"), int | float) else None,
            lon=b.get("lon") if isinstance(b.get("lon"), int | float) else None,
            availability=str(b["availability"]) if b.get("availability") else None,
            distance_km=None,
        )
        for b in o.branches
    ]
    for item in items:
        item.distance_km = _distance(item.lat, item.lon, here)
    return sorted(items, key=lambda b: (b.distance_km is None, b.distance_km or 0))


def _offer(o: MarketOffer, here: tuple[float, float] | None = None) -> MarketOfferView:
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
        branches=_branches(o, here),
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


def _product(p: MarketProduct, here: tuple[float, float] | None = None) -> MarketProductOut:
    return MarketProductOut(
        canonical_id=p.canonical_id,
        title=p.title,
        brand=p.brand,
        category_code=p.category_code,
        offers=[_offer(o, here) for o in p.offers],
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
    request: Request,
    db: ReadDb,
    buyer: OptionalBuyer,
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
    ads: AdService = request.app.state.network.ads
    sponsored = await ads.sponsored(db, q)
    if buyer is not None and q and q.strip():  # kirgan xaridor tarixi: alohida qisqa yozuv tranzaksiyasi
        buyers: BuyerService = request.app.state.network.buyers
        await buyers.record_search(request.app.state.db, buyer.buyer_id, q.strip(), category)
    return MarketSearchOut(
        items=[_result(r) for r in results],
        sponsored=[SponsoredView(ad_id=ad_id, offer=_offer(offer)) for ad_id, offer in sponsored],
    )


@router.get("/products/{canonical_id}", response_model=MarketProductOut)
async def marketplace_product(
    canonical_id: UUID,
    request: Request,
    db: ReadDb,
    buyer: OptionalBuyer,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> MarketProductOut:
    """Narx solishtirish (M32): hamma ommaviy takliflar narx bo'yicha. `lat`/`lon` — xaridor o'zi ruxsat
    bersa (M33, BL-095): filiallargacha to'g'ri chiziq masofasi; saqlanmaydi va logga yozilmaydi."""
    product = await _port.product(db, canonical_id)
    if product is None:
        raise NotFoundError("Product not found")
    here = (lat, lon) if lat is not None and lon is not None else None
    out = _product(product, here)
    if buyer is not None:
        buyers: BuyerService = request.app.state.network.buyers
        out.is_favorite = await buyers.is_favorite(db, buyer.buyer_id, canonical_id)
        await buyers.record_view(request.app.state.db, buyer.buyer_id, canonical_id)
    return out


@router.post("/offers/{offer_id}/visit", response_model=MarketVisitOut)
async def marketplace_visit(
    offer_id: UUID, request: Request, ad: Annotated[UUID | None, Query()] = None
) -> MarketVisitOut:
    """ "Do'konga o'tish" (M35): taklif hozir ham ACTIVE bo'lsa — yozuv va shop saytidagi mahsulot manzili;
    qaytarib olingan bo'lsa — 404."""
    ip = client_ip(request)
    await enforce(request.app.state.rate_limiter, f"market-visit:{ip}", limit=30)
    database: Database = request.app.state.db
    async with database.transaction() as db:
        target = await _port.visit_target(db, offer_id)
        if target is None:
            raise NotFoundError("Offer is no longer available")
        if ad is not None:  # M37: reklama bosilishi
            if target.sku_id is not None:
                await request.app.state.network.ads.click(db, ad, target.shop_id, target.sku_id)
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


# ------------------------------------------------------------------ M34: global AI maslahatchi, M38: sitemap
@router.post("/advisor", response_model=AdvisorOut)
async def marketplace_advisor(body: AdvisorIn, request: Request, buyer: OptionalBuyer) -> AdvisorOut:
    """Faqat ommaviy takliflar asosida maslahat (BL-097, BL-098); javob bilan manbalar ro'yxati. Tarix
    saqlanmaydi (kirgan xaridorniki bundan mustasno: xabar va javob tarixiga yoziladi). Limit: IP bo'yicha
    10/daq va 60/kun."""
    ip = client_ip(request)
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"market-ai:{ip}", limit=10)
    await enforce(limiter, f"market-ai-day:{ip}", limit=60, window_seconds=86400)
    advisor: AdvisorService = request.app.state.network.advisor
    out = await advisor.ask(request.app.state.db, body)
    if buyer is not None:
        buyers: BuyerService = request.app.state.network.buyers
        await buyers.record_advisor(
            request.app.state.db,
            buyer.buyer_id,
            body.message,
            out.answer,
            [src.model_dump(mode="json") for src in out.sources],
        )
    return out


class SitemapItem(BaseModel):
    canonical_id: UUID
    updated_at: str


class MarketSitemapOut(BaseModel):
    items: list[SitemapItem]


@router.get("/sitemap", response_model=MarketSitemapOut)
async def marketplace_sitemap(db: ReadDb) -> MarketSitemapOut:
    """SEO (M38, BL-106/107): faqat hozir ommaviy taklifi bor umumiy mahsulotlar — bitta asosiy manzil."""
    rows = await _port.sitemap(db)
    return MarketSitemapOut(items=[SitemapItem(canonical_id=c, updated_at=u.isoformat()) for c, u in rows])
