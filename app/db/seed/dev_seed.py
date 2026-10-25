"""Lokal demo ma'lumotlari: platforma jamoasi, turli holatdagi 8 ta shop va katalog (23 §3).

    make seed          # yoki: uv run python -m app.db.seed.dev_seed

Ma'lumotlar servislar orqali yaratiladi — audit, o'tishlar jurnali va havolalar haqiqiydagidek.
Keyin sanalar "orqaga suriladi" (pilot kunlari, tekshiruv kutish vaqti, eskirgan havola) — faqat shu skriptda,
migrator ulanishi orqali (jurnal jadvallarini ilova roli o'zgartira olmaydi).

Qayta ishga tushirish xavfsiz: slug'i bor shop va telefoni bor odam o'tkazib yuboriladi. Faqat lokal
va sinov bazalari uchun: haqiqiy ma'lumot hech qachon shu yo'l bilan yuklanmaydi.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.seed.catalog_seed import run_catalog_seed
from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.passwords import PasswordHasher
from app.platform.auth.services.auth_service import AuthService
from app.platform.shops.manifest import MODULE_MANIFEST as SHOPS_MANIFEST
from app.platform.shops.models.orm import Branch, Shop, ShopNote
from app.platform.shops.platform_schemas import ShopNoteIn
from app.platform.shops.schemas import BranchIn, ShopCreateIn
from app.platform.shops.services.shop_service import ShopService
from app.platform.staff.cli import create_platform_admin
from app.platform.staff.manifest import MODULE_MANIFEST as STAFF_MANIFEST
from app.platform.staff.models.orm import Membership, PlatformStaff, Principal
from app.platform.staff.permissions import PLATFORM_ROLE_PERMISSIONS, PermissionRegistry
from app.platform.staff.platform_schemas import PlatformInviteIn, PlatformRole
from app.platform.staff.schemas import InviteIn, Role
from app.platform.staff.services.platform_team_service import PlatformTeamService
from app.platform.staff.services.staff_service import StaffService
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.db.session import Database, set_identity_context
from app.shared.types.actor import ActorContext

ADMIN_PHONE, ADMIN_PASSWORD = "+998900000001", "Admin-Local-2026"
OWNER_PASSWORD = "Demo-Ega-2026"  # noqa: S105 — faqat lokal demo
STAFF_PASSWORD = "Demo-Xodim-2026"  # noqa: S105 — faqat lokal demo
USER_AGENT = "dev-seed"
WORKING_HOURS = {day: [["10:00", "20:00"]] for day in ("mon", "tue", "wed", "thu", "fri", "sat")}


@dataclass(frozen=True)
class TeamSeed:
    full_name: str
    phone: str
    role: PlatformRole
    password: str | None  # None — taklif qilingan, hali kirmagan


@dataclass(frozen=True)
class ShopSeed:
    slug: str
    name: str
    tin: str
    owner_name: str
    owner_phone: str
    state: str  # PENDING | ACTIVE | SUSPENDED | DRAFT_EXPIRING | DRAFT_EXPIRED
    created_days_ago: int
    waiting_days: int = 0  # PENDING: tekshiruvga yuborilganiga necha kun
    active_days: int = 0  # ACTIVE/SUSPENDED: faollashtirilganiga necha kun
    branches: tuple[tuple[str, str], ...] = ()
    staff: tuple[tuple[str, str, Role], ...] = ()
    notes: tuple[str, ...] = ()
    suspend_reason: str = "to'lov kelishuvi"


TEAM = (
    TeamSeed("Dilnoza Support", "+998900000002", "PLATFORM_SUPPORT", "Demo-Support-2026"),
    TeamSeed("Bekzod Kutubxona", "+998900000003", "SPEC_EDITOR", None),
    # Kutubxonaga admin kiritgan modellarni shu odam tasdiqlaydi ("ikki ko'z", engineering/17 §10)
    TeamSeed("Sardor Kutubxona", "+998900000004", "SPEC_EDITOR", "Demo-Kutubxona-2026"),
)

SHOPS = (
    ShopSeed(
        "techpc",
        "TechPC",
        "305123456",
        "Ali Valiyev",
        "+998901112233",
        "PENDING",
        5,
        waiting_days=3,
        branches=(
            ("Chilonzor", "Toshkent, Chilonzor 9-kvartal, 12"),
            ("Yunusobod", "Toshkent, Yunusobod 4-mavze, 7"),
        ),
        staff=(("Vali Operator", "+998901112234", "SALES"), ("Olim Omborchi", "+998901112235", "WAREHOUSE")),
        notes=(
            "Kelishuv imzolangan, pilot 1-noyabrdan.",
            "Aloqa uchun: Ali aka, kechqurun qo'ng'iroq qilgan ma'qul.",
        ),
    ),
    ShopSeed(
        "megacomp",
        "MegaComp",
        "305884120",
        "Bobur Rahimov",
        "+998901112240",
        "PENDING",
        2,
        waiting_days=1,
        branches=(("Sergeli", "Toshkent, Sergeli 6-mavze, 21"),),
        staff=(("Malika Menejer", "+998901112241", "MANAGER"),),
    ),
    ShopSeed(
        "noutbukuz",
        "NoutbukUz",
        "302778014",
        "Dilshod Karimov",
        "+998901112250",
        "ACTIVE",
        30,
        active_days=26,
        branches=(
            ("Chilonzor", "Toshkent, Chilonzor 19-kvartal, 3"),
            ("Yunusobod", "Toshkent, Amir Temur 108"),
            ("Samarqand darvoza", "Toshkent, Qatortol 60"),
        ),
        staff=(
            ("Jasur Menejer", "+998901112251", "MANAGER"),
            ("Sherzod Operator", "+998901112252", "SALES"),
            ("Kamol Omborchi", "+998901112253", "WAREHOUSE"),
        ),
        notes=("Pilot tugashiga oz qoldi — natijalar hisobotini tayyorlash kerak.",),
    ),
    ShopSeed(
        "kompyuterpro",
        "KompyuterPro",
        "303150992",
        "Nodira Saidova",
        "+998901112260",
        "ACTIVE",
        15,
        active_days=12,
        branches=(("Mirobod", "Toshkent, Mirobod, Taras Shevchenko 22"), ("Olmazor", "Toshkent, Olmazor 41")),
        staff=(
            ("Aziza Operator", "+998901112261", "SALES"),
            ("Rustam Omborchi", "+998901112262", "WAREHOUSE"),
        ),
    ),
    ShopSeed(
        "hitech-samarqand",
        "Hi-Tech Samarqand",
        "304662301",
        "Rustam Qodirov",
        "+998901112270",
        "ACTIVE",
        8,
        active_days=5,
        branches=(("Samarqand markaz", "Samarqand, Registon ko'chasi 5"),),
        staff=(("Farrux Operator", "+998901112271", "SALES"),),
    ),
    ShopSeed("gamezone", "GameZone", "307245510", "Sardor Aliyev", "+998901112280", "DRAFT_EXPIRING", 3),
    ShopSeed("pc-market", "PC Market", "306001477", "Jamshid Tursunov", "+998901112290", "DRAFT_EXPIRED", 6),
    ShopSeed(
        "byteshop",
        "ByteShop",
        "301009845",
        "Laylo Ergasheva",
        "+998901112300",
        "SUSPENDED",
        25,
        active_days=20,
        branches=(("Yakkasaroy", "Toshkent, Yakkasaroy, Shota Rustaveli 14"),),
        staff=(("Bekzod Operator", "+998901112301", "SALES"),),
        notes=("To'xtatildi: to'lov bo'yicha kelishuv kutilmoqda.",),
    ),
)


@dataclass
class SeedReport:
    created_shops: list[str] = field(default_factory=list)
    skipped_shops: list[str] = field(default_factory=list)
    created_team: list[str] = field(default_factory=list)
    catalog_products: int = 0
    catalog_specs: int = 0


@dataclass(frozen=True)
class _Services:
    auth: AuthService
    shops: ShopService
    staff: StaffService
    team: PlatformTeamService
    permissions: PermissionRegistry


def _services(settings: Settings) -> _Services:
    config = settings.auth_config()
    audit = AuditService()
    use = UseService(RulesRegistry.from_manifests([SHOPS_MANIFEST, STAFF_MANIFEST]), audit)
    hasher = PasswordHasher(config.argon2_time_cost, config.argon2_memory_kib, config.argon2_parallelism)
    staff = StaffService(use, audit, config)
    return _Services(
        auth=AuthService(config, hasher, audit, use),
        shops=ShopService(use, audit, config, staff),
        staff=staff,
        team=PlatformTeamService(audit, config),
        permissions=PermissionRegistry.from_manifests([SHOPS_MANIFEST, STAFF_MANIFEST]),
    )


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


async def _phone_exists(db: AsyncSession, phone: str) -> bool:
    return (await db.execute(select(Principal.id).where(Principal.phone == phone))).first() is not None


async def _admin_actor(db: AsyncSession) -> ActorContext:
    staff, principal = (
        await db.execute(
            select(PlatformStaff, Principal)
            .join(Principal, Principal.id == PlatformStaff.principal_id)
            .where(Principal.phone == ADMIN_PHONE)
        )
    ).one()
    await set_identity_context(db, principal_id=principal.id)
    return ActorContext(
        actor_type="PLATFORM",
        actor_id=principal.id,
        shop_id=None,
        surface="platform",
        roles=frozenset({staff.role}),
        permissions=PLATFORM_ROLE_PERMISSIONS.get(staff.role, frozenset()),
    )


async def _owner_actor(db: AsyncSession, svc: _Services, shop_id: UUID) -> ActorContext | None:
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
        permissions=svc.permissions.for_role("OWNER"),
        membership_id=owner.id,
    )


async def _seed_team(database: Database, svc: _Services, report: SeedReport) -> None:
    for member in TEAM:
        async with database.transaction() as db:
            if await _phone_exists(db, member.phone):
                continue
            admin = await _admin_actor(db)
            invited = await svc.team.invite(
                db, admin, PlatformInviteIn(phone=member.phone, full_name=member.full_name, role=member.role)
            )
            if member.password:
                await svc.auth.accept_platform_invite(
                    db, _token(invited.invite.url), member.password, USER_AGENT
                )
            report.created_team.append(member.full_name)


async def _fill_shop(db: AsyncSession, svc: _Services, shop_id: UUID, spec: ShopSeed) -> bool:
    """Ega nomidan: filiallar, xodimlar, tekshiruvga yuborish. Bor narsa takrorlanmaydi. True — yuborildi."""
    owner = await _owner_actor(db, svc, shop_id)
    if owner is None:
        return False
    branch_count = (
        await db.execute(select(func.count()).select_from(Branch).where(Branch.shop_id == shop_id))
    ).scalar_one()
    if branch_count == 0:
        for name, address in spec.branches:
            await svc.shops.create_branch(
                db, owner, BranchIn(name=name, address=address, working_hours=WORKING_HOURS)
            )
    member_count = (
        await db.execute(select(func.count()).select_from(Membership).where(Membership.shop_id == shop_id))
    ).scalar_one()
    if member_count <= 1:
        for full_name, phone, role in spec.staff:
            if await _phone_exists(db, phone):
                continue
            invited = await svc.staff.invite(db, owner, InviteIn(phone=phone, full_name=full_name, role=role))
            await svc.auth.accept_invite(db, _token(invited.invite.url), STAFF_PASSWORD, USER_AGENT)
            owner = await _owner_actor(db, svc, shop_id)  # qabul qilish kontekstni o'zgartiradi
            assert owner is not None
    shop = await db.get(Shop, shop_id)
    assert shop is not None
    if shop.status == "DRAFT" and spec.state in ("PENDING", "ACTIVE", "SUSPENDED"):
        await svc.shops.submit_for_verification(db, owner)
        return True
    return False


async def _add_notes(db: AsyncSession, svc: _Services, shop_id: UUID, notes: tuple[str, ...]) -> None:
    existing = (
        await db.execute(select(func.count()).select_from(ShopNote).where(ShopNote.shop_id == shop_id))
    ).scalar_one()
    if existing:
        return
    admin = await _admin_actor(db)
    for body in notes:
        await svc.shops.add_note(db, admin, shop_id, ShopNoteIn(body=body))


@dataclass(frozen=True)
class _ShopResult:
    shop_id: UUID
    created: bool  # shu yugurishda yaratildi
    submitted: bool  # shu yugurishda tekshiruvga yuborildi


async def _seed_shop(database: Database, svc: _Services, spec: ShopSeed) -> _ShopResult | None:
    """Shopni yaratadi (techpc bo'lsa — mavjudini to'ldiradi). Slug'i bor boshqa shop — None."""
    async with database.transaction() as db:
        existing = (await db.execute(select(Shop).where(Shop.slug == spec.slug))).scalar_one_or_none()
        if existing is not None and spec.slug != "techpc":
            return None
        admin = await _admin_actor(db)
        if existing is None:
            created = await svc.shops.create_shop(
                db,
                admin,
                ShopCreateIn(
                    slug=spec.slug,
                    name=spec.name,
                    legal_name=f"{spec.name} MCHJ",
                    tin=spec.tin,
                    owner_phone=spec.owner_phone,
                    owner_full_name=spec.owner_name,
                ),
            )
            shop_id = created.shop.id
            if not spec.state.startswith("DRAFT"):
                await svc.auth.accept_invite(db, _token(created.owner_invite.url), OWNER_PASSWORD, USER_AGENT)
        else:
            shop_id = existing.id
        submitted = await _fill_shop(db, svc, shop_id, spec)
        admin = await _admin_actor(db)
        if submitted and spec.state in ("ACTIVE", "SUSPENDED"):
            await svc.shops.platform_transition(db, admin, shop_id, "ACTIVATE", None)
            if spec.state == "SUSPENDED":
                await svc.shops.platform_transition(db, admin, shop_id, "SUSPEND", spec.suspend_reason)
        await _add_notes(db, svc, shop_id, spec.notes)
        return _ShopResult(shop_id, created=existing is None, submitted=submitted)


