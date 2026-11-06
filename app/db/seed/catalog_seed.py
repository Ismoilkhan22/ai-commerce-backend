"""Lokal demo katalog (2-modul): texnik kutubxona, 3 ta shop mahsulotlari, narx va kurs, rasmlar.

`dev_seed.run_seed` chaqiradi. Hammasi servislar orqali — audit, o'tishlar jurnali va "ikki ko'z" tasdig'i
haqiqiydagidek. Qayta ishga tushirish xavfsiz: kutubxonadagi model va mahsuloti bor shop o'tkazib yuboriladi.
Model nomlari va narxlar taxminiy (demo uchun), texnik qiymatlar ishlab chiqaruvchi sahifalariga yaqin.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.dependencies import get_import_stock_results
from app.domains.catalog.domain_manifest import DOMAIN_MANIFEST as CATALOG_MANIFEST
from app.domains.catalog.pc_specs.models.orm import ReferenceHardwareSpec, SpecRequest
from app.domains.catalog.pc_specs.normalize import normalize_code
from app.domains.catalog.pc_specs.schemas import HardwareSpecIn, SpecRequestIn
from app.domains.catalog.pricing.schemas import ExchangeRateIn
from app.domains.catalog.products.models.orm import Product
from app.domains.catalog.products.schemas import PriceIn, ProductCreate, SkuIn
from app.domains.catalog.providers import CatalogServices, build_catalog_services
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.manifest import MODULE_MANIFEST as SHOPS_MANIFEST
from app.platform.shops.models.orm import Shop
from app.platform.staff.manifest import MODULE_MANIFEST as STAFF_MANIFEST
from app.platform.staff.models.orm import Membership, PlatformStaff, Principal
from app.platform.staff.permissions import PLATFORM_ROLE_PERMISSIONS, PermissionRegistry
from app.platform.storage.local import LocalDiskStorage
from app.platform.storage.services.file_service import FileService
from app.platform.storage.signing import UrlSigner
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.db.session import Database, set_identity_context
from app.shared.types.actor import ActorContext


@dataclass(frozen=True)
class SpecSeed:
    category: str
    brand: str
    model_name: str
    attributes: dict[str, Any]
    source_url: str
    mpn: str | None = None
    approve: bool = True  # False — tasdiq navbatida qoladi (platforma panelida ko'rinsin)


@dataclass(frozen=True)
class SkuSeed:
    code: str
    amount_minor: int
    currency: str = "UZS"
    model_name: str | None = None
    variant: str | None = None
    warranty: int | None = 12
    condition: str = "NEW"


@dataclass(frozen=True)
class ProductSeed:
    category: str
    brand: str
    title: str
    status: str  # DRAFT | PUBLISHED | HIDDEN | ARCHIVED
    skus: tuple[SkuSeed, ...]
    image: tuple[int, int, int] | None = None
    description: str | None = None


@dataclass(frozen=True)
class ShopCatalogSeed:
    slug: str
    rate: str
    rate_age_days: int  # 4 — "eskirgan kurs" ko'rinishi uchun
    products: tuple[ProductSeed, ...]
    spec_requests: tuple[tuple[str, str, str, str], ...] = ()  # (sku kodi, tur, brend, model)


SPECS = (
    SpecSeed(
        "GPU",
        "MSI",
        "GeForce RTX 4060 Ventus 2X Black 8G OC",
        {
            "length_mm": 199,
            "slot_width": 2.0,
            "board_power_w": 115,
            "recommended_psu_w": 550,
            "memory_gb": 8,
            "power_connectors": [{"type": "PCIE_8PIN", "count": 1}],
        },
        "https://www.msi.com/Graphics-Card/GeForce-RTX-4060-VENTUS-2X-BLACK-8G-OC",
    ),
    SpecSeed(
        "GPU",
        "Gigabyte",
        "GeForce RTX 4070 SUPER WINDFORCE OC 12G",
        {
            "length_mm": 261,
            "slot_width": 2.5,
            "board_power_w": 220,
            "recommended_psu_w": 650,
            "memory_gb": 12,
            "power_connectors": [{"type": "12VHPWR", "count": 1}],
        },
        "https://www.gigabyte.com/Graphics-Card/GV-N407SWF3OC-12GD",
    ),
    SpecSeed(
        "GPU",
        "Sapphire",
        "Pulse Radeon RX 7600 8GB",
        {
            "length_mm": 240,
            "slot_width": 2.0,
            "board_power_w": 165,
            "recommended_psu_w": 550,
            "memory_gb": 8,
            "power_connectors": [{"type": "PCIE_8PIN", "count": 1}],
        },
        "https://www.sapphiretech.com/en/consumer/pulse-radeon-rx-7600-8g-gddr6",
    ),
    SpecSeed(
        "CPU",
        "AMD",
        "Ryzen 5 7600",
        {
            "socket": "AM5",
            "memory_types": ["DDR5"],
            "base_power_w": 65,
            "max_power_w": 88,
            "integrated_graphics": True,
            "cooler_included": True,
        },
        "https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-5-7600.html",
        mpn="100-100001015BOX",
    ),
    SpecSeed(
        "CPU",
        "Intel",
        "Core i5-14400F",
        {
            "socket": "LGA1700",
            "memory_types": ["DDR4", "DDR5"],
            "base_power_w": 65,
            "max_power_w": 148,
            "integrated_graphics": False,
            "cooler_included": True,
        },
        "https://www.intel.com/content/www/us/en/products/sku/236774/",
    ),
    SpecSeed(
        "MOTHERBOARD",
        "MSI",
        "PRO B650M-A WIFI",
        {
            "socket": "AM5",
            "chipset": "B650",
            "form_factor": "MICRO_ATX",
            "memory_type": "DDR5",
            "memory_slots": 4,
            "max_memory_gb": 192,
            "m2_slots": 2,
            "sata_ports": 4,
        },
        "https://www.msi.com/Motherboard/PRO-B650M-A-WIFI",
    ),
    SpecSeed(
        "MOTHERBOARD",
        "ASUS",
        "PRIME B760M-A D4",
        {
            "socket": "LGA1700",
            "chipset": "B760",
            "form_factor": "MICRO_ATX",
            "memory_type": "DDR4",
            "memory_slots": 4,
            "max_memory_gb": 128,
            "m2_slots": 2,
            "sata_ports": 4,
        },
        "https://www.asus.com/motherboards-components/motherboards/prime/prime-b760m-a-d4/",
    ),
    SpecSeed(
        "RAM",
        "Kingston",
        "FURY Beast 32GB (2x16GB) DDR5-6000",
        {
            "type": "DDR5",
            "form_factor": "DIMM",
            "module_count": 2,
            "capacity_per_module_gb": 16,
            "speed_mts": 6000,
        },
        "https://www.kingston.com/en/memory/gaming/kingston-fury-beast-ddr5-memory",
    ),
    SpecSeed(
        "STORAGE",
        "Samsung",
        "990 PRO 1TB",
        {"interface": "NVME", "form_factor": "M2_2280", "capacity_gb": 1000},
        "https://www.samsung.com/semiconductor/minisite/ssd/product/consumer/990pro/",
    ),
    SpecSeed(
        "PSU",
        "DeepCool",
        "PK650D",
        {
            "wattage_w": 650,
            "form_factor": "ATX",
            "length_mm": 140,
            "connectors": [{"type": "PCIE_8PIN", "count": 2}],
        },
        "https://www.deepcool.com/products/PowerSupplyUnits/",
    ),
    SpecSeed(
        "CASE",
        "Zalman",
        "i3 Neo",
        {
            "supported_mb_form_factors": ["ATX", "MICRO_ATX", "MINI_ITX"],
            "max_gpu_length_mm": 315,
            "max_cpu_cooler_height_mm": 160,
            "psu_form_factor": "ATX",
        },
        "https://www.zalman.com/",
    ),
    SpecSeed(
        "CPU_COOLER",
        "DeepCool",
        "AK400",
        {
            "type": "AIR",
            "supported_sockets": ["AM5", "AM4", "LGA1700"],
            "height_mm": 155,
            "tdp_rating_w": 220,
        },
        "https://www.deepcool.com/products/Cooling/cpuaircoolers/",
    ),
    SpecSeed(
        "GPU",
        "MSI",
        "GeForce RTX 5060 Ti 16G Ventus 2X OC",
        {"length_mm": 197, "board_power_w": 180, "memory_gb": 16},
        "https://www.msi.com/Graphics-Card/GeForce-RTX-5060-Ti-16G-VENTUS-2X-OC",
        approve=False,
    ),
)

SHOP_CATALOGS = (
    ShopCatalogSeed(
        "techpc",
        rate="12850",
        rate_age_days=0,
        products=(
            ProductSeed(
                "GPU",
                "MSI",
                "MSI GeForce RTX 4060 Ventus 2X Black 8G OC",
                "PUBLISHED",
                (
                    SkuSeed(
                        "TP-GPU-4060",
                        480_000_000,
                        model_name="GeForce RTX 4060 Ventus 2X Black 8G OC",
                        warranty=36,
                    ),
                ),
                image=(34, 139, 34),
                description="8 GB GDDR6, DLSS 3, bitta 8-pin. 1080p o'yinlar uchun.",
            ),
            ProductSeed(
                "GPU",
                "Gigabyte",
                "Gigabyte GeForce RTX 4070 SUPER WINDFORCE OC 12G",
                "PUBLISHED",
                (
                    SkuSeed(
                        "TP-GPU-4070S", 62_000, "USD", "GeForce RTX 4070 SUPER WINDFORCE OC 12G", warranty=36
                    ),
                ),
                image=(30, 90, 160),
            ),
            ProductSeed(
                "CPU",
                "AMD",
                "AMD Ryzen 5 7600",
                "PUBLISHED",
                (
                    SkuSeed("TP-CPU-7600-BOX", 19_900, "USD", "Ryzen 5 7600", "BOX", warranty=36),
                    SkuSeed("TP-CPU-7600-TRAY", 18_500, "USD", "Ryzen 5 7600", "Tray", warranty=12),
                ),
                image=(200, 60, 40),
            ),
            ProductSeed(
                "MOTHERBOARD",
                "MSI",
                "MSI PRO B650M-A WIFI",
                "PUBLISHED",
                (SkuSeed("TP-MB-B650M", 215_000_000, model_name="PRO B650M-A WIFI", warranty=36),),
            ),
            ProductSeed(
                "RAM",
                "Kingston",
                "Kingston FURY Beast 32GB (2x16GB) DDR5-6000",
                "PUBLISHED",
                (
                    SkuSeed(
                        "TP-RAM-32D5",
                        145_000_000,
                        model_name="FURY Beast 32GB (2x16GB) DDR5-6000",
                        warranty=60,
                    ),
                ),
            ),
            ProductSeed(
                "STORAGE",
                "Samsung",
                "Samsung 990 PRO 1TB NVMe",
                "DRAFT",
                (SkuSeed("TP-SSD-990P-1T", 11_500, "USD", "990 PRO 1TB", warranty=60),),
            ),
            ProductSeed(
                "PSU",
                "DeepCool",
                "DeepCool PK650D 650W",
                "HIDDEN",
                (SkuSeed("TP-PSU-PK650D", 78_000_000, model_name="PK650D", warranty=36),),
            ),
            ProductSeed(
                "CPU_COOLER",
                "DeepCool",
                "DeepCool AK400",
                "PUBLISHED",
                (SkuSeed("TP-COOL-AK400", 39_000_000, model_name="AK400"),),
            ),
            ProductSeed(
                "GPU",
                "MSI",
                "MSI GeForce RTX 3060 Ventus 2X 12G (ishlatilgan)",
                "PUBLISHED",
                (
                    SkuSeed(
                        "TP-GPU-3060-U",
                        290_000_000,
                        model_name="GeForce RTX 3060 Ventus 2X 12G",
                        warranty=3,
                        condition="USED",
                    ),
                ),
            ),
        ),
        spec_requests=(("TP-GPU-3060-U", "GPU", "MSI", "GeForce RTX 3060 Ventus 2X 12G"),),
    ),
    ShopCatalogSeed(
        "noutbukuz",
        rate="12800",
        rate_age_days=0,
        products=(
            ProductSeed(
                "LAPTOP",
                "Lenovo",
                "Lenovo IdeaPad Slim 3 15IRH8 (i5-13420H, 16GB, 512GB)",
                "PUBLISHED",
                (SkuSeed("NB-LEN-IPS3-15", 64_900, "USD", warranty=12),),
            ),
            ProductSeed(
                "LAPTOP",
                "ASUS",
                "ASUS TUF Gaming A15 FA507NV (RTX 4060)",
                "PUBLISHED",
                (SkuSeed("NB-ASUS-TUF-A15", 104_900, "USD", warranty=24),),
                image=(90, 90, 90),
            ),
            ProductSeed(
                "LAPTOP",
                "HP",
                "HP 250 G10 (i3-1315U, 8GB, 256GB)",
                "PUBLISHED",
                (SkuSeed("NB-HP-250G10", 590_000_000, warranty=12),),
            ),
            ProductSeed(
                "MONITOR",
                "Samsung",
                'Samsung Odyssey G5 27" 165Hz',
                "DRAFT",
                (SkuSeed("NB-MON-G5-27", 360_000_000, warranty=24),),
            ),
            ProductSeed(
                "MOUSE",
                "Logitech",
                "Logitech G102 Lightsync",
                "ARCHIVED",
                (SkuSeed("NB-MOUSE-G102", 23_000_000, warranty=12),),
            ),
        ),
    ),
    ShopCatalogSeed(
        "kompyuterpro",
        rate="12780",
        rate_age_days=4,
        products=(
            ProductSeed(
                "CPU",
                "Intel",
                "Intel Core i5-14400F",
                "PUBLISHED",
                (SkuSeed("KP-CPU-14400F", 20_500, "USD", "Core i5-14400F", warranty=36),),
            ),
            ProductSeed(
                "MOTHERBOARD",
                "ASUS",
                "ASUS PRIME B760M-A D4",
                "PUBLISHED",
                (SkuSeed("KP-MB-B760M-D4", 165_000_000, model_name="PRIME B760M-A D4", warranty=36),),
            ),
            ProductSeed(
                "GPU",
                "Sapphire",
                "Sapphire Pulse Radeon RX 7600 8GB",
                "PUBLISHED",
                (SkuSeed("KP-GPU-RX7600", 27_900, "USD", "Pulse Radeon RX 7600 8GB", warranty=24),),
            ),
            ProductSeed(
                "CASE",
                "Zalman",
                "Zalman i3 Neo",
                "DRAFT",
                (SkuSeed("KP-CASE-I3NEO", 65_000_000, model_name="i3 Neo", warranty=12),),
            ),
        ),
    ),
)


@dataclass
class CatalogSeedReport:
    specs: int = 0
    products: int = 0
    files: int = 0
    skipped_shops: list[str] = field(default_factory=list)


def png(rgb: tuple[int, int, int], size: int = 96) -> bytes:
    """Bir rangli kichik PNG — tarmoqsiz, kutubxonasiz (demo rasm)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * size
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8 bit, RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


