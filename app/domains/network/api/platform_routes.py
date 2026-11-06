"""Platforma paneli: umumiy mahsulotga bog'lashni ko'rib chiqish (Stage 2, M23, BR-X08)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.domains.network.providers import NetworkServices, network_services
from app.domains.network.schemas import CanonicalList, LinkDecisionIn, ReviewList
from app.domains.network.services.ads import AdList, AdOut, AdRejectIn
from app.domains.network.services.trust import BadgeIn, BadgeOut, BadgeRevokeIn, ReportList, ReportResolveIn
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission

router = APIRouter(prefix="/network", tags=["network-platform"])

Network = Annotated[NetworkServices, Depends(network_services)]
CanReview = Annotated[RequestContext, Depends(require_platform_permission("platform.network.review"))]


@router.get("/review", response_model=ReviewList)
async def network_review_queue(ctx: CanReview, svc: Network) -> ReviewList:
    """Avtomatik bog'lanmagan (MPN yoki brend yo'q) ommaviy takliflar — eng eskisi birinchi."""
    return await svc.review.pending(ctx.db)


@router.get("/canonicals", response_model=CanonicalList)
async def list_canonicals(
    ctx: CanReview, svc: Network, q: Annotated[str | None, Query(max_length=100)] = None
) -> CanonicalList:
    return await svc.review.canonicals(ctx.db, q)


@router.post("/review/{shop_id}/{sku_id}", status_code=204)
async def decide_link(
    shop_id: UUID, sku_id: UUID, body: LinkDecisionIn, ctx: CanReview, svc: Network
) -> None:
    """Mavjud umumiy mahsulotga bog'lash, yangisini yaratish yoki "bog'lanmaydi"."""
    await svc.review.decide(ctx.db, ctx.actor, shop_id, sku_id, body)


# ------------------------------------------------------------------ M29: belgi va shikoyatlar
CanVerify = Annotated[RequestContext, Depends(require_platform_permission("platform.shop.activate"))]


@router.get("/shops/{shop_id}/badges", response_model=list[BadgeOut])
async def shop_badges(shop_id: UUID, ctx: CanVerify, svc: Network) -> list[BadgeOut]:
    return await svc.trust.history(ctx.db, shop_id)


@router.post("/shops/{shop_id}/badges", response_model=BadgeOut, status_code=201)
async def grant_badge(shop_id: UUID, body: BadgeIn, ctx: CanVerify, svc: Network) -> BadgeOut:
    """ "Tasdiqlangan do'kon": dalil matni majburiy, 1…24 oy (BL-087). Eski faol belgi yangilanadi."""
    return await svc.trust.grant(ctx.db, ctx.actor, shop_id, body)


@router.post("/shops/{shop_id}/badges/revoke", status_code=204)
async def revoke_badge(shop_id: UUID, body: BadgeRevokeIn, ctx: CanVerify, svc: Network) -> None:
    await svc.trust.revoke(ctx.db, ctx.actor, shop_id, body)


@router.get("/reports", response_model=ReportList)
async def offer_reports(
    ctx: CanReview,
    svc: Network,
    status: Annotated[str, Query(pattern="^(OPEN|DISMISSED|ACTIONED)$")] = "OPEN",
) -> ReportList:
    return await svc.trust.reports(ctx.db, status)


@router.post("/reports/{report_id}/resolve", status_code=204)
async def resolve_report(report_id: UUID, body: ReportResolveIn, ctx: CanReview, svc: Network) -> None:
    """Rad etish yoki taklifni yashirish (`SUSPENDED`, `PLATFORM_REPORT` — ega o'zi qaytara olmaydi)."""
    await svc.trust.resolve(ctx.db, ctx.actor, report_id, body)


# ------------------------------------------------------------------ M37: reklamani tasdiqlash
@router.get("/ads", response_model=AdList)
async def pending_ads(ctx: CanReview, svc: Network) -> AdList:
    return await svc.ads.pending(ctx.db)


@router.post("/ads/{ad_id}/approve", response_model=AdOut)
async def approve_ad(ad_id: UUID, ctx: CanReview, svc: Network) -> AdOut:
    return await svc.ads.review(ctx.db, ctx.actor, ad_id, True, None)


@router.post("/ads/{ad_id}/reject", response_model=AdOut)
async def reject_ad(ad_id: UUID, body: AdRejectIn, ctx: CanReview, svc: Network) -> AdOut:
    return await svc.ads.review(ctx.db, ctx.actor, ad_id, False, body.reason)
