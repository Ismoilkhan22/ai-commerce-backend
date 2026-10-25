"""CatalogQueryPort implementatsiyasi (app/shared/contracts/catalog.py). Ulanish — app/dependencies.py."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pricing.services.pricing_service import PricingService, uzs_amount
from app.domains.catalog.products.models.orm import Product, Sku
from app.platform.audit.services.audit_service import AuditService
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
                warranty_months=sku.warranty_months,
                price_version_id=version.id if version else None,
                amount_minor=version.amount_minor if version else None,
                currency=("USD" if usd else "UZS") if version else None,
                exchange_rate_id=rate.id if usd and rate else None,
                exchange_rate=rate.rate if usd and rate else None,
                uzs_amount_minor=uzs_amount(version, rate) if version else None,
            )
        return result
