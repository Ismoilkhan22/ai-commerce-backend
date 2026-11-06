"""Import qatori bo'yicha reja: yangi / yangilanadi / o'tkaziladi / xato (18 §6) — sinovda ham, yozishda ham.

Yozish paytida reja QAYTA tuziladi (sinovdan keyin SKU paydo bo'lgan yoki narx o'zgargan bo'lishi mumkin):
sinov natijasi faqat ko'rib chiqish uchun, yozish doim joriy holatdan.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.imports.parsing import category_lookup, normalize_header
from app.domains.catalog.pricing.models.orm import CurrentPrice, PriceVersion
from app.domains.catalog.pricing.services.pricing_service import PricingService
from app.domains.catalog.products.models.orm import Category, Product, Sku
from app.domains.catalog.products.schemas import SKU_CODE, PriceIn, SkuIn
from app.platform.shops.models.orm import Branch
from app.shared.money import MAX_USD_MINOR, MINOR_PER_UNIT
from app.shared.types.actor import ActorContext

_SKU_CODE = re.compile(SKU_CODE)
PRODUCT_FIELDS = ("title", "brand", "description")
SKU_FIELDS = ("variant_name", "condition", "mpn", "model_name", "warranty_months")


@dataclass
class Existing:
    sku: Sku
    product: Product
    price_amount: int | None
    price_currency: str | None
    price_version: int  # joriy narx ko'rsatkichi versiyasi (0 — narx yo'q)


@dataclass
class PlanContext:
    """Bitta bo'lak uchun bazadan bir marta o'qilgan ma'lumot."""

    categories: dict[str, Category]  # kod → toifa (faol)
    category_names: dict[str, str]  # sinonim → kod
    branches: dict[str, UUID]  # nom (kichik harf) → filial (ochiq, xodim doirasida)
    branch_ids: set[UUID]
    has_rate: bool
    existing: dict[str, Existing]  # SKU kodi (kichik harf) → mavjud SKU
    policy: str
    stock_enabled: bool
    default_branch_id: UUID | None


@dataclass
class Plan:
    action: str  # CREATE | UPDATE | SKIP | ERROR
    errors: list[dict[str, str]] = field(default_factory=list)
    skip_reason: str | None = None  # EXISTS | UNCHANGED
    existing: Existing | None = None
    category: Category | None = None
    product_changes: dict[str, Any] = field(default_factory=dict)
    sku_changes: dict[str, Any] = field(default_factory=dict)
    price: PriceIn | None = None
    price_changed: bool = False
    sku_in: SkuIn | None = None
    stock: tuple[UUID, int] | None = None  # (filial, absolyut qoldiq)

    def error(self, name: str, code: str) -> None:
        if not any(e["field"] == name for e in self.errors):
            self.errors.append({"field": name, "code": code})


async def load_context(
    db: AsyncSession,
    actor: ActorContext,
    pricing: PricingService,
    codes: Iterable[str],
    *,
    policy: str,
    stock_enabled: bool,
    default_branch_id: UUID | None,
) -> PlanContext:
    assert actor.shop_id is not None
    shop_id = actor.shop_id
    categories = {
        c.code: c for c in (await db.execute(select(Category).where(Category.is_active.is_(True)))).scalars()
    }
    names = category_lookup([(c.code, c.name_uz, c.name_ru, c.name_en) for c in categories.values()])
    branch_rows = (
        await db.execute(select(Branch).where(Branch.shop_id == shop_id, Branch.status == "ACTIVE"))
    ).scalars()
    branches: dict[str, UUID] = {}
    branch_ids: set[UUID] = set()
    for branch in branch_rows:
        if actor.branch_ids is not None and branch.id not in actor.branch_ids:
            continue  # filial doirasi (10 §6.8)
        branches.setdefault(branch.name.strip().lower(), branch.id)
        branch_ids.add(branch.id)
    lowered = sorted({c.lower() for c in codes if c})
    existing: dict[str, Existing] = {}
    if lowered:
        rows = await db.execute(
            select(Sku, Product, PriceVersion, CurrentPrice)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .outerjoin(CurrentPrice, (CurrentPrice.shop_id == Sku.shop_id) & (CurrentPrice.sku_id == Sku.id))
            .outerjoin(PriceVersion, PriceVersion.id == CurrentPrice.price_version_id)
            .where(Sku.shop_id == shop_id, func.lower(Sku.sku_code).in_(lowered))
        )
        for sku, product, version, current in rows:
            existing[sku.sku_code.lower()] = Existing(
                sku,
                product,
                version.amount_minor if version else None,
                version.currency if version else None,
                current.version if current else 0,
            )
    return PlanContext(
        categories=categories,
        category_names=names,
        branches=branches,
        branch_ids=branch_ids,
        has_rate=await pricing.current_rate(db, shop_id) is not None,
        existing=existing,
        policy=policy,
        stock_enabled=stock_enabled,
        default_branch_id=default_branch_id if default_branch_id in branch_ids else None,
    )


def _minor(amount: str) -> int:
    return int(Decimal(amount) * MINOR_PER_UNIT)


def _stock(plan: Plan, ctx: PlanContext, values: Mapping[str, Any]) -> None:
    quantity = values.get("quantity")
    if quantity is None or not ctx.stock_enabled:
        return
    name = values.get("branch")
    if name is not None:
        branch_id = ctx.branches.get(str(name).strip().lower())
        if branch_id is None:
            plan.error("branch", "UNKNOWN_BRANCH")
            return
    elif ctx.default_branch_id is not None:
        branch_id = ctx.default_branch_id
    else:
        plan.error("branch", "REQUIRED")
        return
    plan.stock = (branch_id, int(quantity))


