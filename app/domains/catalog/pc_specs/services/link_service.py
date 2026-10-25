"""Shop SKU'sini texnik kutubxonadagi modelga bog'lash va "yangi model" so'rovi (engineering/17 §5, DEC-120).

Avtomatik bog'lash faqat ANIQ BITTA nomzod bo'lsa: avval MPN, keyin brend + model nomi (normallashtirilgan).
"RTX 5060" ↔ "RTX 5060 Ti", "8GB" ↔ "16GB" hech qachon birlashmaydi:
- brend + model bo'yicha topilgan modelning varianti ("8GB") SKU'da ko'rinishi shart (variant nomi, mahsulot
  nomi yoki atributlar), SKU boshqa hajmni aytsa ("16GB") — bog'lanmaydi;
- SKU'ning MPN'i modelning MPN'idan farq qilsa — bog'lanmaydi.
Shubha bo'lsa — bog'lanmaydi, xodim nomzodlardan tanlaydi. Xodim o'zi tanlagan (MANUAL) bog'lanishni
avtomatika o'zgartirmaydi; xodim bog'lanishni uzgan bo'lsa — qayta bog'lamaydi (`spec_autolink_blocked`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pc_specs.models.orm import ReferenceHardwareSpec, SkuSpecLink, SpecRequest
from app.domains.catalog.pc_specs.normalize import normalize_brand, normalize_code
from app.domains.catalog.pc_specs.schemas import (
    AutoLinkResult,
    HardwareSpecOut,
    SpecCandidates,
    SpecRequestIn,
    SpecRequestList,
    SpecRequestOut,
)
from app.domains.catalog.products.models.orm import Category, Product, Sku
from app.domains.catalog.products.schemas import SpecLinkOut
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.errors.base import InvalidTransitionError, NotFoundError, ValidationError
from app.shared.types.actor import ActorContext

SKU = "catalog.sku"
SHOP_SEARCH_LIMIT = 20
REQUEST_LIST_LIMIT = 100
_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|MB)(?![A-Z])", re.IGNORECASE)
# Kutubxona atributlaridagi hajm (17 §4.1): videokarta xotirasi, disk sig'imi, RAM moduli
_SPEC_SIZE_ATTRS = ("memory_gb", "capacity_gb", "capacity_per_module_gb")


_TO_GB = {"MB": Decimal("0.001"), "GB": Decimal(1), "TB": Decimal(1000)}  # disk sig'imi: 1 TB = 1000 GB


def _size_token(number: str, unit: str) -> str | None:
    """Hajm GB'da: "1TB" va kutubxonadagi `capacity_gb: 1000` bir xil chiqsin."""
    try:
        value = Decimal(number.replace(",", ".")) * _TO_GB[unit.upper()]
    except InvalidOperation:
        return None
    return f"{format(value.normalize(), 'f')}GB"


def sizes_in(*texts: str | None) -> set[str]:
    """Matndagi hajmlar: "RTX 4060 8 GB" → {"8GB"}; "16GB (2x8GB)" → {"16GB", "8GB"}."""
    found: set[str] = set()
    for text in texts:
        for number, unit in _SIZE.findall(text or ""):
            if token := _size_token(number, unit):
                found.add(token)
    return found


def _sku_sizes(sku: Sku, product: Product) -> set[str]:
    found = sizes_in(sku.variant_name, product.title)
    for key, value in (sku.attributes or {}).items():
        if isinstance(value, str):
            found |= sizes_in(value)
        elif isinstance(value, int | float) and not isinstance(value, bool) and key.lower().endswith("gb"):
            if token := _size_token(str(value), "GB"):
                found.add(token)
    return found


def _spec_sizes(spec: ReferenceHardwareSpec) -> set[str]:
    attrs: dict[str, Any] = spec.attributes or {}
    found = sizes_in(spec.variant_key)
    for key in _SPEC_SIZE_ATTRS:
        if isinstance(attrs.get(key), int):
            found.add(f"{attrs[key]}GB")
    modules, per_module = attrs.get("module_count"), attrs.get("capacity_per_module_gb")
    if isinstance(modules, int) and isinstance(per_module, int):
        found.add(f"{modules * per_module}GB")  # RAM to'plami: 2 × 8 GB = 16 GB
    return found


def variant_agrees(spec: ReferenceHardwareSpec, sku: Sku, product: Product) -> bool:
    """Brend + model mos kelgan modelni avtomatik bog'lash mumkinmi — variant va hajm bo'yicha."""
    sku_sizes = _sku_sizes(sku, product)
    spec_sizes = _spec_sizes(spec)
    if spec.variant_key:
        key_sizes = sizes_in(spec.variant_key)
        if key_sizes:  # "8GB": SKU aynan shu hajmni aytishi va boshqasini aytmasligi shart
            return key_sizes <= sku_sizes and sku_sizes <= spec_sizes
        variant_text = normalize_code(f"{sku.variant_name or ''} {product.title}") or ""
        return spec.variant_key in variant_text  # "WHITE", "OC" kabi hajmsiz variant
    # Variantsiz model: SKU aytgan hajm modelnikiga zid bo'lmasin
    return not (sku_sizes and spec_sizes and not sku_sizes <= spec_sizes)


