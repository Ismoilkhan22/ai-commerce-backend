"""Platforma: umumiy mahsulotga bog'lashni ko'rib chiqish (M23, BR-X08, TC-016).

Avtomatik faqat (brend + MPN); MPN yoki brendsiz SKU'lar — `PENDING_REVIEW`. Admin mavjud umumiy mahsulotni
tanlaydi, yangisini yaratadi yoki "bog'lanmaydi" deydi. Shoplararo o'qish faqat shu yerda va faqat
`platform.network.review` ruxsati bilan: RLS'da `app.network_review` varianti (network_0002).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import CanonicalProduct, PublicOffer, SkuLink
from app.domains.network.schemas import (
    CanonicalIn,
    CanonicalList,
    CanonicalOut,
    LinkDecisionIn,
    ReviewItem,
    ReviewList,
)
from app.domains.network.services.offers import LINK, OfferService, normalize_brand
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.db.session import set_shop_context
from app.shared.errors.base import NotFoundError, ValidationError
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext


def normalize_mpn(value: str | None) -> str | None:
    return normalize_brand(value)  # bir xil qoida: katta harf, belgisiz


async def _review_context(db: AsyncSession) -> None:
    await db.execute(text("SELECT set_config('app.network_review', 'on', true)"))


class ReviewService:
    def __init__(self, audit: AuditService, offers: OfferService) -> None:
        self.audit = audit
        self.offers = offers

    async def pending(self, db: AsyncSession, limit: int = 100) -> ReviewList:
        await _review_context(db)
        rows = await db.execute(
            select(SkuLink, PublicOffer.title, PublicOffer.brand, Shop.name)
            .join(
                PublicOffer, (PublicOffer.shop_id == SkuLink.shop_id) & (PublicOffer.sku_id == SkuLink.sku_id)
            )
            .join(Shop, Shop.id == SkuLink.shop_id)
            .where(SkuLink.status == "PENDING_REVIEW")
            .order_by(SkuLink.updated_at)
            .limit(limit)
        )
        return ReviewList(
            items=[
                ReviewItem(
                    shop_id=link.shop_id,
                    shop_name=shop_name,
                    sku_id=link.sku_id,
                    title=title,
                    brand=brand,
                    reason=link.reason,
                    updated_at=link.updated_at,
                )
                for link, title, brand, shop_name in rows
            ]
        )

    async def canonicals(self, db: AsyncSession, q: str | None, limit: int = 30) -> CanonicalList:
        query = select(CanonicalProduct).where(CanonicalProduct.status == "ACTIVE")
        if q and q.strip():
            pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(
                or_(
                    CanonicalProduct.title.ilike(pattern, escape="\\"),
                    CanonicalProduct.mpn_norm.startswith(normalize_mpn(q) or "\x00", autoescape=True),
                )
            )
        rows = await db.execute(query.order_by(CanonicalProduct.title).limit(limit))
        return CanonicalList(items=[CanonicalOut.model_validate(c) for c in rows.scalars()])

    async def decide(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, sku_id: UUID, data: LinkDecisionIn
    ) -> SkuLink:
        await _review_context(db)
        link = await db.get(SkuLink, (shop_id, sku_id), with_for_update=True)
        if link is None:
            raise NotFoundError("Link not found")
        canonical_id: UUID | None
        if data.unlink:
            canonical_id = None
        elif data.canonical_id is not None:
            canonical = await db.get(CanonicalProduct, data.canonical_id)
            if canonical is None or canonical.status != "ACTIVE":
                raise ValidationError(
                    "Canonical product not found",
                    fields=[{"field": "canonical_id", "code": "invalid", "params": {}}],
                )
            canonical_id = canonical.id
        elif data.create is not None:
            canonical_id = (await self._create(db, data.create)).id
        else:
            raise ValidationError(
                "Choose a decision", fields=[{"field": "canonical_id", "code": "required", "params": {}}]
            )
        link.canonical_id = canonical_id
        link.status = "LINKED" if canonical_id else "UNLINKED"
        link.method = "PLATFORM_REVIEW" if canonical_id else "NONE"
        link.reviewed_by, link.reviewed_at = actor.membership_id or actor.actor_id, utcnow()
        await db.flush()
        await set_shop_context(db, shop_id)
        offer = (
            await db.execute(
                select(PublicOffer)
                .where(PublicOffer.shop_id == shop_id, PublicOffer.sku_id == sku_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        on_shop = ActorContext(
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            shop_id=shop_id,
            surface=actor.surface,
            roles=actor.roles,
            membership_id=actor.membership_id,
        )
        if offer is not None and offer.canonical_id != canonical_id:
            offer.canonical_id = canonical_id
            offer.listing_version += 1
            await db.flush()
            await self.offers._emit(db, on_shop, offer, "network.public_offer.updated")
        await write_outbox(
            db,
            schema="network",
            event_type="network.canonical_match.changed",
            actor=on_shop,
            shop_id=shop_id,
            aggregate_type=LINK,
            aggregate_id=offer.id if offer is not None else sku_id,
            aggregate_version=link.version,
            payload={"sku_id": sku_id, "canonical_id": canonical_id, "status": link.status},
        )
        await self.audit.record(
            db,
            action="network.link.changed",
            entity_type=LINK,
            entity_id=sku_id,
            actor=on_shop,
            diff={"status": link.status, "canonical_id": str(canonical_id) if canonical_id else None},
        )
        return link

    async def _create(self, db: AsyncSession, data: CanonicalIn) -> CanonicalProduct:
        brand_norm, mpn_norm = normalize_brand(data.brand), normalize_mpn(data.mpn)
        if brand_norm and mpn_norm:
            existing = (
                await db.execute(
                    select(CanonicalProduct).where(
                        CanonicalProduct.brand_norm == brand_norm,
                        CanonicalProduct.mpn_norm == mpn_norm,
                        CanonicalProduct.status == "ACTIVE",
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
        canonical = CanonicalProduct(
            brand=data.brand,
            brand_norm=brand_norm,
            mpn_norm=mpn_norm,
            title=data.title.strip(),
            category_code=data.category_code,
            source="PLATFORM",
            version=1,
        )
        db.add(canonical)
        await db.flush()
        return canonical
