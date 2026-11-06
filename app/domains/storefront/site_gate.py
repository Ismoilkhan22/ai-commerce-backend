"""Saytni topish va holati (SitePort, storefront.md §0, §5): `slug` → shop → sayt holati → xaridor nima
ko'radi.

- Shop URL'dagi slug'dan topiladi (10 daqiqa keshda); shop holati esa har so'rovda bazadan — to'xtatilgan
  shop darhol "vaqtincha ishlamayapti" bo'ladi.
- Tranzaksiyaga shu shop konteksti o'rnatiladi (RLS): narx, kurs va qoldiq paneldagidek faqat shu shopniki.
- Yopilgan shop va bunday slug yo'q — bir xil 404 (shop borligini taxmin qilib bo'lmaydi).
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.storefront.common import SITE_TTL, SLUG_TTL, PreviewSigner, cached_json, site_key, slug_key
from app.domains.storefront.models.orm import Site
from app.platform.shops.models.orm import Shop
from app.shared.cache import Cache
from app.shared.contracts.storefront import SiteAccess, SiteState
from app.shared.db.session import set_shop_context
from app.shared.errors.base import NotFoundError

_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
SITE_FIELDS = (
    "status",
    "logo_file_id",
    "accent_color",
    "theme_mode",
    "tagline",
    "seo_description",
    "contact_phone",
    "contact_email",
    "telegram_username",
    "instagram_username",
)


def site_state(shop_status: str, site_status: str) -> SiteState:
    """Shop to'xtatilgan → "vaqtincha ishlamayapti"; faollashtirilmagan → "tez orada"; keyin sayt holati."""
    if shop_status == "SUSPENDED":
        return "PAUSED"
    if shop_status != "ACTIVE":
        return "COMING_SOON"
    if site_status == "LIVE":
        return "LIVE"
    return "PAUSED" if site_status == "PAUSED" else "COMING_SOON"


def site_snapshot(site: Site | None) -> dict[str, Any] | None:
    if site is None:
        return None
    return {name: (str(v) if isinstance(v := getattr(site, name), UUID) else v) for name in SITE_FIELDS}


class SiteGate:
    def __init__(self, cache: Cache, preview: PreviewSigner) -> None:
        self.cache = cache
        self.preview = preview

    async def resolve(self, db: AsyncSession, slug: str, *, preview_token: str | None = None) -> SiteAccess:
        if not _SLUG.fullmatch(slug):
            raise NotFoundError("Site not found")
        shop = await self._shop(db, slug)
        if shop is None or shop.status == "CLOSED":
            raise NotFoundError("Site not found")
        await set_shop_context(db, shop.id)
        site = await self.site(db, shop.id)
        site_status = str(site["status"]) if site else "DRAFT"
        return SiteAccess(
            shop_id=shop.id,
            slug=shop.slug,
            shop_name=shop.name,
            shop_status=shop.status,
            site_status=site_status,
            state=site_state(shop.status, site_status),
            preview=self.preview.valid_for(preview_token, shop.id),
        )

    async def site(self, db: AsyncSession, shop_id: UUID) -> dict[str, Any] | None:
        """Sayt sozlamalari (5 daqiqa keshda, saqlanganda darhol o'chiriladi). Yozuv yo'q — None (DRAFT)."""

        async def load() -> dict[str, Any] | None:
            return site_snapshot(await db.get(Site, shop_id))

        value: dict[str, Any] | None = await cached_json(self.cache, site_key(shop_id), SITE_TTL, load)
        return value

    async def _shop(self, db: AsyncSession, slug: str) -> Shop | None:
        cached = await self.cache.get(slug_key(slug))
        if cached:
            shop = await db.get(Shop, UUID(cached))
            if shop is not None and shop.slug == slug:
                return shop
            await self.cache.delete(slug_key(slug))  # slug o'zgargan — qayta qidiriladi
        shop = (await db.execute(select(Shop).where(Shop.slug == slug))).scalar_one_or_none()
        if shop is not None:
            await self.cache.set(slug_key(slug), str(shop.id), SLUG_TTL)
        return shop
