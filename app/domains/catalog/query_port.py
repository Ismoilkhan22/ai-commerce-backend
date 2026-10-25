"""CatalogQueryPort implementatsiyasi (app/shared/contracts/catalog.py). Ulanish — app/dependencies.py."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pricing.services.pricing_service import RATE_MAX_AGE, PricingService, uzs_amount
from app.domains.catalog.products.models.orm import Product, Sku
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import SkuSnapshot


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
