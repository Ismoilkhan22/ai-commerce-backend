"""M29: "Tasdiqlangan do'kon" belgisi va xaridor shikoyatlari (BL-087, BL-088) — Stage 2/3.

- Belgi faqat platforma admini beradi: dalil matni majburiy (nima tekshirildi), muddat 1…24 oy. Muddati o'tsa
  belgi o'zi ko'rinmaydi (o'qishda hisoblanadi); olib tashlash — sabab bilan, tarix saqlanadi.
- Shikoyat: xaridor global qidiruvdan yuboradi (shaxsiz, IP xeshi). Admin "rad etildi" yoki "chora
  ko'rildi" — ikkinchisida taklif `SUSPENDED` (`PLATFORM_REPORT`) va avtomatik qaytmaydi; e'tiroz — audit.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import OfferReport, PublicOffer, ShopBadge
from app.domains.network.services.offers import OfferService
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.db.session import set_shop_context
from app.shared.errors.base import InvalidTransitionError, NotFoundError
from app.shared.types.actor import ActorContext

BADGE = "network.shop_badge"
REPORT = "network.offer_report"
ReportReason = Literal["WRONG_PRICE", "NOT_AVAILABLE", "FAKE_PRODUCT", "FRAUD", "OTHER"]


class BadgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: str = Field(min_length=5, max_length=500, description="Nima tekshirildi (shaxsiy ma'lumotsiz)")
    valid_months: int = Field(default=12, ge=1, le=24)


class BadgeRevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


class BadgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    shop_id: UUID
    level: str
    evidence: str
    valid_until: str
    granted_at: str
    revoked_at: str | None
    revoke_reason: str | None
    active: bool


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: ReportReason
    note: str | None = Field(default=None, max_length=500)


class ReportOut(BaseModel):
    id: UUID
    offer_id: UUID
    shop_id: UUID
    shop_name: str
    offer_title: str
    reason: str
    note: str | None
    status: str
    created_at: str


class ReportList(BaseModel):
    items: list[ReportOut]


class ReportResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["DISMISS", "SUSPEND_OFFER"]
    resolution: str = Field(min_length=3, max_length=500)


def _badge_out(badge: ShopBadge) -> BadgeOut:
    return BadgeOut(
        id=badge.id,
        shop_id=badge.shop_id,
        level=badge.level,
        evidence=badge.evidence,
        valid_until=badge.valid_until.isoformat(),
        granted_at=badge.granted_at.isoformat(),
        revoked_at=badge.revoked_at.isoformat() if badge.revoked_at else None,
        revoke_reason=badge.revoke_reason,
        active=badge.revoked_at is None and badge.valid_until > utcnow(),
    )


async def verified_shop_ids(db: AsyncSession, shop_ids: Sequence[UUID]) -> set[UUID]:
    if not shop_ids:
        return set()
    rows = await db.execute(
        select(ShopBadge.shop_id).where(
            ShopBadge.shop_id.in_(list(shop_ids)),
            ShopBadge.revoked_at.is_(None),
            ShopBadge.valid_until > utcnow(),
        )
    )
    return set(rows.scalars())


class TrustService:
    def __init__(self, audit: AuditService, offers: OfferService) -> None:
        self.audit = audit
        self.offers = offers

    # ------------------------------------------------------------------ belgi
    async def grant(self, db: AsyncSession, actor: ActorContext, shop_id: UUID, data: BadgeIn) -> BadgeOut:
        shop = await db.get(Shop, shop_id)
        if shop is None:
            raise NotFoundError("Shop not found")
        if shop.status != "ACTIVE":
            raise InvalidTransitionError(
                "Only active shops can be verified", entity=BADGE, **{"from": shop.status}, command="GRANT"
            )
        now = utcnow()
        for old in (
            await db.execute(
                select(ShopBadge).where(ShopBadge.shop_id == shop_id, ShopBadge.revoked_at.is_(None))
            )
        ).scalars():
            old.revoked_at, old.revoke_reason = now, "RENEWED"
        badge = ShopBadge(
            shop_id=shop_id,
            evidence=data.evidence.strip(),
            valid_until=now + timedelta(days=30 * data.valid_months),
            granted_by=actor.actor_id,
        )
        db.add(badge)
        await db.flush()
        await db.refresh(badge)
        await self.audit.record(
            db,
            action="network.badge.granted",
            entity_type=BADGE,
            entity_id=badge.id,
            actor=_on(actor, shop_id),
        )
        return _badge_out(badge)

    async def revoke(self, db: AsyncSession, actor: ActorContext, shop_id: UUID, data: BadgeRevokeIn) -> None:
        rows = (
            await db.execute(
                select(ShopBadge).where(ShopBadge.shop_id == shop_id, ShopBadge.revoked_at.is_(None))
            )
        ).scalars()
        found = False
        for badge in rows:
            badge.revoked_at, badge.revoke_reason = utcnow(), data.reason.strip()
            found = True
        if not found:
            raise NotFoundError("No active badge")
        await self.audit.record(
            db,
            action="network.badge.revoked",
            entity_type=BADGE,
            entity_id=shop_id,
            actor=_on(actor, shop_id),
            reason=data.reason.strip(),
        )

    async def history(self, db: AsyncSession, shop_id: UUID) -> list[BadgeOut]:
        rows = await db.execute(
            select(ShopBadge).where(ShopBadge.shop_id == shop_id).order_by(ShopBadge.granted_at.desc())
        )
        return [_badge_out(b) for b in rows.scalars()]

    # ------------------------------------------------------------------ shikoyat
    async def report(
        self, db: AsyncSession, offer_id: UUID, shop_id: UUID, data: ReportIn, ip_hash: str
    ) -> None:
        db.add(
            OfferReport(
                offer_id=offer_id,
                shop_id=shop_id,
                reason=data.reason,
                note=(data.note or "").strip() or None,
                ip_hash=ip_hash,
            )
        )
        await db.flush()

    async def reports(self, db: AsyncSession, status: str = "OPEN") -> ReportList:
        rows = await db.execute(
            select(OfferReport, Shop.name)
            .join(Shop, Shop.id == OfferReport.shop_id)
            .where(OfferReport.status == status)
            .order_by(OfferReport.created_at)
            .limit(200)
        )
        items: list[ReportOut] = []
        for report, shop_name in rows:
            await set_shop_context(db, report.shop_id)
            offer = await db.get(PublicOffer, report.offer_id)
            items.append(
                ReportOut(
                    id=report.id,
                    offer_id=report.offer_id,
                    shop_id=report.shop_id,
                    shop_name=shop_name,
                    offer_title=offer.title if offer else "—",
                    reason=report.reason,
                    note=report.note,
                    status=report.status,
                    created_at=report.created_at.isoformat(),
                )
            )
        return ReportList(items=items)

    async def resolve(
        self, db: AsyncSession, actor: ActorContext, report_id: UUID, data: ReportResolveIn
    ) -> None:
        report = await db.get(OfferReport, report_id, with_for_update=True)
        if report is None:
            raise NotFoundError("Report not found")
        if report.status != "OPEN":
            raise InvalidTransitionError(
                "Report is closed", entity=REPORT, **{"from": report.status}, command=data.action
            )
        report.status = "ACTIONED" if data.action == "SUSPEND_OFFER" else "DISMISSED"
        report.resolution, report.resolved_by, report.resolved_at = (
            data.resolution.strip(),
            actor.actor_id,
            utcnow(),
        )
        on_shop = _on(actor, report.shop_id)
        if data.action == "SUSPEND_OFFER":
            await set_shop_context(db, report.shop_id)
            offer = (
                await db.execute(
                    select(PublicOffer).where(PublicOffer.id == report.offer_id).with_for_update()
                )
            ).scalar_one_or_none()
            if offer is not None and offer.status == "ACTIVE":
                offer.status, offer.withdraw_reason, offer.withdrawn_at = (
                    "SUSPENDED",
                    "PLATFORM_REPORT",
                    utcnow(),
                )
                offer.listing_version += 1
                await db.flush()
                await self.offers._emit(db, on_shop, offer, "network.public_offer.withdrawn")
        await db.flush()
        await self.audit.record(
            db,
            action="network.report.resolved",
            entity_type=REPORT,
            entity_id=report.id,
            actor=on_shop,
            reason=data.resolution.strip(),
            diff={"action": data.action},
        )


def _on(actor: ActorContext, shop_id: UUID) -> ActorContext:
    return ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        shop_id=shop_id,
        surface=actor.surface,
        roles=actor.roles,
        membership_id=actor.membership_id,
    )
