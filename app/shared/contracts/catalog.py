"""CatalogQueryPort — boshqa domenlar (commerce, sales_ai) katalogdan narx va SKU'ni shu orqali o'qiydi.

Buyurtma qoralamasida narx nusxasi olinadi, tasdiqlashda esa joriy narx shu port orqali sinxron, keshsiz
o'qilib solishtiriladi (12 §5.1, DEC-127, DEC-134). `catalog` kodini import qilish — TAQIQ (ADR-032).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.contracts.compatibility import BuildLine, CompatibilityResult
from app.shared.money import Currency
from app.shared.types.actor import ActorContext


@dataclass(frozen=True)
class SkuSnapshot:
    sku_id: UUID
    product_id: UUID
    title: str  # mahsulot nomi + variant: "MSI GeForce RTX 4060 Ventus 2X · 8 GB"
    sku_code: str
    sellable: bool  # mahsulot saytda chiqarilgan va SKU faol
    product_status: str  # DRAFT | PUBLISHED | HIDDEN | ARCHIVED (FSM-02)
    sku_status: str  # ACTIVE | ARCHIVED
    warranty_months: int | None
    price_version_id: UUID | None
    amount_minor: int | None
    currency: Currency | None
    exchange_rate_id: UUID | None  # dollar narxi bo'lsa — qaysi kurs bilan o'girildi
    exchange_rate: Decimal | None
    exchange_rate_effective_at: datetime | None
    exchange_rate_stale: bool  # dollar narxi va kurs 3 kundan eski — yakuniy narx berilmaydi (BL-018)
    uzs_amount_minor: int | None  # xaridor ko'radigan narx (tiyinda), yaxlitlanmaydi (DEC-133)
    product_title: str = ""  # tanlash ro'yxati uchun nom va variant alohida
    variant_name: str | None = None


@dataclass(frozen=True)
class NetworkSkuFacts:
    """Stage 2 `network`: ommaviy taklif proyeksiyasi uchun ruxsat etilgan maydonlar. Tannarx, ichki izoh,
    xodim yo'q (BL-081)."""

    sku_id: UUID
    product_id: UUID
    title: str
    brand: str | None
    category_code: str
    mpn_norm: str | None
    condition: str  # NEW | USED | REFURBISHED
    warranty_months: int | None
    sellable: bool  # mahsulot chiqarilgan va SKU faol
    amount_minor: int | None
    currency: Currency | None
    uzs_amount_minor: int | None  # kursi yo'q dollar narxi — None (ko'rsatilmaydi)


@dataclass(frozen=True)
class SkuReportDim:
    """Hisobot o'lchami (7c): SKU nomi, toifasi va joriy narxi so'mda. Shaxsiy ma'lumot yo'q."""

    sku_id: UUID
    product_id: UUID
    title: str
    sku_code: str
    category_code: str
    category_name: str
    price_uzs_minor: int | None  # narxi yo'q yoki dollar kursi yo'q bo'lsa — None


@dataclass(frozen=True)
class RateSnapshot:
    """Shopning joriy dollar kursi (kuchga kirgan eng oxirgisi)."""

    rate_id: UUID
    rate: Decimal  # 1 dollar = necha so'm
    effective_at: datetime
    stale: bool  # 3 kundan eski (BL-018)


# ------------------------------------------------------------------ sayt (4-modul): faqat ommaviy maydonlar
# Tannarx, MPN, model nomi, ichki izoh, xodim — bu tiplarda umuman yo'q (TC-SEC-09). Faqat saytda chiqarilgan
# mahsulotning faol va narxi bor variantlari; kursi yo'q dollar narxi ko'rsatilmaydi (BL-012).

PublicSort = Literal["newest", "price_asc", "price_desc"]


@dataclass(frozen=True)
class PublicCategory:
    code: str
    parent_code: str | None
    name_uz: str
    name_ru: str
    name_en: str
    position: int
    product_count: int  # shu toifaning o'zida (bolalarisiz) ko'rinadigan mahsulotlar


@dataclass(frozen=True)
class PublicVariant:
    sku_id: UUID
    variant_name: str | None
    condition: str  # NEW | USED | REFURBISHED
    warranty_months: int | None
    attributes: dict[str, Any]
    price_uzs_minor: int


