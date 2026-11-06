"""NetworkQueryPort amalga oshirilishi (Stage 3 o'qiydi) — db/marketplace.md.

O'qish `app.network_public = 'on'` bilan: RLS faqat ACTIVE takliflarni beradi; qo'shimcha ravishda shop ham
ACTIVE bo'lishi tekshiriladi. `permitted_fields` da yo'q maydon (masalan narx) javobda `None`.
Qidiruv: so'rovdagi har so'z nom, brend yoki MPN'da bo'lishi kerak; natija umumiy mahsulot bo'yicha
guruhlanadi.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, any_, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import CanonicalProduct, PublicOffer
from app.domains.network.services.trust import verified_shop_ids
from app.platform.shops.models.orm import Shop
from app.shared.contracts.network import MarketOffer, MarketProduct, MarketResult, MarketSort, VisitTarget

MAX_SCAN = 500  # bitta qidiruvda ko'rib chiqiladigan takliflar (keyin alohida indeks — engineering/28 §9)
_TOKEN = re.compile(r"[0-9a-zа-яёʻ'`]+", re.IGNORECASE)


async def _public(db: AsyncSession) -> None:
    await db.execute(text("SELECT set_config('app.network_public', 'on', true)"))


def _escape(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def offer_view(offer: PublicOffer, shop: Shop, verified: set[UUID]) -> MarketOffer:
    fields = set(offer.permitted_fields or ())
    return MarketOffer(
        offer_id=offer.id,
        shop_id=offer.shop_id,
        shop_name=shop.name,
        shop_slug=shop.slug,
        shop_verified=offer.shop_id in verified,
        canonical_id=offer.canonical_id,
        title=offer.title,
        brand=offer.brand,
        category_code=offer.category_code,
        price_uzs_minor=offer.price_uzs_minor if "price" in fields else None,
        condition=offer.condition if "condition" in fields else None,
        warranty_months=offer.warranty_months if "warranty" in fields else None,
        availability=offer.availability if "availability" in fields else None,
        last_verified_at=offer.last_verified_at,
        branches=tuple(offer.branches or ()) if "branch" in fields else (),
    )


def _price_key(offer: MarketOffer) -> tuple[int, int]:
    return (0, offer.price_uzs_minor) if offer.price_uzs_minor is not None else (1, 0)


class NetworkQueryPortImpl:
    async def _rows(
        self, db: AsyncSession, *conditions: ColumnElement[bool]
    ) -> list[tuple[PublicOffer, Shop]]:
        await _public(db)
        rows = await db.execute(
            select(PublicOffer, Shop)
            .join(Shop, Shop.id == PublicOffer.shop_id)
            .where(PublicOffer.status == "ACTIVE", Shop.status == "ACTIVE", *conditions)
            .order_by(PublicOffer.last_verified_at.desc(), PublicOffer.id)
            .limit(MAX_SCAN)
        )
        return [(offer, shop) for offer, shop in rows]

    async def search(
        self,
        db: AsyncSession,
        *,
        q: str | None,
        category: str | None,
        max_price_uzs_minor: int | None,
        in_stock: bool,
        sort: MarketSort,
        limit: int,
    ) -> list[MarketResult]:
        conditions: list[ColumnElement[bool]] = []
        tokens = [t.lower() for t in _TOKEN.findall(q or "") if len(t) >= 2][:8]
        for token in tokens:
            pattern = f"%{_escape(token)}%"
            conditions.append(
                or_(
                    PublicOffer.title.ilike(pattern, escape="\\"),
                    PublicOffer.brand.ilike(pattern, escape="\\"),
                    PublicOffer.canonical_id.in_(
                        select(CanonicalProduct.id).where(
                            or_(
                                CanonicalProduct.mpn_norm.ilike(pattern.upper(), escape="\\"),
                                CanonicalProduct.title.ilike(pattern, escape="\\"),
                            )
                        )
                    ),
                )
            )
        if category:
            conditions.append(PublicOffer.category_code == category)
        if max_price_uzs_minor is not None:
            conditions.append(
                and_(
                    PublicOffer.price_uzs_minor <= max_price_uzs_minor,
                    literal("price") == any_(PublicOffer.permitted_fields),
                )
            )
        if in_stock:
            conditions.append(PublicOffer.availability.in_(("IN_STOCK", "LOW_STOCK")))
        rows = await self._rows(db, *conditions)
        verified = await verified_shop_ids(db, list({o.shop_id for o, _ in rows}))
        groups: dict[UUID, list[MarketOffer]] = {}
        order: list[UUID] = []
        for offer, shop in rows:
            key = offer.canonical_id or offer.id
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(offer_view(offer, shop, verified))
        canonicals = await self._canonicals(db, [k for k in order if groups[k][0].canonical_id is not None])
        results: list[MarketResult] = []
        for key in order:
            offers = sorted(groups[key], key=_price_key)
            first = offers[0]
            canonical = canonicals.get(key) if first.canonical_id is not None else None
            prices = [o.price_uzs_minor for o in offers if o.price_uzs_minor is not None]
            results.append(
                MarketResult(
                    canonical_id=first.canonical_id,
                    title=canonical.title if canonical else first.title,
                    brand=(canonical.brand if canonical else None) or first.brand,
                    category_code=canonical.category_code if canonical else first.category_code,
                    offers_count=len(offers),
                    in_stock_count=sum(1 for o in offers if o.availability in ("IN_STOCK", "LOW_STOCK")),
                    min_price_uzs_minor=min(prices) if prices else None,
                    max_price_uzs_minor=max(prices) if prices else None,
                    offer=first,
                )
            )
        if sort != "relevance":
            priced = [r for r in results if r.min_price_uzs_minor is not None]
            unpriced = [r for r in results if r.min_price_uzs_minor is None]
            priced.sort(key=lambda r: r.min_price_uzs_minor or 0, reverse=sort == "price_desc")
            results = priced + unpriced
        else:
            # Ko'p shopda bor va omborda bor mahsulot yuqorida (oshkor mezonlar, BL-105)
            results.sort(key=lambda r: (-min(r.offers_count, 5), -min(r.in_stock_count, 1)))
        return results[:limit]

    async def product(self, db: AsyncSession, canonical_id: UUID) -> MarketProduct | None:
        canonical = await db.get(CanonicalProduct, canonical_id)
        if canonical is None or canonical.status != "ACTIVE":
            return None
        rows = await self._rows(db, PublicOffer.canonical_id == canonical_id)
        verified = await verified_shop_ids(db, list({o.shop_id for o, _ in rows}))
        return MarketProduct(
            canonical_id=canonical.id,
            title=canonical.title,
            brand=canonical.brand,
            category_code=canonical.category_code,
            offers=tuple(sorted((offer_view(o, s, verified) for o, s in rows), key=_price_key)),
        )

    async def visit_target(self, db: AsyncSession, offer_id: UUID) -> VisitTarget | None:
        rows = await self._rows(db, PublicOffer.id == offer_id)
        if not rows:
            return None
        offer, shop = rows[0]
        return VisitTarget(
            offer_id=offer.id,
            shop_id=offer.shop_id,
            shop_slug=shop.slug,
            product_id=offer.product_id,
            sku_id=offer.sku_id,
        )

    async def sitemap(self, db: AsyncSession, limit: int = 50_000) -> list[tuple[UUID, datetime]]:
        await _public(db)
        rows = await db.execute(
            select(PublicOffer.canonical_id, func.max(PublicOffer.updated_at))
            .join(Shop, Shop.id == PublicOffer.shop_id)
            .where(
                PublicOffer.status == "ACTIVE", Shop.status == "ACTIVE", PublicOffer.canonical_id.is_not(None)
            )
            .group_by(PublicOffer.canonical_id)
            .order_by(func.max(PublicOffer.updated_at).desc())
            .limit(limit)
        )
        return [(c, u) for c, u in rows if c is not None]

    @staticmethod
    async def _canonicals(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, CanonicalProduct]:
        if not ids:
            return {}
        rows = await db.execute(select(CanonicalProduct).where(CanonicalProduct.id.in_(list(ids))))
        return {c.id: c for c in rows.scalars()}