def _price(plan: Plan, ctx: PlanContext, values: Mapping[str, Any]) -> None:
    amount = values.get("price")
    if amount is None:
        return
    currency = values.get("currency") or "UZS"
    minor = _minor(str(amount))
    if currency == "USD" and minor > MAX_USD_MINOR:
        plan.error("price", "INVALID_NUMBER")
        return
    if currency == "USD" and not ctx.has_rate:
        plan.error("price", "NO_EXCHANGE_RATE")  # 18 §11: dollar narxi, lekin shop kursi yo'q
        return
    try:
        plan.price = PriceIn(currency=currency, amount_minor=minor, reason="Import")
    except PydanticValidationError:
        plan.error("price", "INVALID_NUMBER")


def _sku_in(plan: Plan, values: Mapping[str, Any], attributes: dict[str, Any]) -> None:
    try:
        plan.sku_in = SkuIn(
            sku_code=values["sku_code"],
            variant_name=values.get("variant_name"),
            condition=values.get("condition") or "NEW",
            mpn=values.get("mpn"),
            model_name=values.get("model"),
            attributes=attributes,
            warranty_months=values.get("warranty_months"),
            price=plan.price,
        )
    except PydanticValidationError as exc:
        for item in exc.errors():
            loc = item["loc"][0] if item["loc"] else "row"
            plan.error({"model_name": "model"}.get(str(loc), str(loc)), "INVALID_FORMAT")


def _attributes(values: Mapping[str, Any], current: Mapping[str, Any] | None) -> dict[str, Any]:
    attributes = dict(current or {})
    attributes.update(values.get("attributes") or {})
    if values.get("barcode"):
        attributes["barcode"] = values["barcode"]
    return attributes


def plan_row(ctx: PlanContext, values: Mapping[str, Any], row_errors: Iterable[dict[str, str]]) -> Plan:
    plan = Plan(action="ERROR", errors=[dict(e) for e in row_errors])
    code = values.get("sku_code")
    if not code:
        plan.error("sku_code", "REQUIRED")
    elif not _SKU_CODE.match(str(code)):
        plan.error("sku_code", "INVALID_FORMAT")
    existing = ctx.existing.get(str(code).lower()) if code else None
    plan.existing = existing
    if existing is not None and (existing.product.status == "ARCHIVED" or existing.sku.status != "ACTIVE"):
        plan.error("sku_code", "ARCHIVED")

    if ctx.policy == "STOCK_ONLY":  # omborchi importi: katalogga tegilmaydi (DEC-140, 2-qaror)
        if code and existing is None:
            plan.error("sku_code", "NOT_FOUND")
        if values.get("quantity") is None:
            plan.error("quantity", "REQUIRED")
        _stock(plan, ctx, values)
        plan.action = "ERROR" if plan.errors else "UPDATE"
        return plan

    category_value = values.get("category")
    if category_value is not None:
        category_code = ctx.category_names.get(normalize_header(str(category_value)))
        if category_code is None or category_code not in ctx.categories:
            plan.error("category", "INVALID_CHOICE")
        else:
            plan.category = ctx.categories[category_code]
    _price(plan, ctx, values)
    _stock(plan, ctx, values)

    if existing is None:
        if ctx.policy == "UPDATE_PRICE_ONLY":
            if code:
                plan.error("sku_code", "NOT_FOUND")
        else:
            if not values.get("title"):
                plan.error("title", "REQUIRED")
            if category_value is None:
                plan.error("category", "REQUIRED")
            if code and not plan.errors:
                _sku_in(plan, values, _attributes(values, None))
        if not plan.errors:
            plan.action = "CREATE"
        return plan

    if plan.errors:
        return plan
    if ctx.policy == "CREATE_ONLY":
        plan.action, plan.skip_reason = "SKIP", "EXISTS"
        return plan
    if ctx.policy == "UPDATE_PRICE_ONLY" and plan.price is None:
        plan.error("price", "REQUIRED")
        return plan
    if ctx.policy == "UPDATE_EXISTING":
        for name in PRODUCT_FIELDS:
            if values.get(name) is not None:
                plan.product_changes[name] = values[name]
        if plan.category is not None:
            plan.product_changes["category_code"] = plan.category.code
        for name in SKU_FIELDS:
            source = "model" if name == "model_name" else name
            if values.get(source) is not None:
                plan.sku_changes[name] = values[source]
        if values.get("attributes") or values.get("barcode"):
            plan.sku_changes["attributes"] = _attributes(values, existing.sku.attributes)
        plan.product_changes = {
            k: v for k, v in plan.product_changes.items() if getattr(existing.product, k) != v
        }
        plan.sku_changes = {k: v for k, v in plan.sku_changes.items() if getattr(existing.sku, k) != v}
    if plan.price is not None:
        plan.price_changed = (plan.price.amount_minor, plan.price.currency) != (
            existing.price_amount,
            existing.price_currency,
        )
    changed = plan.product_changes or plan.sku_changes or plan.price_changed or plan.stock is not None
    plan.action = "UPDATE" if changed else "SKIP"
    if not changed:
        plan.skip_reason = "UNCHANGED"
    return plan
