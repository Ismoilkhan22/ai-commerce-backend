"""Shop paneli: sayt sozlamalari, sahifalar, ochish/yopish, ko'rib chiqish havolasi (storefront.md §1–§2).

- Faqat ega o'zgartiradi (`storefront.site.edit`), menejer ko'radi (`storefront.site.view`).
- Yozuv ega birinchi marta saqlaganda yaratiladi (`If-Match: "v0"`); yozuv yo'q — sayt DRAFT.
- Har o'zgarish — audit (faqat maydon nomlari); holat o'zgarishi — `transition_log`.
- Saqlangandan keyin sayt keshi darhol o'chiriladi (08 §4.3).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.storefront.common import (
    MIN_ACCENT_CONTRAST,
    PreviewSigner,
    background,
    contrast,
    invalidate_shop,
)
from app.domains.storefront.models.orm import DEFAULT_ACCENT, PAGE_KINDS, Page, Site
from app.domains.storefront.schemas import (
    LogoOut,
    PageList,
    PageOut,
    PageUpdate,
    PreviewTokenOut,
    SiteOut,
    SiteProblem,
    SiteUpdate,
)
from app.domains.storefront.site_gate import site_state
from app.domains.storefront.state_machine import SITE
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Shop
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.cache import Cache
from app.shared.clock import utcnow
from app.shared.errors.base import ValidationError
from app.shared.http import check_version
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

PAGE_ENTITY = "storefront.page"
LOGO_PURPOSE = "SITE_LOGO"
# Standart sarlavhalar — shop matni bitta tilda (DEC-135), ega o'zgartiradi
DEFAULT_TITLES = {
    "ABOUT": "Biz haqimizda",
    "DELIVERY_PAYMENT": "Yetkazish va to‘lov",
    "WARRANTY_RETURNS": "Kafolat va qaytarish",
}
_TARGETS = {"PUBLISH": "LIVE", "PAUSE": "PAUSED", "RESUME": "LIVE"}


def _field(name: str, code: str, **params: object) -> dict[str, Any]:
    return {"field": name, "code": code, "params": params}


class SiteService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        files: FileService,
        cache: Cache,
        preview: PreviewSigner,
        site_url_template: str,
    ) -> None:
        self.use = use
        self.audit = audit
        self.files = files
        self.cache = cache
        self.preview = preview
        self.site_url_template = site_url_template

    # ================================================================== sozlamalar
    async def get(self, db: AsyncSession, actor: ActorContext) -> SiteOut:
        shop = await self._shop(db, actor)
        return await self._out(db, shop, await db.get(Site, shop.id))

    async def update(
        self, db: AsyncSession, actor: ActorContext, expected_version: int, data: SiteUpdate
    ) -> SiteOut:
        shop = await self._shop(db, actor)
        site = await self._locked(db, shop.id)
        check_version(site.version if site else 0, expected_version)
        wanted = data.model_dump(exclude_unset=True)
        for name in ("accent_color", "theme_mode"):
            if name in wanted and wanted[name] is None:  # bo'sh qilib bo'lmaydi — standartiga qaytadi
                wanted[name] = DEFAULT_ACCENT if name == "accent_color" else "LIGHT"
        if wanted.get("contact_phone"):
            wanted["contact_phone"] = normalize_phone(wanted["contact_phone"], "contact_phone")
        if "accent_color" in wanted:
            wanted["accent_color"] = str(wanted["accent_color"]).upper()
        created = site is None
        if site is None:
            site = Site(shop_id=shop.id, status="DRAFT", accent_color=DEFAULT_ACCENT, theme_mode="LIGHT")
            db.add(site)
        old_logo = site.logo_file_id
        if wanted.get("logo_file_id") is not None:
            await self.files.usable(db, shop.id, wanted["logo_file_id"], LOGO_PURPOSE)
        changed = [name for name, value in wanted.items() if getattr(site, name) != value]
        for name in changed:
            setattr(site, name, wanted[name])
        if {"accent_color", "theme_mode"} & set(changed):
            self._check_contrast(site)
        if site.status != "DRAFT" and not site.contact_phone:
            # Ochiq saytda xaridor shopga qo'ng'iroq qila olishi kerak — telefonni o'chirib bo'lmaydi
            raise ValidationError("Phone required", fields=[_field("contact_phone", "required")])
        if changed or created:
            site.updated_by = actor.membership_id
            await db.flush()
            await db.refresh(site)  # updated_at — server tomonida (onupdate)
            if "logo_file_id" in changed and old_logo is not None:
                await self.files.mark_deleted(db, shop.id, old_logo)  # eski logotip — yetim fayl qolmasin
            await self.audit.record(
                db,
                action="storefront.site.created" if created else "storefront.site.updated",
                entity_type=SITE,
                entity_id=shop.id,
                actor=actor,
                entity_version=site.version,
                diff={"changed_fields": sorted(changed)},
            )
            await invalidate_shop(self.cache, shop.id)
        return await self._out(db, shop, site)

    async def transition(
        self, db: AsyncSession, actor: ActorContext, command: str, expected_version: int
    ) -> SiteOut:
        """Ochish (PUBLISH), vaqtincha yopish (PAUSE), qayta ochish (RESUME)."""
        shop = await self._shop(db, actor)
        site = await self._locked(db, shop.id)
        check_version(site.version if site else 0, expected_version)
        current = site.status if site else "DRAFT"
        rule = self.use.validate_transition(SITE, current, _TARGETS[command], command, actor)
        if command in ("PUBLISH", "RESUME"):
            problems = self._publish_problems(site)
            if problems:
                raise ValidationError("Site is not ready", fields=[_field(p.field, p.code) for p in problems])
        assert site is not None  # DRAFT'dan ochish — telefon majburiy, demak yozuv bor
        now = utcnow()
        site.status = rule.to_status
        site.status_changed_at = now
        if site.published_at is None and rule.to_status == "LIVE":
            site.published_at = now
        site.updated_by = actor.membership_id
        await db.flush()
        await db.refresh(site)
        await self.use.log_transition(db, entity_id=shop.id, rule=rule, actor=actor)
        await self.audit.record(
            db,
            action=f"storefront.site.{command.lower()}",
            entity_type=SITE,
            entity_id=shop.id,
            actor=actor,
            entity_version=site.version,
            diff={"status": {"old": current, "new": site.status}},
        )
        await invalidate_shop(self.cache, shop.id)
        return await self._out(db, shop, site)

    def preview_token(self, actor: ActorContext, slug: str) -> PreviewTokenOut:
        assert actor.shop_id is not None
        token, expires_at = self.preview.issue(actor.shop_id)
        return PreviewTokenOut(
            token=token, expires_at=expires_at, preview_url=f"{self._site_url(slug)}?preview={token}"
        )

    # ================================================================== sahifalar
    async def pages(self, db: AsyncSession, actor: ActorContext) -> PageList:
        rows = {
            p.kind: p for p in (await db.execute(select(Page).where(Page.shop_id == actor.shop_id))).scalars()
        }
        return PageList(items=[self._page_out(kind, rows.get(kind)) for kind in PAGE_KINDS])

    async def save_page(
        self, db: AsyncSession, actor: ActorContext, kind: str, expected_version: int, data: PageUpdate
    ) -> PageOut:
        shop = await self._shop(db, actor)
        page = (
            await db.execute(select(Page).where(Page.shop_id == shop.id, Page.kind == kind).with_for_update())
        ).scalar_one_or_none()
        check_version(page.version if page else 0, expected_version)
        if (
            await self._locked(db, shop.id) is None
        ):  # sahifa saytsiz bo'lmaydi (FK) — qoralama sayt yaratiladi
            db.add(Site(shop_id=shop.id, status="DRAFT", accent_color=DEFAULT_ACCENT, theme_mode="LIGHT"))
            await db.flush()
        created = page is None
        if page is None:
            page = Page(shop_id=shop.id, kind=kind, title=data.title, body_md=data.body_md)
            db.add(page)
        changed = [n for n, v in data.model_dump().items() if created or getattr(page, n) != v]
        for name in changed:
            setattr(page, name, getattr(data, name))
        if changed:
            page.updated_by = actor.membership_id
            await db.flush()
            await db.refresh(page)
            await self.audit.record(
                db,
                action="storefront.page.saved",
                entity_type=PAGE_ENTITY,
                entity_id=page.id,
                actor=actor,
                entity_version=page.version,
                diff={"kind": kind, "changed_fields": sorted(changed)},
            )
            await invalidate_shop(self.cache, shop.id)
        return self._page_out(kind, page)

    # ================================================================== ichki
    def _site_url(self, slug: str) -> str:
        return self.site_url_template.format(slug=slug)

    @staticmethod
    def _check_contrast(site: Site) -> None:
        """Oq fonda och sariq tugma o'qilmaydi — bunday rangni tanlab bo'lmaydi (storefront.md §1)."""
        ratio = contrast(site.accent_color, background(site.theme_mode))
        if ratio < MIN_ACCENT_CONTRAST:
            raise ValidationError(
                "Accent color contrast is too low",
                fields=[
                    _field(
                        "accent_color", "low_contrast", min_ratio=MIN_ACCENT_CONTRAST, ratio=round(ratio, 2)
                    )
                ],
            )

    @staticmethod
    def _publish_problems(site: Site | None) -> list[SiteProblem]:
        """Saytni ochishdan oldin: xaridor shopga qo'ng'iroq qila olishi kerak — telefon majburiy."""
        if site is None or not site.contact_phone:
            return [SiteProblem(field="contact_phone", code="required")]
        return []

    async def _out(self, db: AsyncSession, shop: Shop, site: Site | None) -> SiteOut:
        logo = None
        if site is not None and site.logo_file_id is not None:
            files = await self.files.by_ids(db, shop.id, [site.logo_file_id])
            if (row := files.get(site.logo_file_id)) is not None:
                logo = LogoOut(file_id=row.id, url=self.files.url_for(row)[0])
        status = site.status if site else "DRAFT"
        return SiteOut(
            status=status,
            state=site_state(shop.status, status),
            slug=shop.slug,
            site_url=self._site_url(shop.slug),
            shop_status=shop.status,
            logo=logo,
            accent_color=site.accent_color if site else DEFAULT_ACCENT,
            theme_mode=site.theme_mode if site else "LIGHT",
            tagline=site.tagline if site else None,
            seo_description=site.seo_description if site else None,
            contact_phone=site.contact_phone if site else None,
            contact_email=site.contact_email if site else None,
            telegram_username=site.telegram_username if site else None,
            instagram_username=site.instagram_username if site else None,
            published_at=site.published_at if site else None,
            status_changed_at=site.status_changed_at if site else None,
            publish_problems=self._publish_problems(site) if status == "DRAFT" else [],
            version=site.version if site else 0,
            updated_at=site.updated_at if site else None,
        )

    @staticmethod
    def _page_out(kind: str, page: Page | None) -> PageOut:
        if page is None:
            return PageOut(
                kind=kind,
                title=DEFAULT_TITLES[kind],
                body_md="",
                is_published=False,
                version=0,
                updated_at=None,
            )
        return PageOut(
            kind=kind,
            title=page.title,
            body_md=page.body_md,
            is_published=page.is_published,
            version=page.version,
            updated_at=page.updated_at,
        )

    @staticmethod
    async def _locked(db: AsyncSession, shop_id: UUID) -> Site | None:
        return (
            await db.execute(select(Site).where(Site.shop_id == shop_id).with_for_update())
        ).scalar_one_or_none()

    @staticmethod
    async def _shop(db: AsyncSession, actor: ActorContext) -> Shop:
        assert actor.shop_id is not None
        shop = await db.get(Shop, actor.shop_id)
        assert shop is not None
        return shop
