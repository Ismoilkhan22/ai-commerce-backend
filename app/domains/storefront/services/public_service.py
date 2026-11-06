"""Ommaviy sayt o'qishlari (storefront.md §5, engineering/21 §6): faqat ochiq maydonlar, keshdan.

- Katalog va narx — `CatalogQueryPort`, mavjudlik — `StockQueryPort` (boshqa domen kodi import qilinmaydi).
- Kesh: ro'yxat va mahsulot 60 s (+ jitter), sozlamalar va sahifalar 300 s (saqlanganda darhol o'chadi).
- Mahsulot sahifasi keshdan berilsa ham holati har so'rovda qayta tekshiriladi: yashirilgan mahsulot
  darhol "topilmadi" (UAT-M07). Ro'yxatda u 60 s gacha ko'rinishi mumkin — buyurtma so'rovi baribir rad etadi.
- Narx va mavjudlik "taxminiy" — `as_of` bilan (BL-026); buyurtmada `commerce` qayta tekshiradi.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.storefront.common import (
    DOMAIN,
    LIST_TTL,
    SITE_TTL,
    accent_text_color,
    cached_json,
    index_version,
    pages_key,
    title_slug,
)
from app.domains.storefront.models.orm import Page
from app.domains.storefront.schemas import (
    PrivacySection,
    PublicBranchList,
    PublicBranchOut,
    PublicBranchStock,
    PublicCategoryList,
    PublicCategoryOut,
    PublicConsent,
    PublicContacts,
    PublicLegal,
    PublicPageLink,
    PublicPageOut,
    PublicPrivacy,
    PublicProductCardOut,
    PublicProductList,
    PublicProductOut,
    PublicShop,
    PublicSite,
    PublicSortParam,
    PublicTheme,
    PublicVariantOut,
)
from app.domains.storefront.site_gate import SiteGate
from app.platform.shops.models.orm import Branch, Shop, ShopPolicy
from app.platform.storage.services.file_service import FileService
from app.shared.cache import Cache
from app.shared.cache.keys import shop_key
from app.shared.clock import utcnow
from app.shared.consent import PRIVACY_KEYS, STOREFRONT_CONSENT_VERSION
from app.shared.contracts.catalog import CatalogQueryPort, PublicCategory
from app.shared.contracts.commerce import SkuAvailability, StockQueryPort, StockStatus
from app.shared.contracts.messaging import ChatAvailabilityPort
from app.shared.contracts.storefront import SiteAccess, ensure_open
from app.shared.errors.base import NotFoundError
from app.shared.i18n.translator import t

PAGE_ORDER = ("ABOUT", "DELIVERY_PAYMENT", "WARRANTY_RETURNS")
_RANK: dict[str, int] = {"IN_STOCK": 2, "LOW_STOCK": 1, "OUT_OF_STOCK": 0}


def _live_only(value: dict[str, Any], live: dict[UUID, int]) -> dict[str, Any]:
    """Keshdagi sahifadan hozir ko'rinmaydigan variantlarni olib tashlaydi, narxni joriyga almashtiradi."""
    variants = []
    for variant in value["variants"]:
        price = live.get(UUID(str(variant["sku_id"])))
        if price is not None:
            variants.append({**variant, "price_uzs_minor": price})
    return {**value, "variants": variants}


def _best(statuses: Sequence[StockStatus]) -> StockStatus:
    """Kartochkadagi umumiy holat: variantlardan eng yaxshisi."""
    return max(statuses, key=lambda s: _RANK[s], default="OUT_OF_STOCK")


