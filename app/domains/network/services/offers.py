"""Ommaviy takliflar va umumiy mahsulotga bog'lash (Stage 2: M23, M24) — db/network.md.

- Standartda hammasi yopiq (BL-079): taklif faqat ega bosganda va faqat ACTIVE (tekshirilgan) shopda.
- Proyeksiya faqat Query Port'lardan (`CatalogQueryPort.network_facts`, `StockQueryPort.availability`);
  `catalog`/`commerce` jadvallariga JOIN yo'q (TC-NET-04). Tannarx, xaridor, aniq qoldiq — yo'q (BL-081).
- Qaytarib olish darhol (BL-080): bitta tranzaksiyada `WITHDRAWN` + outbox.
- Har o'zgarishda `listing_version` +1 (BL-085); event `network.public_offer.published|updated|withdrawn`.
- Avtomatik bog'lash faqat aniq (brend + MPN); qolgani — `PENDING_REVIEW`, platforma admini (BR-X08, TC-016).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import CanonicalProduct, PublicOffer, SkuLink
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Branch, Shop
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort, NetworkSkuFacts
from app.shared.contracts.commerce import StockQueryPort
from app.shared.errors.base import NotFoundError, ShopNotVerifiedError, ValidationError
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

OFFER = "network.public_offer"
_NOT_ALNUM = re.compile(r"[\W_]+", re.UNICODE)
LINK = "network.sku_link"
DEFAULT_FIELDS = ["availability", "condition", "price", "warranty"]  # filial (M33) — faqat ega yoqsa
SYSTEM_REASONS = ("NO_PRICE", "NOT_SELLABLE", "SHOP_SUSPENDED")  # tuzalsa taklif o'zi qaytadi


def normalize_brand(value: str | None) -> str | None:
    """`catalog` bilan bir xil qoida ("MSI" = "msi" = "M.S.I."), lekin import'siz (TC-NET-04)."""
    normalized = _NOT_ALNUM.sub("", (value or "").upper())
    return normalized or None


def _projection(facts: NetworkSkuFacts, availability: str | None) -> dict[str, Any]:
    return {
        "product_id": facts.product_id,
        "title": facts.title,
        "brand": facts.brand,
        "category_code": facts.category_code,
        "price_minor": facts.amount_minor,
        "currency": facts.currency,
        "price_uzs_minor": facts.uzs_amount_minor,
        "condition": facts.condition,
        "warranty_months": facts.warranty_months,
        "availability": availability,
    }


def _problem(facts: NetworkSkuFacts | None) -> str | None:
    if facts is None or not facts.sellable:
        return "NOT_SELLABLE"
    if facts.uzs_amount_minor is None:
        return "NO_PRICE"  # narx yo'q yoki dollar narxi kursi yo'q (BL-012)
    return None


