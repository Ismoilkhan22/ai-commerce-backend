"""M37: reklama o'rinlari va adolatli saralash (Stage 3) — BL-099, BL-104, BL-105.

```
Ega: "Reklama qilish" (ommaviy taklif, muddat, kalit so'zlar) ──▶ PENDING_REVIEW
Platforma: tasdiqlaydi ──▶ ACTIVE (muddat ichida) | rad etadi (sabab bilan) ──▶ REJECTED
Qidiruv ──▶ oddiy natijalar o'zgarmaydi; alohida `sponsored` ro'yxati (ko'pi 2 ta), har biri "Reklama"
AI maslahatchi ──▶ reklamani ko'rmaydi (uning tool'i faqat oddiy qidiruv)
```

Taklif yopilsa yoki shop to'xtatilsa reklama ham ko'rinmaydi (o'qishda tekshiriladi). Bosish soni yoziladi
(`?ad=` bilan "Do'konga o'tish"); ko'rsatishlar yozilmaydi (o'qish so'rovi yozmaydi).
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import ARRAY, Text, cast, or_, select, text, update
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import AdCampaign, PublicOffer
from app.domains.network.query_port import offer_view
from app.domains.network.services.trust import verified_shop_ids
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.contracts.network import MarketOffer
from app.shared.db.session import set_shop_context
from app.shared.errors.base import InvalidTransitionError, NotFoundError, ValidationError
from app.shared.types.actor import ActorContext

AD = "network.ad_campaign"
MAX_SPONSORED = 2
_TOKEN = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


class AdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_id: UUID
    starts_at: datetime
    ends_at: datetime
    keywords: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _period(self) -> AdIn:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AdOut(BaseModel):
    id: UUID
    shop_id: UUID
    sku_id: UUID
    title: str
    keywords: list[str]
    status: str
    starts_at: datetime
    ends_at: datetime
    clicks: int
    reject_reason: str | None


class AdList(BaseModel):
    items: list[AdOut]


class AdRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300)


class AdService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def create(self, db: AsyncSession, actor: ActorContext, data: AdIn) -> AdOut:
        assert actor.shop_id is not None
        offer = (
            await db.execute(
                select(PublicOffer).where(
                    PublicOffer.shop_id == actor.shop_id, PublicOffer.sku_id == data.sku_id
                )
            )
        ).scalar_one_or_none()
        if offer is None or offer.status != "ACTIVE":
            raise ValidationError(
                "Only public offers can be advertised",
                fields=[{"field": "sku_id", "code": "invalid", "params": {}}],
            )
        keywords = sorted({k.strip().lower()[:40] for k in data.keywords if k.strip()})
        ad = AdCampaign(
            shop_id=actor.shop_id,
            sku_id=data.sku_id,
            keywords=keywords,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            created_by=actor.membership_id,
        )
        db.add(ad)
        await db.flush()
        await db.refresh(ad)
        await self.audit.record(db, action="network.ad.created", entity_type=AD, entity_id=ad.id, actor=actor)
        return await self._out(db, ad)

    async def list_shop(self, db: AsyncSession, actor: ActorContext) -> AdList:
        rows = await db.execute(
            select(AdCampaign)
            .where(AdCampaign.shop_id == actor.shop_id)
            .order_by(AdCampaign.created_at.desc())
        )
        return AdList(items=[await self._out(db, a) for a in rows.scalars()])

    async def pause(self, db: AsyncSession, actor: ActorContext, ad_id: UUID) -> AdOut:
        ad = (
            await db.execute(
                select(AdCampaign)
                .where(AdCampaign.shop_id == actor.shop_id, AdCampaign.id == ad_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if ad is None:
            raise NotFoundError("Ad not found")
        if ad.status not in ("PENDING_REVIEW", "ACTIVE"):
            raise InvalidTransitionError("Ad is closed", entity=AD, **{"from": ad.status}, command="PAUSE")
        ad.status = "PAUSED"
        await db.flush()
        return await self._out(db, ad)

    # ------------------------------------------------------------------ platforma
    async def pending(self, db: AsyncSession) -> AdList:
        await db.execute(text("SELECT set_config('app.network_review', 'on', true)"))
        rows = await db.execute(
            select(AdCampaign).where(AdCampaign.status == "PENDING_REVIEW").order_by(AdCampaign.created_at)
        )
        return AdList(items=[await self._out(db, a) for a in rows.scalars()])

    async def review(
        self, db: AsyncSession, actor: ActorContext, ad_id: UUID, approve: bool, reason: str | None
    ) -> AdOut:
        await db.execute(text("SELECT set_config('app.network_review', 'on', true)"))
        ad = (
            await db.execute(select(AdCampaign).where(AdCampaign.id == ad_id).with_for_update())
        ).scalar_one_or_none()
        if ad is None:
            raise NotFoundError("Ad not found")
        if ad.status != "PENDING_REVIEW":
            raise InvalidTransitionError(
                "Ad is not pending", entity=AD, **{"from": ad.status}, command="REVIEW"
            )
        ad.status = "ACTIVE" if approve else "REJECTED"
        ad.reject_reason = None if approve else (reason or "").strip()
        ad.reviewed_by, ad.reviewed_at = actor.actor_id, utcnow()
        await db.flush()
        return await self._out(db, ad)

    # ------------------------------------------------------------------ qidiruvda
    async def sponsored(self, db: AsyncSession, q: str | None) -> list[tuple[UUID, MarketOffer]]:
        """Faol reklamalar (muddat ichida, taklifi ACTIVE): so'rov so'zi kalit so'zda yoki taklif nomida."""
        now = utcnow()
        tokens = [t.lower() for t in _TOKEN.findall(q or "") if len(t) >= 2][:6]
        if not tokens:
            return []
        await db.execute(text("SELECT set_config('app.network_public', 'on', true)"))
        rows = await db.execute(
            select(AdCampaign.id, PublicOffer, Shop)
            .join(
                PublicOffer,
                (PublicOffer.shop_id == AdCampaign.shop_id) & (PublicOffer.sku_id == AdCampaign.sku_id),
            )
            .join(Shop, Shop.id == AdCampaign.shop_id)
            .where(
                AdCampaign.status == "ACTIVE",
                AdCampaign.starts_at <= now,
                AdCampaign.ends_at > now,
                PublicOffer.status == "ACTIVE",
                Shop.status == "ACTIVE",
                or_(
                    *(PublicOffer.title.ilike(f"%{t}%") for t in tokens),
                    AdCampaign.keywords.op("&&")(cast(pg_array(tokens), ARRAY(Text))),
                ),
            )
            .order_by(AdCampaign.created_at)
            .limit(MAX_SPONSORED)
        )
        items = list(rows)
        verified = await verified_shop_ids(db, list({shop.id for _, _, shop in items}))
        return [(ad_id, offer_view(offer, shop, verified)) for ad_id, offer, shop in items]

    async def click(self, db: AsyncSession, ad_id: UUID, shop_id: UUID, sku_id: UUID) -> None:
        """Faqat shu reklama shu taklifniki bo'lsa sanaladi (begona `?ad=` bilan sun'iy bosish yo'q)."""
        await db.execute(text("SELECT set_config('app.network_public', 'on', true)"))
        ad = (await db.execute(select(AdCampaign).where(AdCampaign.id == ad_id))).scalar_one_or_none()
        if ad is None or ad.status != "ACTIVE" or ad.shop_id != shop_id or ad.sku_id != sku_id:
            return
        await set_shop_context(db, ad.shop_id)  # yozish — faqat shop konteksti bilan (RLS)
        await db.execute(
            update(AdCampaign).where(AdCampaign.id == ad_id).values(clicks=AdCampaign.clicks + 1)
        )

    async def _out(self, db: AsyncSession, ad: AdCampaign) -> AdOut:
        offer = (
            await db.execute(
                select(PublicOffer.title).where(
                    PublicOffer.shop_id == ad.shop_id, PublicOffer.sku_id == ad.sku_id
                )
            )
        ).scalar_one_or_none()
        return AdOut(
            id=ad.id,
            shop_id=ad.shop_id,
            sku_id=ad.sku_id,
            title=offer or "—",
            keywords=list(ad.keywords or ()),
            status=ad.status,
            starts_at=ad.starts_at,
            ends_at=ad.ends_at,
            clicks=ad.clicks,
            reject_reason=ad.reject_reason,
        )