def _services(settings: Settings) -> tuple[CatalogServices, PermissionRegistry]:
    manifests = [SHOPS_MANIFEST, STAFF_MANIFEST, CATALOG_MANIFEST]
    audit = AuditService()
    files = FileService(
        storage=LocalDiskStorage(Path(settings.storage_local_dir)),
        signer=UrlSigner(settings.jwt_secret.get_secret_value()),
        audit=audit,
        public_base_url=settings.public_files_url,
        signed_ttl=timedelta(seconds=settings.signed_url_ttl_seconds),
    )
    use = UseService(RulesRegistry.from_manifests(manifests), audit)
    permissions = PermissionRegistry.from_manifests(manifests)
    return build_catalog_services(use, audit, files, permissions, get_import_stock_results()), permissions


async def _platform_actor(db: AsyncSession, phone: str) -> ActorContext | None:
    row = (
        await db.execute(
            select(PlatformStaff, Principal)
            .join(Principal, Principal.id == PlatformStaff.principal_id)
            .where(Principal.phone == phone, PlatformStaff.status == "ACTIVE")
        )
    ).one_or_none()
    if row is None:
        return None
    staff, principal = row
    await set_identity_context(db, principal_id=principal.id)
    return ActorContext(
        actor_type="PLATFORM",
        actor_id=principal.id,
        shop_id=None,
        surface="platform",
        roles=frozenset({staff.role}),
        permissions=PLATFORM_ROLE_PERMISSIONS.get(staff.role, frozenset()),
    )


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