@dataclass(frozen=True)
class LinkView:
    link: SkuSpecLink
    spec: ReferenceHardwareSpec


def link_out(view: LinkView) -> SpecLinkOut:
    return SpecLinkOut(
        spec_id=view.spec.id,
        category=view.spec.category,
        brand=view.spec.brand,
        model_name=view.spec.model_name,
        variant_key=view.spec.variant_key,
        method=view.link.method,
        linked_at=view.link.linked_at,
    )


def spec_out(spec: ReferenceHardwareSpec, pending_version: int | None = None) -> HardwareSpecOut:
    return HardwareSpecOut(
        id=spec.id,
        category=spec.category,
        brand=spec.brand,
        model_name=spec.model_name,
        variant_key=spec.variant_key,
        mpn=spec.mpn,
        attributes=spec.attributes,
        source_url=spec.source_url,
        status=spec.status,
        version=spec.version,
        approved_at=spec.approved_at,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
        pending_version=pending_version,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class LinkService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    # ------------------------------------------------------------------ o'qish
    async def links_for(
        self, db: AsyncSession, shop_id: UUID | None, sku_ids: list[UUID]
    ) -> dict[UUID, LinkView]:
        if not sku_ids or shop_id is None:
            return {}
        rows = await db.execute(
            select(SkuSpecLink, ReferenceHardwareSpec)
            .join(ReferenceHardwareSpec, ReferenceHardwareSpec.id == SkuSpecLink.spec_id)
            .where(SkuSpecLink.shop_id == shop_id, SkuSpecLink.sku_id.in_(sku_ids))
        )
        return {link.sku_id: LinkView(link, spec) for link, spec in rows}

    async def search(self, db: AsyncSession, q: str | None, category: str | None) -> SpecCandidates:
        """Shop paneli: kutubxonadan qo'lda tanlash uchun qidiruv — faqat tasdiqlangan modellar."""
        query = select(ReferenceHardwareSpec).where(ReferenceHardwareSpec.status == "APPROVED")
        if category:
            query = query.where(ReferenceHardwareSpec.category == category)
        if q and q.strip():
            pattern = f"%{_escape_like(q.strip())}%"
            normalized = normalize_code(q)
            conditions: list[ColumnElement[bool]] = [
                ReferenceHardwareSpec.brand.ilike(pattern, escape="\\"),
                ReferenceHardwareSpec.model_name.ilike(pattern, escape="\\"),
                ReferenceHardwareSpec.mpn.ilike(pattern, escape="\\"),
            ]
            if normalized:
                conditions.append(
                    ReferenceHardwareSpec.model_normalized.contains(normalized, autoescape=True)
                )
            query = query.where(or_(*conditions))
        rows = await db.execute(
            query.order_by(ReferenceHardwareSpec.brand, ReferenceHardwareSpec.model_name).limit(
                SHOP_SEARCH_LIMIT
            )
        )
        return SpecCandidates(items=[spec_out(s) for s in rows.scalars()])

    async def candidates(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> SpecCandidates:
        sku, product, category = await self._sku_context(db, actor, sku_id)
        specs = await self._matches(db, category.spec_category, product.brand, sku)
        return SpecCandidates(items=[spec_out(s) for s in specs])

    # ------------------------------------------------------------------ avtomatik bog'lash
    async def auto_link(
        self, db: AsyncSession, actor: ActorContext, sku: Sku, product: Product, spec_category: str | None
    ) -> None:
        """SKU yaratilganda yoki MPN/model/brend/toifa o'zgarganda. Xodim tanlagan yoki xodim uzgan
        bog'lanishga tegmaydi."""
        existing = await db.get(SkuSpecLink, (sku.shop_id, sku.id))
        if (existing is not None and existing.method == "MANUAL") or sku.spec_autolink_blocked:
            return
        match = await self._auto_match(db, spec_category, product, sku)
        if match is None:
            if existing is not None:  # avtomatik bog'lanish endi to'g'ri emas (masalan, MPN o'zgardi)
                await db.delete(existing)
                await db.flush()
                await self._audit(db, actor, sku.id, "catalog.sku.spec_unlinked")
            return
        spec, method = match
        if existing is not None and existing.spec_id == spec.id and existing.method == method:
            return
        if existing is None:
            db.add(SkuSpecLink(shop_id=sku.shop_id, sku_id=sku.id, spec_id=spec.id, method=method))
        else:
            existing.spec_id, existing.method, existing.linked_by = spec.id, method, None
            existing.linked_at = utcnow()
        await db.flush()
        await self._audit(db, actor, sku.id, "catalog.sku.spec_linked", method)

    async def auto_link_all(self, db: AsyncSession, actor: ActorContext) -> AutoLinkResult:
        """Shopning bog'lanmagan faol SKU'larini qayta tekshiradi (kutubxonaga yangi model qo'shilgach)."""
        rows = await db.execute(
            select(Sku, Product, Category)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .join(Category, Category.code == Product.category_code)
            .outerjoin(SkuSpecLink, (SkuSpecLink.shop_id == Sku.shop_id) & (SkuSpecLink.sku_id == Sku.id))
            .where(
                Sku.shop_id == actor.shop_id,
                Sku.status == "ACTIVE",
                Product.status != "ARCHIVED",
                Category.spec_category.is_not(None),
                SkuSpecLink.sku_id.is_(None),
                Sku.spec_autolink_blocked.is_(False),
            )
        )
        checked = linked = 0
        for sku, product, category in rows:
            checked += 1
            await self.auto_link(db, actor, sku, product, category.spec_category)
            if await db.get(SkuSpecLink, (sku.shop_id, sku.id)) is not None:
                linked += 1
        return AutoLinkResult(checked=checked, linked=linked)

    # ------------------------------------------------------------------ qo'lda
    async def set_link(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, spec_id: UUID
    ) -> SpecLinkOut:
        sku, _, category = await self._sku_context(db, actor, sku_id, editable=True)
        spec = await db.get(ReferenceHardwareSpec, spec_id)
        if (
            spec is None
            or spec.status != "APPROVED"
            or category.spec_category is None
            or spec.category != category.spec_category
        ):
            raise ValidationError(
                "Spec cannot be linked", fields=[{"field": "spec_id", "code": "invalid", "params": {}}]
            )
        link = await db.get(SkuSpecLink, (sku.shop_id, sku.id))
        if link is None:
            link = SkuSpecLink(shop_id=sku.shop_id, sku_id=sku.id, spec_id=spec.id, method="MANUAL")
            db.add(link)
        else:
            link.spec_id, link.method = spec.id, "MANUAL"
            link.linked_at = utcnow()
        link.linked_by = actor.membership_id
        sku.spec_autolink_blocked = False  # xodim o'zi bog'ladi — taqiq olinadi
        await db.flush()
        await db.refresh(link)
        await self._audit(db, actor, sku.id, "catalog.sku.spec_linked", "MANUAL")
        return link_out(LinkView(link, spec))

    async def remove_link(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> None:
        """Xodim qarori: bog'lanish uziladi va avtomatika uni qayta tiklamaydi, xodim o'zi bog'laguncha."""
        sku, _, _ = await self._sku_context(db, actor, sku_id, editable=True, for_update=True)
        sku.spec_autolink_blocked = True
        link = await db.get(SkuSpecLink, (sku.shop_id, sku.id))
        if link is not None:
            await db.delete(link)
        await db.flush()
        if link is not None:
            await self._audit(db, actor, sku.id, "catalog.sku.spec_unlinked")

    async def drop_mismatched(
        self, db: AsyncSession, actor: ActorContext, skus: list[Sku], spec_category: str | None
    ) -> None:
        """Mahsulot toifasi almashganda: endi boshqa turdagi modelga bog'lanish (avto ham, qo'lda ham)
        uziladi — boshqa turdagi model bog'lanmaydi (M02 §4.4)."""
        links = await self.links_for(db, skus[0].shop_id if skus else None, [s.id for s in skus])
        for sku_id, view in links.items():
            if view.spec.category == spec_category:
                continue
            await db.delete(view.link)
            await db.flush()
            await self.audit.record(
                db,
                action="catalog.sku.spec_unlinked",
                entity_type=SKU,
                entity_id=sku_id,
                actor=actor,
                reason="category_changed",
                diff={"method": {"old": view.link.method}},
            )

    # ------------------------------------------------------------------ "yangi model" so'rovi
    async def create_request(
        self, db: AsyncSession, actor: ActorContext, data: SpecRequestIn
    ) -> SpecRequestOut:
        if data.sku_id is not None:
            _, _, category = await self._sku_context(db, actor, data.sku_id, editable=True)
            if category.spec_category != data.category:  # boshqa turdagi model SKU'ga bog'lanmaydi
                raise ValidationError(
                    "Category must match the SKU's product category",
                    fields=[
                        {
                            "field": "category",
                            "code": "invalid_choice",
                            "params": {"expected": category.spec_category},
                        }
                    ],
                )
        request = SpecRequest(
            shop_id=actor.shop_id,
            sku_id=data.sku_id,
            category=data.category,
            brand=data.brand.strip(),
            model_name=data.model_name.strip(),
            mpn=(data.mpn or "").strip() or None,
            source_url=data.source_url,
            comment=(data.comment or "").strip() or None,
            requested_by=actor.membership_id,
        )
        db.add(request)
        await db.flush()
        await db.refresh(request)
        await self.audit.record(
            db,
            action="catalog.spec_request.created",
            entity_type="catalog.spec_request",
            entity_id=request.id,
            actor=actor,
        )
        return SpecRequestOut.model_validate(request)

    async def list_requests(
        self, db: AsyncSession, actor: ActorContext, status: str | None
    ) -> SpecRequestList:
        query = select(SpecRequest).where(
            SpecRequest.shop_id == actor.shop_id
        )  # RLS'siz jadval — filtr shart
        if status:
            query = query.where(SpecRequest.status == status)
        rows = await db.execute(query.order_by(SpecRequest.created_at.desc()).limit(REQUEST_LIST_LIMIT))
        return SpecRequestList(items=[SpecRequestOut.model_validate(r) for r in rows.scalars()])

    async def get_request(self, db: AsyncSession, actor: ActorContext, request_id: UUID) -> SpecRequestOut:
        request = (
            await db.execute(  # RLS'siz jadval — shop filtri shart
                select(SpecRequest).where(SpecRequest.id == request_id, SpecRequest.shop_id == actor.shop_id)
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("Spec request not found")
        return SpecRequestOut.model_validate(request)

    # ------------------------------------------------------------------ ichki
    async def _matches(
        self, db: AsyncSession, spec_category: str | None, brand: str | None, sku: Sku
    ) -> list[ReferenceHardwareSpec]:
        """Aniq mos kelganlar: MPN bo'yicha, bo'lmasa brend + model bo'yicha (hammasi, tartib bilan)."""
        if spec_category is None:
            return []
        approved = (
            ReferenceHardwareSpec.status == "APPROVED",
            ReferenceHardwareSpec.category == spec_category,
        )
        if sku.mpn_normalized:
            by_mpn = list(
                (
                    await db.execute(
                        select(ReferenceHardwareSpec).where(
                            *approved, ReferenceHardwareSpec.mpn_normalized == sku.mpn_normalized
                        )
                    )
                ).scalars()
            )
            if by_mpn:
                return by_mpn
        model = normalize_code(sku.model_name)
        wanted_brand = normalize_brand(brand)
        if not model or not wanted_brand:
            return []
        rows = await db.execute(
            select(ReferenceHardwareSpec)
            .where(*approved, ReferenceHardwareSpec.model_normalized == model)
            .order_by(ReferenceHardwareSpec.variant_key)
        )
        return [s for s in rows.scalars() if normalize_brand(s.brand) == wanted_brand]

    async def _auto_match(
        self, db: AsyncSession, spec_category: str | None, product: Product, sku: Sku
    ) -> tuple[ReferenceHardwareSpec, str] | None:
        specs = await self._matches(db, spec_category, product.brand, sku)
        by_mpn = [s for s in specs if sku.mpn_normalized and s.mpn_normalized == sku.mpn_normalized]
        if by_mpn:
            return (by_mpn[0], "AUTO_MPN") if len(by_mpn) == 1 else None
        # Brend + model bo'yicha: MPN'i zid yoki varianti mos kelmaganlar chiqariladi (M02 §4.4)
        fitting = [
            s
            for s in specs
            if not (sku.mpn_normalized and s.mpn_normalized and s.mpn_normalized != sku.mpn_normalized)
            and variant_agrees(s, sku, product)
        ]
        if len(fitting) != 1:
            return None  # topilmadi yoki shubhali — xodim nomzodlardan tanlaydi
        return fitting[0], "AUTO_MODEL"

    async def _sku_context(
        self,
        db: AsyncSession,
        actor: ActorContext,
        sku_id: UUID,
        *,
        editable: bool = False,
        for_update: bool = False,
    ) -> tuple[Sku, Product, Category]:
        query = (
            select(Sku, Product, Category)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .join(Category, Category.code == Product.category_code)
            .where(Sku.id == sku_id, Sku.shop_id == actor.shop_id)
        )
        if for_update:
            query = query.with_for_update(of=Sku)
        row = (await db.execute(query)).one_or_none()
        if row is None:
            raise NotFoundError("SKU not found")
        sku, product, category = row
        if editable and (sku.status != "ACTIVE" or product.status == "ARCHIVED"):
            raise InvalidTransitionError(
                "SKU is archived", entity=SKU, **{"from": "ARCHIVED"}, command="LINK_SPEC"
            )
        return sku, product, category

    async def _audit(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, action: str, method: str | None = None
    ) -> None:
        await self.audit.record(
            db,
            action=action,
            entity_type=SKU,
            entity_id=sku_id,
            actor=actor,
            diff={"method": {"new": method}} if method else None,
        )
