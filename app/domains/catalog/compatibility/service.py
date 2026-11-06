"""Shop SKU'lari bo'yicha moslik tekshiruvi — 6-modul integratsiya nuqtasi (engineering/17 §7).

`sales_ai` ning `catalog.check_compatibility` tool'i va `commerce/quotes` shu funksiyani
`CatalogQueryPort.check_compatibility` orqali chaqiradi. Faqat o'qiydi: SKU → bog'langan spec → engine.
Spec'ning joriy tasdiqlangan versiyasi ishlatiladi; natijada versiyalar qaytadi (BL-030).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.compatibility.engine import check
from app.domains.catalog.compatibility.model import PC_CATEGORIES, Build, Part
from app.domains.catalog.pc_specs.models.orm import ReferenceHardwareSpec, SkuSpecLink
from app.domains.catalog.products.models.orm import Category, Product, Sku
from app.shared.contracts.compatibility import BuildLine, CompatibilityResult
from app.shared.errors.base import ValidationError
from app.shared.i18n.locale import Locale

# Bog'langan deb hisoblanadigan spec holatlari.
# RETIRED — eski bog'lanishlar saqlanadi (M02), ma'lumot hali to'g'ri
USABLE_SPEC_STATUSES = ("APPROVED", "RETIRED")


def _field(field: str, code: str) -> dict[str, Any]:
    return {"field": field, "code": code, "params": {}}


async def check_skus(
    db: AsyncSession,
    shop_id: UUID,
    lines: Sequence[BuildLine],
    locale: Locale = "uz",
    *,
    full_build: bool = True,
) -> CompatibilityResult:
    """Yig'ma qatorlarini engine qismlariga aylantiradi.

    PC qismi bo'lmagan SKU'lar (monitor va h.k.) tekshirilmaydi.
    """
    for index, line in enumerate(lines):
        if line.quantity < 1:
            raise ValidationError(
                "Invalid quantity", fields=[_field(f"lines[{index}].quantity", "min_value")]
            )
    ids = list(dict.fromkeys(line.sku_id for line in lines))
    rows = (
        await db.execute(
            select(Sku.id, Category.spec_category, SkuSpecLink.spec_id, ReferenceHardwareSpec)
            .join(Product, and_(Product.shop_id == Sku.shop_id, Product.id == Sku.product_id))
            .join(Category, Category.code == Product.category_code)
            .outerjoin(SkuSpecLink, and_(SkuSpecLink.shop_id == Sku.shop_id, SkuSpecLink.sku_id == Sku.id))
            .outerjoin(
                ReferenceHardwareSpec,
                and_(
                    ReferenceHardwareSpec.id == SkuSpecLink.spec_id,
                    ReferenceHardwareSpec.status.in_(USABLE_SPEC_STATUSES),
                ),
            )
            .where(Sku.shop_id == shop_id, Sku.id.in_(ids))
        )
    ).all()
    found = {row[0]: row for row in rows}
    unknown = [i for i, line in enumerate(lines) if line.sku_id not in found]
    if unknown:
        raise ValidationError(
            "Unknown SKU", fields=[_field(f"lines[{i}].sku_id", "invalid") for i in unknown]
        )

    parts: list[Part] = []
    ignored: list[UUID] = []
    for line in lines:
        _, spec_category, _, spec = found[line.sku_id]
        category = spec.category if spec is not None else spec_category
        if category not in PC_CATEGORIES:
            ignored.append(line.sku_id)
            continue
        if spec is None:
            parts.append(Part(category=category, quantity=line.quantity, sku_id=line.sku_id))
            continue
        parts.append(
            Part(
                category=category,
                attributes=dict(spec.attributes or {}),
                quantity=line.quantity,
                sku_id=line.sku_id,
                spec_id=spec.id,
                spec_version=spec.version,
                source_url=spec.source_url,
                model_label=f"{spec.brand} {spec.model_name}",
            )
        )
    result = check(Build.of(parts, full_build=full_build), locale)
    return replace(result, ignored_sku_ids=tuple(ignored)) if ignored else result