@dataclass(frozen=True)
class PublicProductCard:
    product_id: UUID
    title: str
    brand: str | None
    category_code: str
    published_at: datetime | None
    price_from_uzs_minor: int
    variant_count: int
    image_file_id: UUID | None
    sku_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class PublicProductPage:
    items: tuple[PublicProductCard, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class PublicProductDetail:
    product_id: UUID
    title: str
    brand: str | None
    description: str | None
    category_code: str
    published_at: datetime | None
    image_file_ids: tuple[UUID, ...]
    variants: tuple[PublicVariant, ...]


class CatalogQueryPort(Protocol):
    async def get_skus(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuSnapshot]:
        """Shu shopning SKU'lari joriy narx bilan. Boshqa shopniki yoki yo'q SKU natijada bo'lmaydi."""
        ...

    async def sku_report_dims(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuReportDim]:
        """Hisobot uchun SKU nomi, toifasi (kod + nomi) va joriy narxi. Boshqa shop SKU'si natijada yo'q."""
        ...

    async def network_facts(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, NetworkSkuFacts]:
        """Stage 2: ommaviy taklif uchun SKU faktlari (shu shopniki, boshqasi natijada yo'q)."""
        ...

    async def count_active_skus(self, db: AsyncSession, shop_id: UUID) -> int:
        """M26 tarif limiti: arxivda bo'lmagan SKU'lar soni."""
        ...

    async def current_rate(self, db: AsyncSession, shop_id: UUID) -> RateSnapshot | None:
        """Shopning joriy dollar kursi; kurs hali kiritilmagan bo'lsa — None."""
        ...

    async def search_sku_ids(
        self, db: AsyncSession, shop_id: UUID, q: str, limit: int, *, sellable_only: bool = False
    ) -> list[UUID]:
        """Matn bo'yicha SKU'lar (nom, brend, SKU kodi, MPN). `sellable_only` — faqat chiqarilgan va faol
        (limit filtrdan keyin, F-34)."""
        ...

    async def pick_sku_ids(self, db: AsyncSession, shop_id: UUID, q: str | None, limit: int) -> list[UUID]:
        """Tanlash ro'yxati (buyurtma qatori, tez sotuv): arxivda bo'lmagan SKU'lar, matn bo'lsa — mos
        kelganlari, bo'lmasa — eng yangilari."""
        ...

    async def sku_spec_categories(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, str | None]:
        """SKU → toifasining PC roli (`categories.spec_category`: CPU, GPU, …); PC qismi emas — None.
        Boshqa shop SKU'si natijada bo'lmaydi."""
        ...

    async def candidate_sku_ids(
        self, db: AsyncSession, shop_id: UUID, spec_category: str, q: str | None, limit: int
    ) -> list[UUID]:
        """PC yig'ish sahifasi: shu roldagi sotiladigan SKU'lar (chiqarilgan mahsulot, faol SKU) — matn bo'lsa
        mos kelganlari, arzonidan boshlab emas, nomi bo'yicha (narx va moslik — chaqiruvchida)."""
        ...

    async def spec_attributes(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        """Bog'langan (tasdiqlangan yoki eski) spec atributlari SKU bo'yicha; bog'lanmagani — yo'q.
        PC yig'ish nomzodlarini engine'dan oldin arzon saralash uchun (QA 6a F6)."""
        ...

    async def check_compatibility(
        self,
        db: AsyncSession,
        shop_id: UUID,
        lines: Sequence[BuildLine],
        locale: Literal["uz", "ru", "en"] = "uz",
        *,
        full_build: bool = True,
    ) -> CompatibilityResult:
        """PC moslik tekshiruvi (engineering/17 §7): deterministik qoidalar, natijani chaqiruvchi saqlaydi.
        Shop SKU'si bo'lmagan qator — ValidationError (`lines[i].sku_id`).
        PC qismi bo'lmaganlar — `ignored_sku_ids`."""
        ...

    # ------------------------------------------------------------------ sayt (ommaviy)
    async def public_categories(self, db: AsyncSession, shop_id: UUID) -> list[PublicCategory]:
        """Saytda ko'rinadigan mahsuloti bor toifalar va ularning ota toifalari (menyu uchun)."""
        ...

    async def public_products(
        self,
        db: AsyncSession,
        shop_id: UUID,
        *,
        category_codes: Sequence[str] | None,
        q: str | None,
        sort: PublicSort,
        limit: int,
        cursor: str | None,
    ) -> PublicProductPage:
        """Saytdagi katalog: faqat ko'rinadigan mahsulotlar, eng arzon variant narxi bilan."""
        ...

    async def public_product(
        self, db: AsyncSession, shop_id: UUID, product_id: UUID
    ) -> PublicProductDetail | None:
        """Mahsulot sahifasi. Ko'rinmaydigan (chiqarilmagan, yashirilgan, narxsiz) — None."""
        ...

    async def public_live_variants(
        self, db: AsyncSession, shop_id: UUID, product_id: UUID
    ) -> dict[UUID, int]:
        """Arzon qayta tekshiruv har so'rovda: hozir ko'rinadigan variantlar → joriy so'm narxi (tiyinda).
        Bo'sh — mahsulot ko'rinmaydi. Kesh bor bo'lsa ham yashirilgan mahsulot, arxivlangan variant va
        o'zgargan narx darhol ko'rinadi (UAT-M07, QA M04 F4)."""
        ...


class CatalogPricePort(Protocol):
    """M30 hamkor API: tashqi tizim (kassa, ERP) narx yozadi — odatdagi narx versiyasi va audit bilan."""

    async def set_price(
        self,
        db: AsyncSession,
        actor: ActorContext,
        sku_id: UUID,
        amount_minor: int,
        currency: Currency,
        reason: str,
    ) -> bool:
        """`True` — yangi versiya yozildi, `False` — narx o'zgarmagan. SKU yo'q/arxivda — NotFoundError."""
        ...