class OfferService:
    def __init__(self, audit: AuditService, catalog: CatalogQueryPort, stock: StockQueryPort) -> None:
        self.audit = audit
        self.catalog = catalog
        self.stock = stock

    # ------------------------------------------------------------------ ega
    async def publish(
        self, db: AsyncSession, actor: ActorContext, sku_ids: Sequence[UUID], fields: Sequence[str] | None
    ) -> list[PublicOffer]:
        assert actor.shop_id is not None
        shop = await db.get(Shop, actor.shop_id)
        if shop is None or shop.status != "ACTIVE":
            raise ShopNotVerifiedError("Only verified (ACTIVE) shops can publish offers")
        permitted = sorted(set(fields)) if fields else DEFAULT_FIELDS
        facts = await self.catalog.network_facts(db, actor.shop_id, sku_ids)
        bad = [
            {"sku_id": str(s), "reason": _problem(facts.get(s))} for s in sku_ids if _problem(facts.get(s))
        ]
        if bad:
            raise ValidationError(
                "Some SKUs cannot be published",
                fields=[{"field": "sku_ids", "code": "not_publishable", "params": {"items": bad}}],
            )
        blocked = [
            o.sku_id
            for o in (await self.offers_for(db, actor.shop_id, sku_ids)).values()
            if o.withdraw_reason == "PLATFORM_REPORT"
        ]
        if blocked:  # platforma shikoyat bo'yicha yashirgan — ega o'zi qaytara olmaydi (BL-088)
            raise ValidationError(
                "Some offers were suspended by the platform",
                fields=[
                    {
                        "field": "sku_ids",
                        "code": "platform_suspended",
                        "params": {"items": [str(b) for b in blocked]},
                    }
                ],
            )
        availability = await self.stock.availability(db, actor.shop_id, sku_ids)
        out: list[PublicOffer] = []
        for sku_id in sku_ids:
            fact = facts[sku_id]
            link = await self._link(db, actor.shop_id, fact)
            offer = await self._offer(db, actor.shop_id, sku_id)
            avail = availability.get(sku_id)
            values = _projection(fact, avail.status if avail else "OUT_OF_STOCK")
            values["branches"] = (
                await self._branches(db, actor.shop_id, avail) if "branch" in permitted else None
            )
            if offer is None:
                offer = PublicOffer(
                    shop_id=actor.shop_id,
                    sku_id=sku_id,
                    canonical_id=link.canonical_id,
                    permitted_fields=permitted,
                    published_by=actor.membership_id,
                    listing_version=1,
                    **values,
                )
                db.add(offer)
                await db.flush()
            else:
                offer.status, offer.withdraw_reason, offer.withdrawn_at = "ACTIVE", None, None
                offer.permitted_fields, offer.canonical_id = permitted, link.canonical_id
                for key, value in values.items():
                    setattr(offer, key, value)
                offer.listing_version += 1
                offer.published_at = offer.last_verified_at = utcnow()
                await db.flush()
            await self._emit(db, actor, offer, "network.public_offer.published")
            out.append(offer)
        await self.audit.record(
            db,
            action="network.offers.published",
            entity_type=OFFER,
            entity_id=actor.shop_id,
            actor=actor,
            diff={"count": len(out)},
        )
        return out

    async def withdraw(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> PublicOffer:
        assert actor.shop_id is not None
        offer = await self._offer(db, actor.shop_id, sku_id, lock=True)
        if offer is None:
            raise NotFoundError("Offer not found")
        if offer.withdraw_reason == "PLATFORM_REPORT":
            return offer  # platforma yashirgan — ega sababni almashtira olmaydi (QA #1, BL-088)
        if offer.status != "WITHDRAWN" or offer.withdraw_reason != "OWNER":
            offer.status, offer.withdraw_reason, offer.withdrawn_at = "WITHDRAWN", "OWNER", utcnow()
            offer.listing_version += 1
            await db.flush()
            await self._emit(db, actor, offer, "network.public_offer.withdrawn")
            await self.audit.record(
                db, action="network.offer.withdrawn", entity_type=OFFER, entity_id=offer.id, actor=actor
            )
        return offer

    async def offers_for(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, PublicOffer]:
        if not sku_ids:
            return {}
        rows = await db.execute(
            select(PublicOffer).where(PublicOffer.shop_id == shop_id, PublicOffer.sku_id.in_(list(sku_ids)))
        )
        return {o.sku_id: o for o in rows.scalars()}

    async def links_for(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuLink]:
        if not sku_ids:
            return {}
        rows = await db.execute(
            select(SkuLink).where(SkuLink.shop_id == shop_id, SkuLink.sku_id.in_(list(sku_ids)))
        )
        return {link.sku_id: link for link in rows.scalars()}

    # ------------------------------------------------------------------ event'lardan
    async def refresh(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> int:
        """Narx, mahsulot holati yoki qoldiq o'zgardi — faqat ommaviy SKU'lar proyeksiyasi yangilanadi.
        Ega yopgan taklif (`OWNER`) qaytarilmaydi; tizim sababi tuzalsa — yana `ACTIVE`."""
        rows = (
            await db.execute(
                select(PublicOffer)
                .where(PublicOffer.shop_id == shop_id, PublicOffer.sku_id.in_(list(sku_ids)))
                .with_for_update()
            )
        ).scalars()
        offers = [o for o in rows if o.status == "ACTIVE" or o.withdraw_reason in SYSTEM_REASONS]
        if not offers:
            return 0
        ids = [o.sku_id for o in offers]
        facts = await self.catalog.network_facts(db, shop_id, ids)
        availability = await self.stock.availability(db, shop_id, ids)
        shop = await db.get(Shop, shop_id)
        changed = 0
        for offer in offers:
            fact = facts.get(offer.sku_id)
            problem = "SHOP_SUSPENDED" if shop is None or shop.status != "ACTIVE" else _problem(fact)
            if problem is not None:
                if offer.status == "ACTIVE" or offer.withdraw_reason != problem:
                    offer.status, offer.withdraw_reason, offer.withdrawn_at = "SUSPENDED", problem, utcnow()
                    offer.listing_version += 1
                    await db.flush()
                    await self._emit(db, actor, offer, "network.public_offer.withdrawn")
                    changed += 1
                continue
            assert fact is not None
            avail = availability.get(offer.sku_id)
            values = _projection(fact, avail.status if avail else "OUT_OF_STOCK")
            values["branches"] = (
                await self._branches(db, shop_id, avail)
                if "branch" in (offer.permitted_fields or ())
                else None
            )
            diff = {k: v for k, v in values.items() if getattr(offer, k) != v}
            revived = offer.status != "ACTIVE"
            if diff or revived:
                for key, value in diff.items():
                    setattr(offer, key, value)
                if revived:
                    offer.status, offer.withdraw_reason, offer.withdrawn_at = "ACTIVE", None, None
                offer.listing_version += 1
                await db.flush()
                await self._emit(db, actor, offer, "network.public_offer.updated")
                changed += 1
            offer.last_verified_at = utcnow()
        return changed

    async def suspend_shop(self, db: AsyncSession, actor: ActorContext, shop_id: UUID) -> int:
        rows = (
            await db.execute(
                select(PublicOffer)
                .where(PublicOffer.shop_id == shop_id, PublicOffer.status == "ACTIVE")
                .with_for_update()
            )
        ).scalars()
        count = 0
        for offer in rows:
            offer.status, offer.withdraw_reason, offer.withdrawn_at = "SUSPENDED", "SHOP_SUSPENDED", utcnow()
            offer.listing_version += 1
            await db.flush()
            await self._emit(db, actor, offer, "network.public_offer.withdrawn")
            count += 1
        return count

    async def revive_shop(self, db: AsyncSession, actor: ActorContext, shop_id: UUID) -> int:
        rows = await db.execute(
            select(PublicOffer.sku_id).where(
                PublicOffer.shop_id == shop_id, PublicOffer.withdraw_reason == "SHOP_SUSPENDED"
            )
        )
        return await self.refresh(db, actor, shop_id, list(rows.scalars()))

    # ------------------------------------------------------------------ yordamchilar
    @staticmethod
    async def _branches(db: AsyncSession, shop_id: UUID, avail: Any) -> list[dict[str, Any]]:
        """M33: ochiq olib ketish filiallari koordinatasi bilan — faqat ega `branch` maydonini yoqqanda."""
        statuses = {b.branch_id: b.status for b in (avail.pickup_branches if avail else ())}
        rows = await db.execute(
            select(Branch).where(
                Branch.shop_id == shop_id,
                Branch.status == "ACTIVE",
                Branch.is_pickup_point.is_(True),
                Branch.latitude.is_not(None),
                Branch.longitude.is_not(None),
            )
        )
        return [
            {
                "name": b.name,
                "address": b.address,
                "lat": float(b.latitude) if b.latitude is not None else None,
                "lon": float(b.longitude) if b.longitude is not None else None,
                "availability": statuses.get(b.id, "OUT_OF_STOCK"),
            }
            for b in rows.scalars()
        ]

    async def _link(self, db: AsyncSession, shop_id: UUID, fact: NetworkSkuFacts) -> SkuLink:
        link = await db.get(SkuLink, (shop_id, fact.sku_id), with_for_update=True)
        if link is not None and (link.reviewed_at is not None or link.status == "LINKED"):
            return link  # admin qarori yoki avvalgi aniq bog'lanish o'zgarmaydi
        brand = normalize_brand(fact.brand)
        canonical_id: UUID | None = None
        reason: str | None = None
        if not brand:
            reason = "NO_BRAND"
        elif not fact.mpn_norm:
            reason = "NO_MPN"
        else:
            canonical = (
                await db.execute(
                    select(CanonicalProduct).where(
                        CanonicalProduct.brand_norm == brand,
                        CanonicalProduct.mpn_norm == fact.mpn_norm,
                        CanonicalProduct.status == "ACTIVE",
                    )
                )
            ).scalar_one_or_none()
            if canonical is None:
                canonical = await self._create_canonical(db, fact, brand)
            canonical_id = canonical.id
        if link is None:
            link = SkuLink(shop_id=shop_id, sku_id=fact.sku_id, status="UNLINKED", version=1)
            db.add(link)
        link.canonical_id = canonical_id
        link.status = "LINKED" if canonical_id else "PENDING_REVIEW"
        link.method = "EXACT_MPN" if canonical_id else "NONE"
        link.reason = reason
        await db.flush()
        return link

    @staticmethod
    async def _create_canonical(db: AsyncSession, fact: NetworkSkuFacts, brand: str) -> CanonicalProduct:
        """Ikki shop bir vaqtda bir xil (brend, MPN) chiqarsa — noyoblik buzilmaydi: savepoint, keyin qayta
        o'qiladi (QA #11)."""
        try:
            async with db.begin_nested():
                canonical = CanonicalProduct(
                    brand=fact.brand,
                    brand_norm=brand,
                    mpn_norm=fact.mpn_norm,
                    title=fact.title,
                    category_code=fact.category_code,
                    source="AUTO_MPN",
                    version=1,
                )
                db.add(canonical)
                await db.flush()
                return canonical
        except IntegrityError:
            existing = (
                await db.execute(
                    select(CanonicalProduct).where(
                        CanonicalProduct.brand_norm == brand,
                        CanonicalProduct.mpn_norm == fact.mpn_norm,
                        CanonicalProduct.status == "ACTIVE",
                    )
                )
            ).scalar_one()
            return existing

    @staticmethod
    async def _offer(
        db: AsyncSession, shop_id: UUID, sku_id: UUID, *, lock: bool = False
    ) -> PublicOffer | None:
        query = select(PublicOffer).where(PublicOffer.shop_id == shop_id, PublicOffer.sku_id == sku_id)
        return (await db.execute(query.with_for_update() if lock else query)).scalar_one_or_none()

    @staticmethod
    async def _emit(db: AsyncSession, actor: ActorContext, offer: PublicOffer, event_type: str) -> None:
        await write_outbox(
            db,
            schema="network",
            event_type=event_type,
            actor=actor,
            shop_id=offer.shop_id,
            aggregate_type=OFFER,
            aggregate_id=offer.id,
            aggregate_version=offer.listing_version,
            payload={
                "offer_id": offer.id,
                "sku_id": offer.sku_id,
                "canonical_id": offer.canonical_id,
                "listing_version": offer.listing_version,
                "status": offer.status,
            },
        )
