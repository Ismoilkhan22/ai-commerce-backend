"""CatalogQueryPort implementatsiyasi (app/shared/contracts/catalog.py). Ulanish — app/dependencies.py.

Sayt (4-modul) o'qishlari ham shu yerda: faqat ommaviy maydonlar, faqat ko'rinadigan mahsulotlar.
"Ko'rinadi" — mahsulot PUBLISHED, variant ACTIVE va narxi bor; dollar narxi faqat shop kursi bo'lsa (BL-012).
So'mga o'girish SQL'da ham `to_uzs_minor` bilan aynan bir xil: eng yaqin butun so'm, 0.5 yuqoriga (DEC-133).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, ColumnElement, Numeric, cast, exists, func, literal, null, or_, select
from sqlalchemy import case as sql_case
from sqlalchemy import tuple_ as sql_tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.imports.models.orm import ImportStockRow as StagedRow
from app.domains.catalog.pricing.models.orm import CurrentPrice, PriceVersion
from app.domains.catalog.pricing.services.pricing_service import RATE_MAX_AGE, PricingService, uzs_amount
from app.domains.catalog.products.models.orm import Category, Product, ProductMedia, Sku
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import (
    PublicCategory,
    PublicProductCard,
    PublicProductDetail,
    PublicProductPage,
    PublicSort,
    PublicVariant,
    SkuSnapshot,
)
from app.shared.contracts.imports import ImportStockRow
from app.shared.errors.base import ValidationError
from app.shared.pagination import decode_cursor, encode_cursor
from app.shared.text import NUL

PUBLIC_CURSOR_KIND = "sf-products"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _uzs_price(rate: Decimal | None) -> ColumnElement[Any]:
    """Variant narxi so'mda (tiyinda). Kurs yo'q bo'lsa dollar narxi NULL — variant ko'rinmaydi (BL-012)."""
    if rate is None:
        return sql_case((PriceVersion.currency == "UZS", PriceVersion.amount_minor), else_=null())
    converted = func.round(cast(PriceVersion.amount_minor, Numeric) * literal(rate, Numeric) / 100) * 100
    return sql_case(
        (PriceVersion.currency == "UZS", PriceVersion.amount_minor), else_=cast(converted, BigInteger)
    )


def _bad_cursor() -> ValidationError:
    return ValidationError(
        "Cursor is invalid", fields=[{"field": "cursor", "code": "invalid_format", "params": {}}]
    )


class CatalogQueryPortImpl:
    def __init__(self) -> None:
        self.pricing = PricingService(AuditService())  # faqat o'qish — audit yozilmaydi

    async def get_skus(
        self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, SkuSnapshot]:
        if not sku_ids:
            return {}
        rows = await db.execute(
            select(Sku, Product)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .where(Sku.shop_id == shop_id, Sku.id.in_(list(sku_ids)))
        )
        pairs = list(rows)
        prices = await self.pricing.active_prices(db, shop_id, [sku.id for sku, _ in pairs])
        rate = await self.pricing.current_rate(db, shop_id)
        rate_stale = rate is not None and rate.effective_at < utcnow() - RATE_MAX_AGE
        result: dict[UUID, SkuSnapshot] = {}
        for sku, product in pairs:
            active = prices.get(sku.id)
            version = active.version if active else None
            usd = version is not None and version.currency == "USD"
            result[sku.id] = SkuSnapshot(
                sku_id=sku.id,
                product_id=product.id,
                title=" · ".join(part for part in (product.title, sku.variant_name) if part),
                sku_code=sku.sku_code,
                sellable=product.status == "PUBLISHED" and sku.status == "ACTIVE",
                product_status=product.status,
                sku_status=sku.status,
                warranty_months=sku.warranty_months,
                price_version_id=version.id if version else None,
                amount_minor=version.amount_minor if version else None,
                currency=("USD" if usd else "UZS") if version else None,
                exchange_rate_id=rate.id if usd and rate else None,
                exchange_rate=rate.rate if usd and rate else None,
                exchange_rate_effective_at=rate.effective_at if usd and rate else None,
                exchange_rate_stale=bool(usd and rate_stale),
                uzs_amount_minor=uzs_amount(version, rate) if version else None,
                product_title=product.title,
                variant_name=sku.variant_name,
            )
        return result

    async def search_sku_ids(self, db: AsyncSession, shop_id: UUID, q: str, limit: int) -> list[UUID]:
        text = q.strip()
        if not text:
            return []
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = await db.execute(
            select(Sku.id)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .where(
                Sku.shop_id == shop_id,
                or_(
                    Product.title.ilike(pattern, escape="\\"),
                    Product.brand.ilike(pattern, escape="\\"),
                    Sku.sku_code.ilike(pattern, escape="\\"),
                    Sku.mpn.ilike(pattern, escape="\\"),
                    Sku.variant_name.ilike(pattern, escape="\\"),
                ),
            )
            .order_by(Sku.id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def pick_sku_ids(self, db: AsyncSession, shop_id: UUID, q: str | None, limit: int) -> list[UUID]:
        query = (
            select(Sku.id)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .where(Sku.shop_id == shop_id, Sku.status == "ACTIVE", Product.status != "ARCHIVED")
        )
        text = (q or "").strip()
        if text:
            pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(
                or_(
                    Product.title.ilike(pattern, escape="\\"),
                    Product.brand.ilike(pattern, escape="\\"),
                    Sku.sku_code.ilike(pattern, escape="\\"),
                    Sku.mpn.ilike(pattern, escape="\\"),
                    Sku.variant_name.ilike(pattern, escape="\\"),
                )
            )
        rows = await db.execute(query.order_by(Product.title, Sku.sku_code, Sku.id).limit(limit))
        return list(rows.scalars())

    # ================================================================== sayt (ommaviy)
    async def _rate(self, db: AsyncSession, shop_id: UUID) -> Decimal | None:
        rate = await self.pricing.current_rate(db, shop_id)
        return rate.rate if rate else None

    @staticmethod
    def _visible_variants(shop_id: UUID, rate: Decimal | None) -> Any:
        """Ko'rinadigan variantlar: faol, narxi bor, so'mdagi narxi aniq (kursi yo'q dollar — yo'q)."""
        uzs = _uzs_price(rate)
        return (
            select(Sku.product_id.label("product_id"), Sku.id.label("sku_id"), uzs.label("uzs"))
            .join(CurrentPrice, (CurrentPrice.shop_id == Sku.shop_id) & (CurrentPrice.sku_id == Sku.id))
            .join(
                PriceVersion,
                (PriceVersion.shop_id == CurrentPrice.shop_id)
                & (PriceVersion.id == CurrentPrice.price_version_id),
            )
            .where(Sku.shop_id == shop_id, Sku.status == "ACTIVE", uzs.is_not(None))
            .subquery()
        )

    async def public_categories(self, db: AsyncSession, shop_id: UUID) -> list[PublicCategory]:
        variants = self._visible_variants(shop_id, await self._rate(db, shop_id))
        counts = dict(
            (
                await db.execute(
                    select(Product.category_code, func.count(func.distinct(Product.id)))
                    .join(variants, variants.c.product_id == Product.id)
                    .where(Product.shop_id == shop_id, Product.status == "PUBLISHED")
                    .group_by(Product.category_code)
                )
            ).all()
        )
        if not counts:
            return []
        categories = {c.code: c for c in (await db.execute(select(Category))).scalars()}
        wanted: set[str] = set()
        for code in counts:  # mahsuloti bor toifa va uning hamma ota toifalari (menyu daraxti)
            current = categories.get(code)
            while current is not None and current.code not in wanted:
                wanted.add(current.code)
                current = categories.get(current.parent_code) if current.parent_code else None
        return [
            PublicCategory(
                code=c.code,
                parent_code=c.parent_code,
                name_uz=c.name_uz,
                name_ru=c.name_ru,
                name_en=c.name_en,
                position=c.position,
                product_count=int(counts.get(c.code, 0)),
            )
            for c in sorted((categories[code] for code in wanted), key=lambda c: (c.position, c.code))
        ]

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
        variants = self._visible_variants(shop_id, await self._rate(db, shop_id))
        agg = (
            select(
                variants.c.product_id,
                func.min(variants.c.uzs).label("price_from"),
                func.count().label("variant_count"),
                func.array_agg(variants.c.sku_id).label("sku_ids"),
            )
            .group_by(variants.c.product_id)
            .subquery()
        )
        published = func.coalesce(Product.published_at, Product.created_at)
        query = (
            select(Product, agg.c.price_from, agg.c.variant_count, agg.c.sku_ids, published.label("pub"))
            .join(agg, agg.c.product_id == Product.id)
            .where(Product.shop_id == shop_id, Product.status == "PUBLISHED")
        )
        if category_codes is not None:
            query = query.where(Product.category_code.in_(list(category_codes)))
        if q and q.strip():
            pattern = f"%{_escape_like(q.strip())}%"
            code_match = exists().where(
                Sku.shop_id == Product.shop_id,
                Sku.product_id == Product.id,
                Sku.status == "ACTIVE",
                Sku.sku_code.ilike(pattern, escape="\\"),
            )
            query = query.where(
                or_(
                    Product.title.ilike(pattern, escape="\\"),
                    Product.brand.ilike(pattern, escape="\\"),
                    code_match,
                )
            )
        key: Any = published if sort == "newest" else agg.c.price_from
        descending = sort in ("newest", "price_desc")
        if cursor:
            value, last_id = self._public_after(cursor, sort)
            row_key = sql_tuple(key, Product.id)
            query = query.where(row_key < (value, last_id) if descending else row_key > (value, last_id))
        order = (key.desc(), Product.id.desc()) if descending else (key.asc(), Product.id.asc())
        rows = list((await db.execute(query.order_by(*order).limit(limit + 1))).all())
        has_more, page = len(rows) > limit, rows[:limit]
        images = await self._first_images(db, shop_id, [row[0].id for row in page])
        items = tuple(
            PublicProductCard(
                product_id=product.id,
                title=product.title,
                brand=product.brand,
                category_code=product.category_code,
                published_at=product.published_at,
                price_from_uzs_minor=int(price_from),
                variant_count=int(variant_count),
                image_file_id=images.get(product.id),
                sku_ids=tuple(sku_ids),
            )
            for product, price_from, variant_count, sku_ids, _ in page
        )
        next_cursor = None
        if has_more and page:
            last = page[-1]
            value = last[4] if sort == "newest" else int(last[1])
            next_cursor = encode_cursor(
                {
                    "k": PUBLIC_CURSOR_KIND,
                    "s": sort,
                    "v": value.isoformat() if isinstance(value, datetime) else value,
                    "id": str(last[0].id),
                }
            )
        return PublicProductPage(items=items, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _public_after(cursor: str, sort: str) -> tuple[Any, UUID]:
        """Cursor klientdan keladi — har shakli tekshiriladi (buzilgani 500 emas, 422)."""
        raw = decode_cursor(cursor)
        raw_value, raw_id = raw.get("v"), raw.get("id")
        try:
            if raw.get("k") != PUBLIC_CURSOR_KIND or raw.get("s") != sort or not isinstance(raw_id, str):
                raise ValueError("cursor shape")
            value: Any
            if sort == "newest":
                if not isinstance(raw_value, str) or NUL in raw_value:
                    raise ValueError("cursor value")
                value = datetime.fromisoformat(raw_value)
                if value.tzinfo is None or value.year < 2000:
                    raise ValueError("cursor time")
            else:
                # bool — int'ning bolasi; narx musbat butun son
                if isinstance(raw_value, bool) or not isinstance(raw_value, int) or not 0 < raw_value < 2**63:
                    raise ValueError("cursor price")
                value = raw_value
            return value, UUID(raw_id)
        except ValueError as exc:
            raise _bad_cursor() from exc

    async def _first_images(
        self, db: AsyncSession, shop_id: UUID, product_ids: list[UUID]
    ) -> dict[UUID, UUID]:
        if not product_ids:
            return {}
        rows = await db.execute(
            select(ProductMedia.product_id, ProductMedia.file_id)
            .where(ProductMedia.shop_id == shop_id, ProductMedia.product_id.in_(product_ids))
            .order_by(ProductMedia.product_id, ProductMedia.position, ProductMedia.id)
        )
        first: dict[UUID, UUID] = {}
        for product_id, file_id in rows:
            first.setdefault(product_id, file_id)
        return first

    async def public_product(
        self, db: AsyncSession, shop_id: UUID, product_id: UUID
    ) -> PublicProductDetail | None:
        product = (
            await db.execute(
                select(Product).where(
                    Product.shop_id == shop_id, Product.id == product_id, Product.status == "PUBLISHED"
                )
            )
        ).scalar_one_or_none()
        if product is None:
            return None
        variants = self._visible_variants(shop_id, await self._rate(db, shop_id))
        rows = list(
            (
                await db.execute(
                    select(Sku, variants.c.uzs)
                    .join(variants, variants.c.sku_id == Sku.id)
                    .where(Sku.shop_id == shop_id, Sku.product_id == product.id)
                    .order_by(variants.c.uzs, Sku.created_at, Sku.id)
                )
            ).all()
        )
        if not rows:  # narxi bor faol variant qolmagan — saytda ko'rinmaydi
            return None
        media = await db.execute(
            select(ProductMedia.file_id)
            .where(ProductMedia.shop_id == shop_id, ProductMedia.product_id == product.id)
            .order_by(ProductMedia.position, ProductMedia.id)
        )
        return PublicProductDetail(
            product_id=product.id,
            title=product.title,
            brand=product.brand,
            description=product.description,
            category_code=product.category_code,
            published_at=product.published_at,
            image_file_ids=tuple(media.scalars()),
            variants=tuple(
                PublicVariant(
                    sku_id=sku.id,
                    variant_name=sku.variant_name,
                    condition=sku.condition,
                    warranty_months=sku.warranty_months,
                    attributes=dict(sku.attributes or {}),
                    price_uzs_minor=int(uzs),
                )
                for sku, uzs in rows
            ),
        )

    async def public_live_variants(
        self, db: AsyncSession, shop_id: UUID, product_id: UUID
    ) -> dict[UUID, int]:
        variants = self._visible_variants(shop_id, await self._rate(db, shop_id))
        rows = await db.execute(
            select(variants.c.sku_id, variants.c.uzs)
            .join(Product, (Product.shop_id == shop_id) & (Product.id == variants.c.product_id))
            .where(Product.id == product_id, Product.status == "PUBLISHED")
        )
        return {sku_id: int(uzs) for sku_id, uzs in rows}


class ImportStockSourceImpl:
    """Katalog importining qoldiq "kutish zali" — commerce faqat shu orqali o'qiydi (18 §7)."""

    async def stock_rows(
        self,
        db: AsyncSession,
        shop_id: UUID,
        batch_id: UUID,
        after: tuple[UUID, UUID] | None,
        limit: int,
    ) -> list[ImportStockRow]:
        query = select(StagedRow).where(StagedRow.shop_id == shop_id, StagedRow.batch_id == batch_id)
        if after is not None:
            query = query.where(sql_tuple(StagedRow.branch_id, StagedRow.sku_id) > sql_tuple(*after))
        rows = await db.execute(query.order_by(StagedRow.branch_id, StagedRow.sku_id).limit(limit))
        return [ImportStockRow(r.sku_id, r.branch_id, r.quantity, r.row_number) for r in rows.scalars()]