async def _seed_specs(
    database: Database, svc: CatalogServices, admin_phone: str, editor_phone: str, report: CatalogSeedReport
) -> None:
    for spec in SPECS:
        async with database.transaction() as db:
            exists = (
                await db.execute(
                    select(ReferenceHardwareSpec.id).where(
                        ReferenceHardwareSpec.category == spec.category,
                        ReferenceHardwareSpec.model_normalized == normalize_code(spec.model_name),
                    )
                )
            ).first()
            if exists is not None:
                continue
            admin = await _platform_actor(db, admin_phone)
            assert admin is not None
            created = await svc.specs.create(
                db,
                admin,
                HardwareSpecIn(
                    category=spec.category,
                    brand=spec.brand,
                    model_name=spec.model_name,
                    mpn=spec.mpn,
                    attributes=spec.attributes,
                    source_url=spec.source_url,
                ),
            )
            editor = await _platform_actor(db, editor_phone)
            if (
                spec.approve and editor is not None
            ):  # "ikki ko'z": admin kiritadi, kutubxona muharriri tasdiqlaydi
                await svc.specs.approve(db, editor, created.id, 1)
            report.specs += 1


async def _seed_shop(
    database: Database,
    svc: CatalogServices,
    permissions: PermissionRegistry,
    spec: ShopCatalogSeed,
    report: CatalogSeedReport,
) -> UUID | None:
    async with database.transaction() as db:
        shop = (await db.execute(select(Shop).where(Shop.slug == spec.slug))).scalar_one_or_none()
        if shop is None:
            return None
        owner = await _owner(db, permissions, shop.id)
        if owner is None:
            return None
        has_products = (
            await db.execute(select(func.count()).select_from(Product).where(Product.shop_id == shop.id))
        ).scalar_one()
        if has_products:
            report.skipped_shops.append(spec.slug)
            return None
        await svc.pricing.add_rate(db, owner, ExchangeRateIn(rate=spec.rate))
        sku_ids: dict[str, UUID] = {}
        for item in spec.products:
            created = await svc.products.create(
                db,
                owner,
                ProductCreate(
                    category_code=item.category,
                    title=item.title,
                    brand=item.brand,
                    description=item.description,
                    skus=[
                        SkuIn(
                            sku_code=s.code,
                            variant_name=s.variant,
                            condition=s.condition,
                            model_name=s.model_name,
                            warranty_months=s.warranty,
                            price=PriceIn(amount_minor=s.amount_minor, currency=s.currency),
                        )
                        for s in item.skus
                    ],
                ),
            )
            sku_ids.update({s.sku_code: s.id for s in created.skus})
            if item.image is not None:
                uploaded = await svc.products.files.upload(
                    db, owner, "PRODUCT_IMAGE", png(item.image), f"{item.skus[0].code.lower()}.png"
                )
                await svc.products.attach_media(db, owner, created.id, uploaded.id)
                report.files += 1
            for command in {
                "PUBLISHED": ["PUBLISH"],
                "HIDDEN": ["PUBLISH", "HIDE"],
                "ARCHIVED": ["ARCHIVE"],
            }.get(item.status, []):
                await svc.products.transition(db, owner, created.id, command, None)
            report.products += 1
        existing_requests = (
            await db.execute(
                select(func.count()).select_from(SpecRequest).where(SpecRequest.shop_id == shop.id)
            )
        ).scalar_one()
        if not existing_requests:
            for code, category, brand, model in spec.spec_requests:
                await svc.links.create_request(
                    db,
                    owner,
                    SpecRequestIn(
                        sku_id=sku_ids.get(code),
                        category=category,
                        brand=brand,
                        model_name=model,
                        comment="Ishlatilgan kartalar ham ko'p keladi — kutubxonaga qo'shib bering",
                    ),
                )
        return shop.id


async def _age_rate(settings: Settings, shop_id: UUID, days: int) -> None:
    """Kursni orqaga surish ("eskirgan kurs" ko'rinishi) — faqat shu skriptda, migrator bilan."""
    url = settings.database_migrator_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.shop_id', $1, true)", str(shop_id))  # FORCE RLS
            await conn.execute(
                "UPDATE catalog.exchange_rates SET effective_at = effective_at - make_interval(days => $2) "
                "WHERE shop_id = $1",
                shop_id,
                days,
            )
    finally:
        await conn.close()


async def run_catalog_seed(settings: Settings, admin_phone: str, editor_phone: str) -> CatalogSeedReport:
    report = CatalogSeedReport()
    svc, permissions = _services(settings)
    database = Database(settings.database_config())
    try:
        await _seed_specs(database, svc, admin_phone, editor_phone, report)
        for spec in SHOP_CATALOGS:
            shop_id = await _seed_shop(database, svc, permissions, spec, report)
            if shop_id is not None and spec.rate_age_days:
                await _age_rate(settings, shop_id, spec.rate_age_days)
    finally:
        await database.dispose()
    return report
