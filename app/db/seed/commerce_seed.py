"""Lokal demo savdo (3-modul): qoldiq, kirim, tez sotuv, har holatdagi buyurtmalar, tuzatish so'rovi.

`dev_seed.run_seed` chaqiradi (katalogdan keyin). Hammasi servislar orqali — daftar, band, audit va o'tishlar
jurnali haqiqiydagidek. Keyin "vaqt" surilib qo'yiladi (24 soat tasdiqlanmagan, 72 soat olib ketilmagan) —
faqat shu skriptda, migrator ulanishi orqali. Qayta ishga tushirish xavfsiz: qoldig'i bor shop o'tkazib
yuboriladi.
Xaridorlar — to'qima ism va raqamlar (demo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.dependencies import get_import_stock_results, get_import_stock_source
from app.domains.catalog.domain_manifest import DOMAIN_MANIFEST as CATALOG_MANIFEST
from app.domains.catalog.pricing.schemas import ExchangeRateIn
from app.domains.catalog.products.models.orm import Product, Sku
from app.domains.catalog.providers import CatalogServices, build_catalog_services
from app.domains.catalog.query_port import CatalogQueryPortImpl
from app.domains.commerce.domain_manifest import DOMAIN_MANIFEST as COMMERCE_MANIFEST
from app.domains.commerce.inventory.models.orm import StockBalance
from app.domains.commerce.inventory.schemas import AdjustmentIn, ReceiptIn, ReceiptLineIn
from app.domains.commerce.orders.schemas import OrderCreate, OrderLineIn, OrderNoteIn, OrderOut
from app.domains.commerce.providers import CommerceServices, build_commerce_services
from app.domains.commerce.query_port import StockQueryPortImpl
from app.domains.commerce.quick_sales.schemas import QuickSaleIn, QuickSaleLineIn
from app.domains.storefront.common import PreviewSigner
from app.domains.storefront.site_gate import SiteGate
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.manifest import MODULE_MANIFEST as SHOPS_MANIFEST
from app.platform.shops.models.orm import Branch, Shop
from app.platform.staff.manifest import MODULE_MANIFEST as STAFF_MANIFEST
from app.platform.staff.models.orm import Membership
from app.platform.staff.permissions import PermissionRegistry
from app.platform.storage.config import build_file_storage
from app.platform.storage.services.file_service import FileService
from app.platform.storage.signing import UrlSigner
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.cache import MemoryCache
from app.shared.db.encryption import configure_pii
from app.shared.db.session import Database, set_identity_context
from app.shared.types.actor import ActorContext

# Kirim: SKU kodi → (birinchi filial, ikkinchi filial) dona. 1 — "kam qoldi" ko'rinishi uchun
TECHPC_STOCK: dict[str, tuple[int, ...]] = {
    "TP-GPU-4060": (6, 2),
    "TP-GPU-4070S": (2, 1),
    "TP-CPU-7600-BOX": (5, 3),
    "TP-CPU-7600-TRAY": (1, 0),
    "TP-MB-B650M": (4, 2),
    "TP-RAM-32D5": (8, 4),
    "TP-COOL-AK400": (10, 5),
    "TP-GPU-3060-U": (1, 0),
}
NOUTBUK_STOCK: dict[str, tuple[int, ...]] = {
    "NB-LEN-IPS3-15": (3, 2, 1),
    "NB-ASUS-TUF-A15": (2, 1, 0),
    "NB-HP-250G10": (4, 0, 2),
}


@dataclass
class CommerceSeedReport:
    receipts: int = 0
    quick_sales: int = 0
    orders: int = 0
    skipped_shops: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Ctx:
    shop_id: UUID
    branches: list[UUID]
    skus: dict[str, UUID]
    actors: dict[str, ActorContext]  # OWNER, MANAGER, SALES, WAREHOUSE (borlari)


def _services(settings: Settings) -> tuple[CommerceServices, CatalogServices, PermissionRegistry]:
    manifests = [SHOPS_MANIFEST, STAFF_MANIFEST, CATALOG_MANIFEST, COMMERCE_MANIFEST]
    audit = AuditService()
    files = FileService(
        storage=build_file_storage(settings.storage_config()),
        signer=UrlSigner(settings.jwt_secret.get_secret_value()),
        audit=audit,
        public_base_url=settings.public_files_url,
        signed_ttl=timedelta(seconds=settings.signed_url_ttl_seconds),
    )
    use = UseService(RulesRegistry.from_manifests(manifests), audit)
    catalog = CatalogQueryPortImpl()
    # Seed saytdan buyurtma bermaydi — sayt holati porti faqat imzo uchun kerak
    site = SiteGate(MemoryCache(), PreviewSigner(settings.jwt_secret.get_secret_value()))
    permissions = PermissionRegistry.from_manifests(manifests)
    commerce = build_commerce_services(
        use, audit, files, catalog, StockQueryPortImpl(catalog), site, get_import_stock_source(), permissions
    )
    catalog_services = build_catalog_services(use, audit, files, permissions, get_import_stock_results())
    return commerce, catalog_services, permissions


async def _context(db: AsyncSession, permissions: PermissionRegistry, slug: str) -> _Ctx | None:
    shop = (await db.execute(select(Shop).where(Shop.slug == slug))).scalar_one_or_none()
    if shop is None:
        return None
    await set_identity_context(db, shop_id=shop.id)
    members = (
        await db.execute(
            select(Membership)
            .where(Membership.shop_id == shop.id, Membership.status == "ACTIVE")
            .order_by(Membership.created_at)
        )
    ).scalars()
    actors: dict[str, ActorContext] = {}
    for member in members:
        actors.setdefault(
            member.role,
            ActorContext(
                actor_type="STAFF",
                actor_id=member.principal_id,
                shop_id=shop.id,
                surface="shop",
                roles=frozenset({member.role}),
                permissions=permissions.for_role(member.role),
                membership_id=member.id,
            ),
        )
    branches = list(
        (
            await db.execute(
                select(Branch.id)
                .where(Branch.shop_id == shop.id, Branch.status == "ACTIVE")
                .order_by(Branch.created_at)
            )
        ).scalars()
    )
    skus = {
        code: sku_id
        for code, sku_id in (
            await db.execute(
                select(Sku.sku_code, Sku.id)
                .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
                .where(Sku.shop_id == shop.id)
            )
        )
    }
    if "OWNER" not in actors or not branches:
        return None
    return _Ctx(shop.id, branches, skus, actors)


async def _has_stock(db: AsyncSession, shop_id: UUID) -> bool:
    count = (
        await db.execute(
            select(func.count()).select_from(StockBalance).where(StockBalance.shop_id == shop_id)
        )
    ).scalar_one()
    return bool(count)


async def _receive(
    db: AsyncSession,
    svc: CommerceServices,
    ctx: _Ctx,
    stock: dict[str, tuple[int, ...]],
    report: CommerceSeedReport,
) -> None:
    actor = ctx.actors.get("WAREHOUSE", ctx.actors["OWNER"])
    for index, branch_id in enumerate(ctx.branches):
        lines = [
            ReceiptLineIn(sku_id=ctx.skus[code], qty=qty[index])
            for code, qty in stock.items()
            if code in ctx.skus and index < len(qty) and qty[index] > 0
        ]
        if lines:
            await svc.stock.create_receipt(
                db, actor, ReceiptIn(branch_id=branch_id, note="Boshlang'ich qoldiq (demo)", lines=lines)
            )
            report.receipts += 1


async def _order(
    db: AsyncSession,
    svc: CommerceServices,
    actor: ActorContext,
    ctx: _Ctx,
    name: str,
    phone: str,
    lines: dict[str, int],
    *,
    branch: int = 0,
    delivery: str | None = None,
    comment: str | None = None,
) -> OrderOut:
    return await svc.orders.create(
        db,
        actor,
        OrderCreate(
            customer_name=name,
            customer_phone=phone,
            branch_id=ctx.branches[branch],
            fulfillment_method="DELIVERY" if delivery else "PICKUP",
            delivery_address=delivery,
            customer_comment=comment,
            lines=[OrderLineIn(sku_id=ctx.skus[code], qty=qty) for code, qty in lines.items()],
        ),
    )


async def _step(
    db: AsyncSession, svc: CommerceServices, actor: ActorContext, order: OrderOut, *steps: str
) -> OrderOut:
    for step in steps:
        method = getattr(svc.lifecycle, step)
        order = await method(db, actor, order.id, order.version)
    return order


async def _seed_techpc(
    db: AsyncSession, svc: CommerceServices, catalog: CatalogServices, ctx: _Ctx, report: CommerceSeedReport
) -> dict[str, list[UUID]]:
    """TechPC: har holatdagi buyurtma. Qaytaradi — keyin vaqti suriladigan buyurtmalar."""
    await _receive(db, svc, ctx, TECHPC_STOCK, report)
    owner = ctx.actors["OWNER"]
    sales = ctx.actors.get("SALES", owner)
    warehouse = ctx.actors.get("WAREHOUSE", owner)
    for actor, code in ((warehouse, "TP-COOL-AK400"), (sales, "TP-RAM-32D5")):
        await svc.quick_sales.create(
            db,
            actor,
            QuickSaleIn(branch_id=ctx.branches[0], lines=[QuickSaleLineIn(sku_id=ctx.skus[code], qty=1)]),
        )
        report.quick_sales += 1

    draft = await _order(db, svc, sales, ctx, "Jasur Tursunov", "+998901234567", {"TP-GPU-4060": 1})
    await svc.orders.add_note(
        db, sales, draft.id, OrderNoteIn(kind="CALL_RESULT", body="Qo'ng'iroq qildim — ertaga javob beradi.")
    )
    stale = await _order(db, svc, sales, ctx, "Malika Rahimova", "+998935557788", {"TP-MB-B650M": 1})
    stale = await _step(db, svc, sales, stale, "submit")
    discount = await _order(db, svc, sales, ctx, "Sardor Aliyev", "+998977001122", {"TP-RAM-32D5": 2})
    line = discount.lines[0]
    discount = await svc.orders.set_discount(db, sales, discount.id, line.id, discount.version, Decimal("8"))
    discount = await _step(db, svc, sales, discount, "submit")
    delivery = await _order(
        db,
        svc,
        sales,
        ctx,
        "Nodir Qodirov",
        "+998909998877",
        {"TP-COOL-AK400": 1, "TP-RAM-32D5": 1},
        delivery="Toshkent, Mirzo Ulug'bek, Buyuk Ipak Yo'li 15, 3-xonadon",
        comment="Kechqurun 18:00 dan keyin qo'ng'iroq qiling",
    )
    delivery = await _step(db, svc, sales, delivery, "submit")
    usd = await _order(db, svc, sales, ctx, "Aziz Karimov", "+998946663322", {"TP-CPU-7600-BOX": 1})
    usd = await _step(db, svc, sales, usd, "submit")

    confirmed = await _order(db, svc, sales, ctx, "Bekzod Ergashev", "+998901112299", {"TP-GPU-4060": 1})
    confirmed = await _step(db, svc, sales, confirmed, "submit", "confirm")
    overdue = await _order(db, svc, sales, ctx, "Dilnoza Saidova", "+998935551100", {"TP-GPU-4070S": 1})
    overdue = await _step(db, svc, sales, overdue, "submit", "confirm")
    ready = await _order(db, svc, sales, ctx, "Otabek Nazarov", "+998998887766", {"TP-CPU-7600-BOX": 1})
    ready = await _step(db, svc, sales, ready, "submit", "confirm")
    ready = await _step(db, svc, warehouse, ready, "start_processing", "mark_ready")
    done = await _order(db, svc, sales, ctx, "Kamola Yusupova", "+998901230000", {"TP-COOL-AK400": 2})
    done = await _step(db, svc, sales, done, "submit", "confirm")
    done = await _step(db, svc, warehouse, done, "start_processing")
    done = await _step(db, svc, sales, done, "complete")
    await svc.orders.paid_mark(db, sales, done.id, "CASH")
    cancelled = await _order(db, svc, sales, ctx, "Rustam Jo'rayev", "+998931234321", {"TP-GPU-3060-U": 1})
    cancelled = await _step(db, svc, sales, cancelled, "submit")
    await svc.lifecycle.cancel(db, owner, cancelled.id, cancelled.version, "Xaridor boshqa do'kondan oldi")
    problem = await _order(db, svc, sales, ctx, "Farrux Olimov", "+998977776655", {"TP-MB-B650M": 1})
    problem = await _step(db, svc, sales, problem, "submit", "confirm")
    problem = await _step(db, svc, warehouse, problem, "start_processing")
    await svc.lifecycle.raise_exception(
        db,
        warehouse,
        problem.id,
        problem.version,
        "Qutisi ochilgan holda keldi — xaridor bilan kelishish kerak",
    )
    report.orders += 10

    # Tuzatish: omborchi so'raydi (ega tasdiqlashi kerak); ega o'zi "sotilmaydi" deb belgilaydi
    await svc.stock.create_adjustment(
        db,
        warehouse,
        AdjustmentIn(
            branch_id=ctx.branches[0],
            sku_id=ctx.skus["TP-GPU-4060"],
            delta=-1,
            reason="Sanoqda 1 ta kam chiqdi",
        ),
    )
    await svc.stock.create_adjustment(
        db,
        owner,
        AdjustmentIn(
            branch_id=ctx.branches[0],
            sku_id=ctx.skus["TP-RAM-32D5"],
            kind="QUARANTINE_IN",
            delta=1,
            reason="Qutisi ezilgan — tekshiruvga",
        ),
    )
    # Kurs yangilandi: dollar narxli, tasdiq kutayotgan buyurtma endi "narx o'zgardi" bo'ladi (DEC-134)
    await catalog.pricing.add_rate(db, owner, ExchangeRateIn(rate=Decimal("12900")))
    return {"unconfirmed": [stale.id], "overdue": [overdue.id]}


async def _seed_noutbuk(
    db: AsyncSession, svc: CommerceServices, ctx: _Ctx, report: CommerceSeedReport
) -> None:
    await _receive(db, svc, ctx, NOUTBUK_STOCK, report)
    manager = ctx.actors.get("MANAGER", ctx.actors["OWNER"])
    sales = ctx.actors.get("SALES", manager)
    warehouse = ctx.actors.get("WAREHOUSE", manager)
    await svc.quick_sales.create(
        db,
        warehouse,
        QuickSaleIn(
            branch_id=ctx.branches[0], lines=[QuickSaleLineIn(sku_id=ctx.skus["NB-HP-250G10"], qty=1)]
        ),
    )
    report.quick_sales += 1
    pending = await _order(db, svc, sales, ctx, "Shahzod Mirzayev", "+998903332211", {"NB-LEN-IPS3-15": 1})
    await _step(db, svc, sales, pending, "submit")
    confirmed = await _order(
        db, svc, sales, ctx, "Gulnora Ismoilova", "+998977009988", {"NB-ASUS-TUF-A15": 1}
    )
    confirmed = await _step(db, svc, sales, confirmed, "submit")
    await _step(db, svc, manager, confirmed, "confirm")  # menejer — o'ziga biriktirilmagan bo'lsa ham
    report.orders += 2


async def _backdate(settings: Settings, shop_id: UUID, marks: dict[str, list[UUID]]) -> None:
    """24 soatdan beri tasdiqlanmagan va 72 soatdan beri olib ketilmagan buyurtmalar (DEC-104, DEC-134)."""
    url = settings.database_migrator_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.shop_id', $1, true)", str(shop_id))  # FORCE RLS
            for order_id in marks.get("unconfirmed", []):
                await conn.execute(
                    "UPDATE commerce.orders SET submitted_at = now() - interval '30 hours', "
                    "created_at = now() - interval '31 hours' WHERE id = $1",
                    order_id,
                )
            for order_id in marks.get("overdue", []):
                await conn.execute(
                    "UPDATE commerce.orders SET confirmed_at = now() - interval '4 days', "
                    "submitted_at = now() - interval '4 days 2 hours', "
                    "created_at = now() - interval '4 days 3 hours' "
                    "WHERE id = $1",
                    order_id,
                )
                await conn.execute(
                    "UPDATE commerce.reservations SET review_at = now() - interval '1 day' "
                    "WHERE order_id = $1",
                    order_id,
                )
    finally:
        await conn.close()


async def run_commerce_seed(settings: Settings) -> CommerceSeedReport:
    configure_pii(settings.pii_keyring())  # xaridor telefoni va manzili shifrlanadi
    report = CommerceSeedReport()
    svc, catalog, permissions = _services(settings)
    database = Database(settings.database_config())
    try:
        for slug in ("techpc", "noutbukuz"):
            marks: dict[str, list[UUID]] = {}
            async with database.transaction() as db:
                ctx = await _context(db, permissions, slug)
                if ctx is None or await _has_stock(db, ctx.shop_id):
                    report.skipped_shops.append(slug)
                    continue
                if slug == "techpc":
                    marks = await _seed_techpc(db, svc, catalog, ctx, report)
                else:
                    await _seed_noutbuk(db, svc, ctx, report)
            if marks:
                await _backdate(settings, ctx.shop_id, marks)
    finally:
        await database.dispose()
    return report