class PublicService:
    def __init__(
        self,
        catalog: CatalogQueryPort,
        stock: StockQueryPort,
        files: FileService,
        cache: Cache,
        gate: SiteGate,
        site_url_template: str,
        chat: ChatAvailabilityPort | None = None,
    ) -> None:
        self.chat = chat
        self.catalog = catalog
        self.stock = stock
        self.files = files
        self.cache = cache
        self.gate = gate
        # Absolyut havolalar (canonical, OG, sitemap) so'rov sarlavhalaridan emas, sozlamadan (QA M04 U6)
        self.site_url_template = site_url_template

    # ================================================================== sayt
    async def site(self, db: AsyncSession, access: SiteAccess) -> PublicSite:
        url = self.site_url_template.format(slug=access.slug)
        shop_ref = PublicShop(name=access.shop_name, slug=access.slug, url=url)
        if access.state != "LIVE" and not access.preview:
            # "Tez orada" / "vaqtincha ishlamayapti": faqat shop nomi (storefront.md §0)
            return PublicSite(state=access.state, preview=access.preview, shop=shop_ref)
        site = await self.gate.site(db, access.shop_id) or {}
        shop = await db.get(Shop, access.shop_id)
        policy = await db.get(ShopPolicy, access.shop_id)
        assert shop is not None
        accent = str(site.get("accent_color") or "#7C3AED")
        logo_url = None
        if site.get("logo_file_id"):
            logo_id = UUID(str(site["logo_file_id"]))
            logo_url = (await self._urls(db, access.shop_id, [logo_id])).get(logo_id)
        pages = await self._published_pages(db, access.shop_id)
        return PublicSite(
            state=access.state,
            preview=access.preview,
            shop=shop_ref,
            theme=PublicTheme(
                accent_color=accent,
                accent_text_color=accent_text_color(accent),
                theme_mode="DARK" if site.get("theme_mode") == "DARK" else "LIGHT",
            ),
            logo_url=logo_url,
            tagline=site.get("tagline"),
            seo_description=site.get("seo_description") or site.get("tagline"),
            contacts=PublicContacts(
                phone=site.get("contact_phone"),
                email=site.get("contact_email"),
                telegram_url=f"https://t.me/{site['telegram_username']}"
                if site.get("telegram_username")
                else None,
                instagram_url=(
                    f"https://instagram.com/{site['instagram_username']}"
                    if site.get("instagram_username")
                    else None
                ),
            ),
            pages=[PublicPageLink(kind=p["kind"], title=p["title"]) for p in pages],
            delivery_enabled=policy.delivery_enabled if policy else True,
            stock_display="EXACT" if policy and policy.stock_display == "EXACT" else "STATUS_ONLY",
            pickup_branch_count=len(await self._pickup_branches(db, access.shop_id)),
            consent=PublicConsent(version=STOREFRONT_CONSENT_VERSION, text=t("consent.storefront_order")),
            legal=PublicLegal(legal_name=shop.legal_name, tin=shop.tin),
            chat_enabled=await self.chat.webchat_enabled(db, access.shop_id) if self.chat else False,
        )

    async def privacy(self, db: AsyncSession, access: SiteAccess) -> PublicPrivacy:
        """Maxfiylik siyosati — platforma shabloni + shop rekvizitlari (26 §8), xaridor tilida."""
        ensure_open(access)
        shop = await db.get(Shop, access.shop_id)
        assert shop is not None
        site = await self.gate.site(db, access.shop_id) or {}
        contact = str(site.get("contact_phone") or site.get("contact_email") or shop.name)
        sections = [
            PrivacySection(
                key=key.removeprefix("privacy."),
                text=t(
                    key,
                    shop_name=shop.name,
                    legal_name=shop.legal_name or shop.name,
                    tin=shop.tin,
                    contact=contact,
                ),
            )
            for key in PRIVACY_KEYS
            if key != "privacy.title"
        ]
        return PublicPrivacy(version=STOREFRONT_CONSENT_VERSION, title=t("privacy.title"), sections=sections)

    # ================================================================== sahifalar va filiallar
    async def page(self, db: AsyncSession, access: SiteAccess, kind: str) -> PublicPageOut:
        ensure_open(access)
        for item in await self._published_pages(db, access.shop_id):
            if item["kind"] == kind:
                return PublicPageOut(kind=item["kind"], title=item["title"], body_md=item["body_md"])
        raise NotFoundError("Page not found")

    async def branches(self, db: AsyncSession, access: SiteAccess) -> PublicBranchList:
        """Ochiq olib ketish joylari (BL-010). Manzilni ega o'zi kiritgan — tasdiqlangan (BL-009)."""
        ensure_open(access)
        return PublicBranchList(
            items=[
                PublicBranchOut(
                    id=b.id,
                    name=b.name,
                    address=b.address,
                    phone=b.phone,
                    working_hours=dict(b.working_hours or {}),
                    latitude=float(b.latitude) if b.latitude is not None else None,
                    longitude=float(b.longitude) if b.longitude is not None else None,
                )
                for b in await self._pickup_branches(db, access.shop_id)
            ]
        )

    # ================================================================== katalog
    async def categories(self, db: AsyncSession, access: SiteAccess) -> PublicCategoryList:
        ensure_open(access)
        return PublicCategoryList(
            items=[
                PublicCategoryOut(
                    code=c.code,
                    parent_code=c.parent_code,
                    name={"uz": c.name_uz, "ru": c.name_ru, "en": c.name_en},
                    product_count=c.product_count,
                )
                for c in await self._categories(db, access.shop_id)
            ]
        )

    async def products(
        self,
        db: AsyncSession,
        access: SiteAccess,
        *,
        category: str | None,
        q: str | None,
        sort: PublicSortParam,
        limit: int,
        cursor: str | None,
    ) -> PublicProductList:
        ensure_open(access)
        shop_id = access.shop_id
        query = (q or "").strip().lower() or None
        key = shop_key(
            shop_id,
            DOMAIN,
            "products:list",
            v=await index_version(self.cache, shop_id),
            cat=category,
            q=query,
            sort=sort,
            limit=limit,
            cursor=cursor,
        )

        async def load() -> dict[str, Any]:
            codes = None if category is None else await self._category_tree(db, shop_id, category)
            page = await self.catalog.public_products(
                db, shop_id, category_codes=codes, q=query, sort=sort, limit=limit, cursor=cursor
            )
            sku_ids = [sku_id for card in page.items for sku_id in card.sku_ids]
            stock = await self.stock.availability(db, shop_id, sku_ids)
            exact = await self._exact(db, shop_id)
            urls = await self._urls(db, shop_id, [c.image_file_id for c in page.items if c.image_file_id])
            items = []
            for card in page.items:
                variants = [stock[s] for s in card.sku_ids if s in stock]
                items.append(
                    PublicProductCardOut(
                        id=card.product_id,
                        slug=title_slug(card.title),
                        title=card.title,
                        brand=card.brand,
                        category_code=card.category_code,
                        image_url=urls.get(card.image_file_id) if card.image_file_id else None,
                        price_from_uzs_minor=card.price_from_uzs_minor,
                        variant_count=card.variant_count,
                        stock_status=_best([v.status for v in variants]),
                        available=sum(v.available for v in variants) if exact else None,
                    ).model_dump(mode="json")
                )
            return {
                "items": items,
                "next_cursor": page.next_cursor,
                "has_more": page.has_more,
                "as_of": utcnow().isoformat(),
            }

        return PublicProductList.model_validate(
            await cached_json(self.cache, key, LIST_TTL, load, jitter=True)
        )

    async def product(self, db: AsyncSession, access: SiteAccess, product_id: UUID) -> PublicProductOut:
        ensure_open(access)
        shop_id = access.shop_id
        # Keshdan berilsa ham holat har safar tekshiriladi: yashirilgan mahsulot, arxivlangan variant va
        # o'zgargan narx darhol ko'rinadi (UAT-M07, QA M04 F4). Keshda faqat og'ir qism (rasm, qoldiq, matn)
        live = await self.catalog.public_live_variants(db, shop_id, product_id)
        if not live:
            raise NotFoundError("Product not found")
        key = shop_key(shop_id, DOMAIN, "product", v=await index_version(self.cache, shop_id), id=product_id)

        async def load() -> dict[str, Any] | None:
            detail = await self.catalog.public_product(db, shop_id, product_id)
            if detail is None:
                return None
            stock = await self.stock.availability(db, shop_id, [v.sku_id for v in detail.variants])
            exact = await self._exact(db, shop_id)
            pickups = await self._pickup_branches(db, shop_id)
            per_branch = len(pickups) >= 2  # DEC-135: bitta joy bo'lsa filial bo'yicha ko'rsatish shart emas
            urls = await self._urls(db, shop_id, list(detail.image_file_ids))
            slug = title_slug(detail.title)
            variants = []
            for v in detail.variants:
                avail = stock.get(v.sku_id)
                variants.append(
                    PublicVariantOut(
                        sku_id=v.sku_id,
                        name=v.variant_name,
                        condition=v.condition,
                        warranty_months=v.warranty_months,
                        attributes=v.attributes,
                        price_uzs_minor=v.price_uzs_minor,
                        stock_status=avail.status if avail else "OUT_OF_STOCK",
                        available=(avail.available if avail else 0) if exact else None,
                        branches=self._branch_stock(pickups, avail, exact) if per_branch else None,
                    )
                )
            return PublicProductOut(
                id=detail.product_id,
                slug=slug,
                canonical_path=f"/p/{detail.product_id}/{slug}",
                title=detail.title,
                brand=detail.brand,
                description=detail.description,
                category_code=detail.category_code,
                images=[urls[f] for f in detail.image_file_ids if f in urls],
                variants=variants,
                as_of=utcnow(),
            ).model_dump(mode="json")

        value = await cached_json(self.cache, key, LIST_TTL, load, jitter=True)
        if value is not None and not _live_only(value, live)["variants"]:
            # Keshdagi variantlarning hammasi endi ko'rinmaydi, yangisi esa bor — keshni yangilaymiz
            await self.cache.delete(key)
            value = await cached_json(self.cache, key, LIST_TTL, load, jitter=True)
        if value is None or not (value := _live_only(value, live))["variants"]:
            raise NotFoundError("Product not found")
        return PublicProductOut.model_validate(value)

    # ================================================================== ichki
    @staticmethod
    def _branch_stock(
        pickups: list[Branch], avail: SkuAvailability | None, exact: bool
    ) -> list[PublicBranchStock]:
        found = {b.branch_id: b for b in (avail.pickup_branches if avail else ())}
        result = []
        for branch in pickups:
            stock = found.get(branch.id)
            result.append(
                PublicBranchStock(
                    branch_id=branch.id,
                    name=branch.name,
                    stock_status=stock.status if stock else "OUT_OF_STOCK",
                    available=(stock.available if stock else 0) if exact else None,
                )
            )
        return result

    async def _exact(self, db: AsyncSession, shop_id: UUID) -> bool:
        return (await self.stock.display_policy(db, shop_id)).stock_display == "EXACT"

    async def _urls(self, db: AsyncSession, shop_id: UUID, file_ids: list[UUID]) -> dict[UUID, str]:
        """Faqat ochiq fayllar (mahsulot rasmi, logotip) — yopiq faylning havolasi saytga chiqmaydi."""
        if not file_ids:
            return {}
        rows = await self.files.by_ids(db, shop_id, file_ids)
        return {fid: self.files.url_for(row)[0] for fid, row in rows.items() if row.is_public}

    async def _categories(self, db: AsyncSession, shop_id: UUID) -> list[PublicCategory]:
        key = shop_key(shop_id, DOMAIN, "categories", v=await index_version(self.cache, shop_id))

        async def load() -> list[dict[str, Any]]:
            return [c.__dict__ for c in await self.catalog.public_categories(db, shop_id)]

        rows = await cached_json(self.cache, key, LIST_TTL, load, jitter=True)
        return [PublicCategory(**row) for row in rows]

    async def _category_tree(self, db: AsyncSession, shop_id: UUID, code: str) -> list[str]:
        """Toifa va uning hamma bolalari (GPU → GPU; PC_PARTS → PC_PARTS, GPU, CPU…)."""
        categories = await self._categories(db, shop_id)
        children: dict[str | None, list[str]] = {}
        for c in categories:
            children.setdefault(c.parent_code, []).append(c.code)
        if code not in {c.code for c in categories}:
            return []
        result, stack = [], [code]
        while stack:
            current = stack.pop()
            result.append(current)
            stack.extend(children.get(current, []))
        return result

    async def _published_pages(self, db: AsyncSession, shop_id: UUID) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            rows = (
                await db.execute(select(Page).where(Page.shop_id == shop_id, Page.is_published.is_(True)))
            ).scalars()
            pages = [{"kind": p.kind, "title": p.title, "body_md": p.body_md} for p in rows]
            return sorted(pages, key=lambda p: PAGE_ORDER.index(p["kind"]))

        value: list[dict[str, Any]] = await cached_json(self.cache, pages_key(shop_id), SITE_TTL, load)
        return value

    @staticmethod
    async def _pickup_branches(db: AsyncSession, shop_id: UUID) -> list[Branch]:
        rows = await db.execute(
            select(Branch)
            .where(Branch.shop_id == shop_id, Branch.status == "ACTIVE", Branch.is_pickup_point.is_(True))
            .order_by(Branch.created_at, Branch.id)
        )
        return list(rows.scalars())