_SET_CREATED = "UPDATE platform.shops SET created_at = $2 WHERE id = $1"
_SET_ACTIVATED = "UPDATE platform.shops SET activated_at = $2 WHERE id = $1"
_MOVE_TRANSITION = "UPDATE platform.transition_log SET occurred_at = $3 WHERE entity_id = $1 AND command = $2"
_MOVE_AUDIT = "UPDATE audit.audit_entries SET occurred_at = $3 WHERE entity_id = $1 AND action = $2"
_MOVE_INVITE = (
    "UPDATE platform.invitations SET created_at = $2, expires_at = $3"
    " WHERE shop_id = $1 AND accepted_at IS NULL"
)


async def _backdate(settings: Settings, spec: ShopSeed, result: _ShopResult) -> None:
    """Sanalarni orqaga surish — pilot kunlari, kutish vaqti va havola muddati ko'rinishi uchun."""
    now = utcnow()
    shop_id = result.shop_id

    def ago(days: float) -> datetime:
        return now - timedelta(days=days)

    url = settings.database_migrator_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            if result.created:
                await conn.execute(_SET_CREATED, shop_id, ago(spec.created_days_ago))
                await conn.execute(_MOVE_AUDIT, shop_id, "shops.shop.created", ago(spec.created_days_ago))
                if spec.state == "DRAFT_EXPIRING":  # taklif 66 soat oldin berilgan, 6 soat qoldi
                    await conn.execute(
                        _MOVE_INVITE, shop_id, now - timedelta(hours=66), now + timedelta(hours=6)
                    )
                if spec.state == "DRAFT_EXPIRED":
                    await conn.execute(_MOVE_INVITE, shop_id, ago(4), ago(1))
            if not result.submitted:
                return
            moves = {
                "SUBMIT_FOR_VERIFICATION": spec.waiting_days
                if spec.state == "PENDING"
                else spec.active_days + 1
            }
            if spec.state in ("ACTIVE", "SUSPENDED"):
                moves["ACTIVATE"] = spec.active_days
                await conn.execute(_SET_ACTIVATED, shop_id, ago(spec.active_days))
            if spec.state == "SUSPENDED":
                moves["SUSPEND"] = 2
            for command, days in moves.items():
                await conn.execute(_MOVE_TRANSITION, shop_id, command, ago(days))
                await conn.execute(_MOVE_AUDIT, shop_id, f"shops.shop.{command.lower()}", ago(days))
    finally:
        await conn.close()


