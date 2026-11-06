"""Ommaviy sayt API: `/api/v1/storefront/{slug}/*` — anonim, faqat o'qish (21 §6, storefront.md §5).

Har so'rov: IP + shop bo'yicha limit (120/daq, 08 §5; sayt serverining o'zi — alohida, kattaroq chelak)
→ READ ONLY tranzaksiya → slug → shop konteksti (RLS) → sayt holati.
Ega ko'rib chiqish tokenini `X-Storefront-Preview` header'ida yoki `?preview=` da yuboradi.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.storefront.providers import StorefrontServices, storefront_services
from app.domains.storefront.schemas import (
    PageKind,
    PublicBranchList,
    PublicCategoryList,
    PublicPageOut,
    PublicPrivacy,
    PublicProductList,
    PublicProductOut,
    PublicSite,
    PublicSortParam,
)
from app.shared.client_ip import client_ip, from_trusted_proxy
from app.shared.contracts.storefront import SiteAccess
from app.shared.db.session import Database
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(tags=["storefront_public"])

READ_LIMIT_PER_MINUTE = 120
SSR_READ_LIMIT_DEFAULT = 3000


def read_bucket(request: Request, slug: str) -> tuple[str, int]:
    """Xaridor — o'z IP'si bo'yicha 120/daq. Sayt serverining o'zi (ishonchli proksi, xaridor IP'sini
    yubormagan) — shop bo'yicha alohida, kattaroq chelak: keshlangan SSR chaqiruvlari xaridorlar limitini,
    xaridorlar esa SSR'ni to'xtatib qo'ya olmaydi (QA M04 U1)."""
    ip = client_ip(request)
    if from_trusted_proxy(request, ip):
        limit = getattr(request.app.state, "storefront_ssr_read_limit", SSR_READ_LIMIT_DEFAULT)
        return f"sf-ssr:{slug[:63]}", limit
    return f"sf-read:{ip}:{slug[:63]}", READ_LIMIT_PER_MINUTE


@dataclass(frozen=True)
class PublicContext:
    db: AsyncSession
    access: SiteAccess


async def public_context(
    request: Request,
    slug: str,
    preview: Annotated[str | None, Query(max_length=200, description="Ko'rib chiqish tokeni")] = None,
    preview_header: Annotated[str | None, Header(alias="X-Storefront-Preview", max_length=200)] = None,
) -> AsyncIterator[PublicContext]:
    limiter: RateLimiter = request.app.state.rate_limiter
    key, limit = read_bucket(request, slug)
    await enforce(limiter, key, limit=limit)
    svc: StorefrontServices = request.app.state.storefront
    database: Database = request.app.state.db
    async with database.transaction(read_only=True) as db:
        access = await svc.gate.resolve(db, slug, preview_token=preview_header or preview)
        yield PublicContext(db=db, access=access)


Public = Annotated[PublicContext, Depends(public_context, scope="function")]
Storefront = Annotated[StorefrontServices, Depends(storefront_services)]


@router.get("/site", response_model=PublicSite)
async def get_site(ctx: Public, svc: Storefront) -> PublicSite:
    """Sayt holati (`LIVE`, `COMING_SOON`, `PAUSED`) va ochiq bo'lsa — ko'rinishi, kontaktlari, sahifalar
    menyusi, rozilik matni va versiyasi. Bunday shop yo'q yoki yopilgan — 404."""
    return await svc.public.site(ctx.db, ctx.access)


@router.get("/categories", response_model=PublicCategoryList)
async def list_categories(ctx: Public, svc: Storefront) -> PublicCategoryList:
    """Menyu: mahsuloti bor toifalar va ularning ota toifalari, nomlari 3 tilda."""
    return await svc.public.categories(ctx.db, ctx.access)


@router.get("/products", response_model=PublicProductList)
async def list_products(
    ctx: Public,
    svc: Storefront,
    category: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Z0-9_]+$")] = None,
    q: Annotated[str | None, Query(max_length=100, description="Nom, brend yoki SKU kodi")] = None,
    sort: PublicSortParam = "newest",
    limit: Annotated[int, Query(ge=1, le=48)] = 24,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> PublicProductList:
    """Katalog: faqat chiqarilgan mahsulotlar, eng arzon variant narxi (so'mda) va mavjudlik holati."""
    return await svc.public.products(
        ctx.db, ctx.access, category=category, q=q, sort=sort, limit=limit, cursor=cursor
    )


@router.get("/products/{product_id}", response_model=PublicProductOut)
async def get_product(product_id: UUID, ctx: Public, svc: Storefront) -> PublicProductOut:
    """Mahsulot sahifasi. Yashirilgan yoki arxivlangan bo'lsa — darhol 404 (kesh bo'lsa ham)."""
    return await svc.public.product(ctx.db, ctx.access, product_id)


@router.get("/pages/{kind}", response_model=PublicPageOut)
async def get_page(kind: PageKind, ctx: Public, svc: Storefront) -> PublicPageOut:
    """Chiqarilgan ma'lumot sahifasi (Markdown). Chiqarilmagan — 404."""
    return await svc.public.page(ctx.db, ctx.access, kind)


@router.get("/branches", response_model=PublicBranchList)
async def list_branches(ctx: Public, svc: Storefront) -> PublicBranchList:
    """Ochiq olib ketish joylari: manzil, telefon, ish vaqti."""
    return await svc.public.branches(ctx.db, ctx.access)


@router.get("/privacy", response_model=PublicPrivacy)
async def get_privacy(ctx: Public, svc: Storefront) -> PublicPrivacy:
    """Maxfiylik siyosati — platforma shabloni va shop rekvizitlari, xaridor tilida (Accept-Language)."""
    return await svc.public.privacy(ctx.db, ctx.access)
