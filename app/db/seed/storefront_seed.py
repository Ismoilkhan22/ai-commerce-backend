"""Lokal demo: shop saytlari (4-modul) — `make seed` ichidan, qayta ishga tushirish xavfsiz.

- NoutbukUz, KompyuterPro, Hi-Tech Samarqand — sayt ochiq (LIVE): rang, logotip, kontaktlar, 3 ta sahifa.
- TechPC — sozlangan, lekin qoralama (shop hali tekshiruvda — xaridor "tez orada ochiladi" ko'radi).
- ByteShop — sayt ochiq, lekin shop to'xtatilgan: xaridor "vaqtincha ishlamayapti" ko'radi.
Sayti allaqachon bor shop o'tkazib yuboriladi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.seed.catalog_seed import png
from app.domains.storefront.common import PreviewSigner
from app.domains.storefront.domain_manifest import DOMAIN_MANIFEST as STOREFRONT_MANIFEST
from app.domains.storefront.models.orm import Site
from app.domains.storefront.schemas import PageUpdate, SiteUpdate
from app.domains.storefront.services.site_service import SiteService
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.manifest import MODULE_MANIFEST as SHOPS_MANIFEST
from app.platform.shops.models.orm import Shop
from app.platform.staff.manifest import MODULE_MANIFEST as STAFF_MANIFEST
from app.platform.staff.models.orm import Membership
from app.platform.staff.permissions import PermissionRegistry
from app.platform.storage.config import build_file_storage
from app.platform.storage.services.file_service import FileService
from app.platform.storage.signing import UrlSigner
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.cache import MemoryCache
from app.shared.db.session import Database, set_identity_context
from app.shared.types.actor import ActorContext

ABOUT = (
    "## {name} haqida\n\n"
    "{name} — {city}dagi kompyuter va texnika do'koni. Har bir mahsulot rasmiy kafolat bilan, "
    "sotishdan oldin tekshiriladi.\n\n"
    "- Yangi va kafolatli mahsulotlar\n- Mutaxassis maslahati: qaysi qism mos keladi, aytib beramiz\n"
    "- Do'konimizga kelib ko'rishingiz mumkin"
)
DELIVERY = (
    "## Yetkazish\n\n{city} bo'ylab yetkazamiz. Narxi va vaqti operator bilan kelishiladi.\n\n"
    "## To'lov\n\nTo'lov mahsulotni olganda: **naqd** yoki **karta** orqali. Saytda oldindan to'lov yo'q."
)
WARRANTY = (
    "## Kafolat\n\nKafolat muddati har mahsulot sahifasida ko'rsatilgan. Chekni yoki buyurtma raqamini "
    "saqlab qo'ying.\n\n## Qaytarish\n\nMahsulot ishlamasa, kafolat muddati ichida do'konga olib keling — "
    "tekshiramiz va almashtiramiz yoki ta'mirlaymiz."
)


@dataclass(frozen=True)
class SiteSeed:
    slug: str
    city: str
    accent: str
    theme: str
    logo_rgb: tuple[int, int, int]
    tagline: str
    phone: str
    telegram: str | None
    instagram: str | None
    publish: bool


SITES = (
    SiteSeed(
        "noutbukuz", "Toshkent", "#2563EB", "LIGHT", (37, 99, 235),
        "Noutbuklar — rasmiy kafolat bilan", "+998712001010", "noutbukuz_shop", "noutbuk.uz", publish=True,
    ),
    SiteSeed(
        "kompyuterpro", "Toshkent", "#059669", "LIGHT", (5, 150, 105),
        "Kompyuter qismlari va tayyor PC'lar", "+998712002020", "kompyuterpro_uz", None, publish=True,
    ),
    SiteSeed(
        "hitech-samarqand", "Samarqand", "#F59E0B", "DARK", (245, 158, 11),
        "Samarqanddagi texnika do'koni", "+998662003030", None, "hitech.samarqand", publish=True,
    ),
    SiteSeed(
        "techpc", "Toshkent", "#7C3AED", "LIGHT", (124, 58, 237),
        "Kompyuter qismlari — rasmiy kafolat bilan", "+998712000000", "techpc_uz", "techpc.uz", publish=False,
    ),
    SiteSeed(
        "byteshop", "Toshkent", "#DC2626", "LIGHT", (220, 38, 38),
        "Byte — har kuni yangi texnika", "+998712004040", None, None, publish=True,
    ),
)  # fmt: skip


@dataclass
class StorefrontSeedReport:
    sites: int = 0
    live: int = 0


def _services(settings: Settings) -> tuple[SiteService, FileService, PermissionRegistry]:
    manifests = [SHOPS_MANIFEST, STAFF_MANIFEST, STOREFRONT_MANIFEST]
    audit = AuditService()
    secret = settings.jwt_secret.get_secret_value()
    files = FileService(
        storage=build_file_storage(settings.storage_config()),
        signer=UrlSigner(secret),
        audit=audit,
        public_base_url=settings.public_files_url,
        signed_ttl=timedelta(seconds=settings.signed_url_ttl_seconds),
    )
    use = UseService(RulesRegistry.from_manifests(manifests), audit)
    # Seed'da kesh xotirada: ishlab turgan server keshi 5 daqiqada o'zi yangilanadi
    sites = SiteService(
        use, audit, files, MemoryCache(), PreviewSigner(secret), settings.storefront_public_url
    )
    return sites, files, PermissionRegistry.from_manifests(manifests)


async def _owner(db: AsyncSession, permissions: PermissionRegistry, shop_id: UUID) -> ActorContext | None:
    await set_identity_context(db, shop_id=shop_id)
    owner = (
        await db.execute(
            select(Membership).where(
                Membership.shop_id == shop_id, Membership.role == "OWNER", Membership.status == "ACTIVE"
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        return None
    await set_identity_context(db, shop_id=shop_id, principal_id=owner.principal_id)
    return ActorContext(
        actor_type="STAFF",
        actor_id=owner.principal_id,
        shop_id=shop_id,
        surface="shop",
        roles=frozenset({"OWNER"}),
        permissions=permissions.for_role("OWNER"),
        membership_id=owner.id,
    )


async def _seed_site(
    database: Database,
    sites: SiteService,
    files: FileService,
    permissions: PermissionRegistry,
    spec: SiteSeed,
) -> bool | None:
    """True — yaratildi va ochildi, False — yaratildi (qoralama), None — o'tkazib yuborildi."""
    async with database.transaction() as db:
        shop = (await db.execute(select(Shop).where(Shop.slug == spec.slug))).scalar_one_or_none()
        if shop is None:
            return None
        owner = await _owner(db, permissions, shop.id)
        if owner is None or await db.get(Site, shop.id) is not None:
            return None
        logo = await files.upload(db, owner, "SITE_LOGO", png(spec.logo_rgb, 128), f"{spec.slug}-logo.png")
        site = await sites.update(
            db,
            owner,
            0,
            SiteUpdate(
                logo_file_id=logo.id,
                accent_color=spec.accent,
                theme_mode=spec.theme,
                tagline=spec.tagline,
                seo_description=f"{shop.name}: {spec.tagline.lower()}. {spec.city}.",
                contact_phone=spec.phone,
                telegram_username=spec.telegram,
                instagram_username=spec.instagram,
            ),
        )
        texts = {"ABOUT": ABOUT, "DELIVERY_PAYMENT": DELIVERY, "WARRANTY_RETURNS": WARRANTY}
        titles = {"ABOUT": "Biz haqimizda", "DELIVERY_PAYMENT": "Yetkazish va to‘lov"}
        titles["WARRANTY_RETURNS"] = "Kafolat va qaytarish"
        for kind, text in texts.items():
            body = text.format(name=shop.name, city=spec.city)
            await sites.save_page(
                db, owner, kind, 0, PageUpdate(title=titles[kind], body_md=body, is_published=True)
            )
        if spec.publish:
            await sites.transition(db, owner, "PUBLISH", site.version)
        return spec.publish


async def run_storefront_seed(settings: Settings) -> StorefrontSeedReport:
    report = StorefrontSeedReport()
    sites, files, permissions = _services(settings)
    database = Database(settings.database_config())
    try:
        for spec in SITES:
            result = await _seed_site(database, sites, files, permissions, spec)
            if result is not None:
                report.sites += 1
                report.live += int(result)
    finally:
        await database.dispose()
    return report