async def run_seed(settings: Settings) -> SeedReport:
    report = SeedReport()
    database = Database(settings.database_config())
    try:
        async with database.transaction() as db:
            admin_missing = not await _phone_exists(db, ADMIN_PHONE)
        if admin_missing:
            await create_platform_admin(
                settings, ADMIN_PHONE, "Platforma Admin", ADMIN_PASSWORD, "PLATFORM_ADMIN"
            )
            report.created_team.append("Platforma Admin")
        svc = _services(settings)
        await _seed_team(database, svc, report)
        for spec in SHOPS:
            result = await _seed_shop(database, svc, spec)
            if result is None:
                report.skipped_shops.append(spec.slug)
                continue
            if result.created or result.submitted:
                await _backdate(settings, spec, result)
                report.created_shops.append(spec.slug)
            else:
                report.skipped_shops.append(spec.slug)
    finally:
        await database.dispose()
    catalog = await run_catalog_seed(settings, ADMIN_PHONE, TEAM[2].phone)
    report.catalog_products, report.catalog_specs = catalog.products, catalog.specs
    return report


def main() -> None:
    report = asyncio.run(run_seed(Settings()))
    lines = [
        f"Yaratildi: shoplar {len(report.created_shops)}, jamoa {len(report.created_team)}, "
        f"katalog: mahsulotlar {report.catalog_products}, kutubxona modellari {report.catalog_specs}; "
        f"o'tkazib yuborildi: {len(report.skipped_shops)}",
        "",
        "Platforma paneli (http://localhost:3001):",
        f"  admin   {ADMIN_PHONE} / {ADMIN_PASSWORD}",
        f"  support {TEAM[0].phone} / {TEAM[0].password}",
        f"  kutubxona muharriri {TEAM[2].phone} / {TEAM[2].password}",
        "Shop paneli (http://localhost:3000) — egalar paroli: "
        + OWNER_PASSWORD
        + ", xodimlar: "
        + STAFF_PASSWORD,
    ]
    lines += [
        f"  {s.name:<18} {s.owner_phone}  ({s.state})" for s in SHOPS if not s.state.startswith("DRAFT")
    ]
    print("\n".join(lines))  # noqa: T201 — CLI chiqishi


if __name__ == "__main__":
    main()
