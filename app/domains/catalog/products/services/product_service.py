"""Mahsulot kartochkasi, variantlar (SKU), rasmlar va FSM-02 (S1-02, BL-011…BL-014, DEC-133).

Saytga chiqish sharti (BL-012): toifa va nom bor, kamida bitta faol SKU va uning narxi bor; dollar narxi
bo'lsa — shop kursi ham. Shart bajarilmasa, javobda nimasi yetishmayotgani maydon bo'yicha aytiladi.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pc_specs.normalize import normalize_code
from app.domains.catalog.pc_specs.services.link_service import LinkService, LinkView, link_out
from app.domains.catalog.pricing.models.orm import ExchangeRate
from app.domains.catalog.pricing.services.pricing_service import (
    ActivePrice,
    PricingService,
    price_out,
    uzs_amount,
)
from app.domains.catalog.products.models.orm import Category, Product, ProductMedia, Sku
from app.domains.catalog.products.schemas import (
    MediaOut,
    ProductCounts,
    ProductCreate,
    ProductList,
    ProductListItem,
    ProductOut,
    ProductSort,
    ProductUpdate,
    SkuIn,
    SkuOut,
    SkuUpdate,
)
from app.domains.catalog.products.services.category_service import CategoryService
from app.domains.catalog.products.state_machine import ENTITY as PRODUCT
from app.platform.audit.services.audit_service import AuditService
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.errors.base import FileInUseError, InvalidTransitionError, NotFoundError, ValidationError
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.pagination import decode_cursor, encode_cursor
from app.shared.text import NUL
from app.shared.types.actor import ActorContext

SKU = "catalog.sku"
MAX_MEDIA = 10  # catalog.md §4
STATUSES = ("DRAFT", "IN_REVIEW", "PUBLISHED", "HIDDEN", "ARCHIVED")
_TARGETS = {"PUBLISH": "PUBLISHED", "HIDE": "HIDDEN", "REPUBLISH": "PUBLISHED", "ARCHIVE": "ARCHIVED"}
_SORTS: dict[str, tuple[Any, bool]] = {
    "-updated_at": (Product.updated_at, True),
    "-created_at": (Product.created_at, True),
    "title": (Product.title, False),
}


def _field(field: str, code: str, **params: object) -> dict[str, Any]:
    return {"field": field, "code": code, "params": params}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class ProductService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        categories: CategoryService,
        pricing: PricingService,
        links: LinkService,
        files: FileService,
    ) -> None:
        self.use = use
        self.audit = audit
        self.categories = categories
        self.pricing = pricing
        self.links = links
        self.files = files

    # ================================================================== o'qish
    async def list_products(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        statuses: Sequence[str],
        category: str | None,
        q: str | None,
        sort: ProductSort,
        limit: int,
        cursor: str | None,
    ) -> ProductList:
        column, descending = _SORTS[sort]
        query = select(Product).where(Product.shop_id == actor.shop_id)
        if statuses:
            query = query.where(Product.status.in_(statuses))
        if category:
            query = query.where(Product.category_code == category)
        if q and q.strip():
            pattern = f"%{_escape_like(q.strip())}%"
            sku_match = exists().where(
                Sku.shop_id == Product.shop_id,
                Sku.product_id == Product.id,
                or_(Sku.sku_code.ilike(pattern, escape="\\"), Sku.mpn.ilike(pattern, escape="\\")),
            )
            query = query.where(
                or_(
                    Product.title.ilike(pattern, escape="\\"),
                    Product.brand.ilike(pattern, escape="\\"),
                    sku_match,
                )
            )
        if cursor:
            query = query.where(self._after(cursor, sort, column, descending))
        order = (column.desc(), Product.id.desc()) if descending else (column.asc(), Product.id.asc())
        rows = list((await db.execute(query.order_by(*order).limit(limit + 1))).scalars())
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            value = getattr(last, column.key)
            next_cursor = encode_cursor(
                {
                    "s": sort,
                    "v": value.isoformat() if isinstance(value, datetime) else value,
                    "id": str(last.id),
                }
            )
        return ProductList(
            items=await self._list_items(db, actor, page), next_cursor=next_cursor, has_more=has_more
        )

    async def counts(self, db: AsyncSession, actor: ActorContext) -> ProductCounts:
        rows = await db.execute(
            select(Product.status, func.count())
            .where(Product.shop_id == actor.shop_id)
            .group_by(Product.status)
        )
        by_status = {status: 0 for status in STATUSES}
        for status, count in rows:
            by_status[status] = count
        return ProductCounts(by_status=by_status, total=sum(by_status.values()))

    async def get(self, db: AsyncSession, actor: ActorContext, product_id: UUID) -> ProductOut:
        return await self._detail(db, actor, await self._product(db, actor, product_id))

    # ================================================================== mahsulot
    async def create(self, db: AsyncSession, actor: ActorContext, data: ProductCreate) -> ProductOut:
        category = await self.categories.usable(db, data.category_code)
        title = data.title.strip()
        if not title:
            raise ValidationError("Title required", fields=[_field("title", "required")])
        product = Product(
            shop_id=actor.shop_id,
            category_code=category.code,
            title=title,
            brand=_clean(data.brand),
            description=_clean(data.description),
            created_by=actor.membership_id,
        )
        db.add(product)
        await db.flush()
        await self.audit.record(
            db, action="catalog.product.created", entity_type=PRODUCT, entity_id=product.id, actor=actor
        )
        codes = [s.sku_code.lower() for s in data.skus]  # SKU kodi katta-kichik harfsiz yagona
        for index, sku_data in enumerate(data.skus):
            if codes.index(sku_data.sku_code.lower()) != index:
                raise ValidationError(
                    "Duplicate SKU code", fields=[_field(f"skus[{index}].sku_code", "not_unique")]
                )
            await self._create_sku(db, actor, product, category, sku_data, field_prefix=f"skus[{index}].")
        return await self._detail(db, actor, product)

    async def update(
        self,
        db: AsyncSession,
        actor: ActorContext,
        product_id: UUID,
        expected_version: int,
        data: ProductUpdate,
    ) -> ProductOut:
        product = await self._product(db, actor, product_id, for_update=True)
        check_version(product.version, expected_version)
        self._ensure_editable(product, "EDIT")
        wanted = data.model_dump(exclude_unset=True)
        for name in ("category_code", "title"):
            if name in wanted and (wanted[name] is None or not str(wanted[name]).strip()):
                raise ValidationError("Field required", fields=[_field(name, "required")])
        if "category_code" in wanted and wanted["category_code"] != product.category_code:
            await self.categories.usable(db, wanted["category_code"])
        for name in ("title", "brand", "description"):
            if name in wanted:
                wanted[name] = _clean(wanted[name])
        changed = {k: v for k, v in wanted.items() if getattr(product, k) != v}
        for key, value in changed.items():
            setattr(product, key, value)
        await db.flush()
        if changed:
            await self.audit.record(
                db,
                action="catalog.product.updated",
                entity_type=PRODUCT,
                entity_id=product.id,
                actor=actor,
                entity_version=product.version,
                diff={"changed": sorted(changed)},
            )
            await self._product_event(db, actor, product, changed_fields=sorted(changed))
        if {"brand", "category_code"} & changed.keys():  # avtomatik bog'lanish brend va toifaga bog'liq
            category = await self._category(db, product)
            if "category_code" in changed:  # boshqa turdagi modelga bog'lanish qolmasin (qo'lda ham)
                await self.links.drop_mismatched(
                    db, actor, await self._skus(db, product), category.spec_category
                )
            for sku in await self._skus(db, product, active_only=True):
                await self.links.auto_link(db, actor, sku, product, category.spec_category)
        return await self._detail(db, actor, product)

    async def transition(
        self, db: AsyncSession, actor: ActorContext, product_id: UUID, command: str, reason: str | None
    ) -> ProductOut:
        product = await self._product(db, actor, product_id, for_update=True)
        if command == "PUBLISH" and product.status == "HIDDEN":
            command = "REPUBLISH"  # bitta "Chiqarish" tugmasi: qoralamadan ham, yashirilgandan ham
        target = _TARGETS[command]
        rule = self.use.validate_transition(PRODUCT, product.status, target, command, actor)
        if target == "PUBLISHED":
            await self._ensure_publishable(db, actor, product)
            product.published_at = utcnow()
        if target == "ARCHIVED":
            product.archived_at = utcnow()
        product.status = target
        await db.flush()
        reason = _clean(reason)
        await self.use.log_transition(db, entity_id=product.id, rule=rule, actor=actor, reason=reason)
        await self.audit.record(
            db,
            action=f"catalog.product.{command.lower()}",
            entity_type=PRODUCT,
            entity_id=product.id,
            actor=actor,
            entity_version=product.version,
            reason=reason,
            diff={"status": {"old": rule.from_status, "new": target}},
        )
        # Sayt keshi va AI qidiruvi (05 §8.1); qayta chiqarish ham "published"
        await write_outbox(
            db,
            schema="catalog",
            event_type=f"catalog.product.{target.lower()}",
            actor=actor,
            shop_id=product.shop_id,
            aggregate_type=PRODUCT,
            aggregate_id=product.id,
            aggregate_version=product.version,
            payload={"product_id": product.id, "product_version": product.version, "status": target},
        )
        return await self._detail(db, actor, product)

    # ================================================================== SKU
    async def add_sku(
        self, db: AsyncSession, actor: ActorContext, product_id: UUID, data: SkuIn
    ) -> ProductOut:
        product = await self._product(db, actor, product_id, for_update=True)
        self._ensure_editable(product, "ADD_SKU")
        category = await self._category(db, product)
        await self._create_sku(db, actor, product, category, data)
        return await self._detail(db, actor, product)

    async def update_sku(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, expected_version: int, data: SkuUpdate
    ) -> ProductOut:
        sku = await self._sku(db, actor, sku_id, for_update=True)
        check_version(sku.version, expected_version)
        product = await self._product(db, actor, sku.product_id)
        self._ensure_editable(product, "EDIT_SKU")
        if sku.status != "ACTIVE":
            raise InvalidTransitionError(
                "SKU is archived", entity=SKU, **{"from": sku.status}, command="EDIT"
            )
        wanted = data.model_dump(exclude_unset=True)
        for name in ("sku_code", "condition", "attributes"):
            if name in wanted and wanted[name] is None:
                raise ValidationError("Field required", fields=[_field(name, "required")])
        for name in ("variant_name", "mpn", "model_name"):
            if name in wanted:
                wanted[name] = _clean(wanted[name])
        if "mpn" in wanted:
            wanted["mpn_normalized"] = normalize_code(wanted["mpn"])
        if "sku_code" in wanted and wanted["sku_code"].lower() != sku.sku_code.lower():
            await self._ensure_code_free(db, sku.shop_id, wanted["sku_code"], "sku_code", exclude_id=sku.id)
        changed = {k: v for k, v in wanted.items() if getattr(sku, k) != v}
        for key, value in changed.items():
            setattr(sku, key, value)
        await self._flush_sku(db, "sku_code")
        if changed:
            await self.audit.record(
                db,
                action="catalog.sku.updated",
                entity_type=SKU,
                entity_id=sku.id,
                actor=actor,
                entity_version=sku.version,
                diff={"changed": sorted(k for k in changed if k != "mpn_normalized")},
            )
            await self._sku_event(db, actor, sku, "updated")
        if {"mpn", "model_name"} & changed.keys():
            await self.links.auto_link(
                db, actor, sku, product, (await self._category(db, product)).spec_category
            )
        return await self._detail(db, actor, product)

    async def archive_sku(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> ProductOut:
        sku = await self._sku(db, actor, sku_id, for_update=True)
        product = await self._product(db, actor, sku.product_id, for_update=True)
        self._ensure_editable(product, "ARCHIVE_SKU")
        if sku.status != "ACTIVE":
            raise InvalidTransitionError(
                "SKU is archived", entity=SKU, **{"from": sku.status}, command="ARCHIVE"
            )
        if product.status in ("PUBLISHED", "HIDDEN"):
            others = [s for s in await self._skus(db, product, active_only=True) if s.id != sku.id]
            if (
                not others
            ):  # saytdagi mahsulot variantsiz qolmasin — avval mahsulotni yashirish/arxivlash kerak
                raise InvalidTransitionError(
                    "Last active SKU of a listed product", entity=SKU, **{"from": "ACTIVE"}, command="ARCHIVE"
                )
        sku.status = "ARCHIVED"
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.sku.archived",
            entity_type=SKU,
            entity_id=sku.id,
            actor=actor,
            entity_version=sku.version,
            diff={"status": {"old": "ACTIVE", "new": "ARCHIVED"}},
        )
        await self._sku_event(db, actor, sku, "archived")
        return await self._detail(db, actor, product)

    # ================================================================== rasmlar
    async def attach_media(
        self, db: AsyncSession, actor: ActorContext, product_id: UUID, file_id: UUID
    ) -> ProductOut:
        product = await self._product(db, actor, product_id, for_update=True)
        self._ensure_editable(product, "ADD_MEDIA")
        assert actor.shop_id is not None
        await self.files.usable(db, actor.shop_id, file_id, "PRODUCT_IMAGE")
        media = await self._media(db, product)
        if any(m.file_id == file_id for m in media):
            return await self._detail(db, actor, product)
        elsewhere = (
            await db.execute(
                select(ProductMedia.product_id).where(
                    ProductMedia.shop_id == product.shop_id, ProductMedia.file_id == file_id
                )
            )
        ).scalar_one_or_none()
        if elsewhere is not None:  # bitta fayl — bitta mahsulot: birida o'chirilsa, boshqasi buzilmasin
            raise FileInUseError("File is attached to another product", product_id=elsewhere)
        if len(media) >= MAX_MEDIA:
            raise ValidationError("Too many images", fields=[_field("media", "max_length", max=MAX_MEDIA)])
        position = max((m.position for m in media), default=-1) + 1
        db.add(
            ProductMedia(shop_id=product.shop_id, product_id=product.id, file_id=file_id, position=position)
        )
        try:
            await db.flush()
        except IntegrityError as exc:  # parallel ulash — tekshiruvdan keyin boshqasi ulgurdi
            if "uq_product_media_shop_id_file_id" in str(exc.orig):
                raise FileInUseError("File is attached to another product") from exc
            raise
        await self.audit.record(
            db, action="catalog.product.media_added", entity_type=PRODUCT, entity_id=product.id, actor=actor
        )
        await self._media_event(db, actor, product, "added")
        return await self._detail(db, actor, product)

    async def remove_media(
        self, db: AsyncSession, actor: ActorContext, product_id: UUID, media_id: UUID
    ) -> ProductOut:
        product = await self._product(db, actor, product_id, for_update=True)
        self._ensure_editable(product, "REMOVE_MEDIA")
        media = await self._media(db, product)
        target = next((m for m in media if m.id == media_id), None)
        if target is None:
            raise NotFoundError("Image not found")
        await db.delete(target)
        await db.flush()
        for position, item in enumerate(m for m in media if m.id != media_id):
            item.position = position
        await self.files.mark_deleted(db, product.shop_id, target.file_id)
        await db.flush()
        await self.audit.record(
            db, action="catalog.product.media_removed", entity_type=PRODUCT, entity_id=product.id, actor=actor
        )
        await self._media_event(db, actor, product, "removed")
        return await self._detail(db, actor, product)

    async def reorder_media(
        self, db: AsyncSession, actor: ActorContext, product_id: UUID, media_ids: list[UUID]
    ) -> ProductOut:
        product = await self._product(db, actor, product_id, for_update=True)
        self._ensure_editable(product, "REORDER_MEDIA")
        media = {m.id: m for m in await self._media(db, product)}
        if len(media_ids) != len(set(media_ids)) or set(media_ids) != set(media):
            raise ValidationError("Order must list every image once", fields=[_field("media_ids", "invalid")])
        for position, media_id in enumerate(media_ids):
            media[media_id].position = position  # 0 — asosiy rasm
        await db.flush()
        await self._media_event(db, actor, product, "reordered")
        return await self._detail(db, actor, product)

    # ================================================================== event'lar (QA 5a F3)
    # Mahsulot matni, variant va rasmlar o'zgarsa — sayt keshi darhol eskiradi (08 §4.1). Faqat ID va kodlar.
    async def _product_event(
        self, db: AsyncSession, actor: ActorContext, product: Product, *, changed_fields: list[str]
    ) -> None:
        await write_outbox(
            db,
            schema="catalog",
            event_type="catalog.product.updated",
            actor=actor,
            shop_id=product.shop_id,
            aggregate_type=PRODUCT,
            aggregate_id=product.id,
            aggregate_version=product.version,
            payload={
                "product_id": product.id,
                "product_version": product.version,
                "changed_fields": changed_fields,
            },
        )

    async def _sku_event(self, db: AsyncSession, actor: ActorContext, sku: Sku, action: str) -> None:
        await write_outbox(
            db,
            schema="catalog",
            event_type="catalog.sku.changed",
            actor=actor,
            shop_id=sku.shop_id,
            aggregate_type=SKU,
            aggregate_id=sku.id,
            aggregate_version=sku.version,
            payload={"sku_id": sku.id, "product_id": sku.product_id, "action": action, "status": sku.status},
        )

    async def _media_event(
        self, db: AsyncSession, actor: ActorContext, product: Product, action: str
    ) -> None:
        """Rasmlar mahsulot tarkibi: mahsulot versiyasi oshadi (event tartibi uchun, 05 §6)."""
        product.updated_at = utcnow()
        await db.flush()
        await write_outbox(
            db,
            schema="catalog",
            event_type="catalog.media.changed",
            actor=actor,
            shop_id=product.shop_id,
            aggregate_type=PRODUCT,
            aggregate_id=product.id,
            aggregate_version=product.version,
            payload={"product_id": product.id, "product_version": product.version, "action": action},
        )

    # ================================================================== import (5c, 18 §6)
    async def import_create(
        self, db: AsyncSession, actor: ActorContext, category: Category, data: ProductCreate
    ) -> tuple[Product, Sku]:
        """Import qatori → qoralama kartochka va bitta SKU (saytga avtomatik chiqmaydi). Javob kartochkasi
        yig'ilmaydi — bo'lakda 500 qator."""
        product = Product(
            shop_id=actor.shop_id,
            category_code=category.code,
            title=data.title.strip(),
            brand=_clean(data.brand),
            description=_clean(data.description),
            created_by=actor.membership_id,
        )
        db.add(product)
        await db.flush()
        await self.audit.record(
            db, action="catalog.product.created", entity_type=PRODUCT, entity_id=product.id, actor=actor
        )
        sku = await self._create_sku(db, actor, product, category, data.skus[0], field_prefix="skus[0].")
        return product, sku

    async def import_update(
        self,
        db: AsyncSession,
        actor: ActorContext,
        product: Product,
        sku: Sku,
        product_changes: dict[str, Any],
        sku_changes: dict[str, Any],
    ) -> bool:
        """Mavjud SKU va kartochka yangilanadi (faqat fayldagi maydonlar). Qoida va event'lar — `update` va
        `update_sku` dagidek. True — nimadir o'zgardi."""
        self._ensure_editable(product, "EDIT")
        if sku.status != "ACTIVE":
            raise InvalidTransitionError(
                "SKU is archived", entity=SKU, **{"from": sku.status}, command="EDIT"
            )
        if "category_code" in product_changes and product_changes["category_code"] != product.category_code:
            await self.categories.usable(db, product_changes["category_code"])
        product_diff = {k: v for k, v in product_changes.items() if getattr(product, k) != v}
        if "mpn" in sku_changes:
            sku_changes = {**sku_changes, "mpn_normalized": normalize_code(sku_changes["mpn"])}
        sku_diff = {k: v for k, v in sku_changes.items() if getattr(sku, k) != v}
        for key, value in product_diff.items():
            setattr(product, key, value)
        for key, value in sku_diff.items():
            setattr(sku, key, value)
        await db.flush()
        if product_diff:
            await self.audit.record(
                db,
                action="catalog.product.updated",
                entity_type=PRODUCT,
                entity_id=product.id,
                actor=actor,
                entity_version=product.version,
                diff={"changed": sorted(product_diff)},
            )
            await self._product_event(db, actor, product, changed_fields=sorted(product_diff))
        if sku_diff:
            await self.audit.record(
                db,
                action="catalog.sku.updated",
                entity_type=SKU,
                entity_id=sku.id,
                actor=actor,
                entity_version=sku.version,
                diff={"changed": sorted(k for k in sku_diff if k != "mpn_normalized")},
            )
            await self._sku_event(db, actor, sku, "updated")
        category = await self._category(db, product)
        if "category_code" in product_diff:
            await self.links.drop_mismatched(db, actor, await self._skus(db, product), category.spec_category)
        if {"brand", "category_code"} & product_diff.keys() or {"mpn", "model_name"} & sku_diff.keys():
            await self.links.auto_link(db, actor, sku, product, category.spec_category)
        return bool(product_diff or sku_diff)

    # ================================================================== ichki
    async def _create_sku(
        self,
        db: AsyncSession,
        actor: ActorContext,
        product: Product,
        category: Category,
        data: SkuIn,
        *,
        field_prefix: str = "",
    ) -> Sku:
        await self._ensure_code_free(db, product.shop_id, data.sku_code, f"{field_prefix}sku_code")
        sku = Sku(
            shop_id=product.shop_id,
            product_id=product.id,
            sku_code=data.sku_code,
            variant_name=_clean(data.variant_name),
            condition=data.condition,
            mpn=_clean(data.mpn),
            mpn_normalized=normalize_code(data.mpn),
            model_name=_clean(data.model_name),
            attributes=dict(data.attributes),
            warranty_months=data.warranty_months,
        )
        db.add(sku)
        await self._flush_sku(db, f"{field_prefix}sku_code")
        await self.audit.record(
            db, action="catalog.sku.created", entity_type=SKU, entity_id=sku.id, actor=actor
        )
        await self._sku_event(db, actor, sku, "created")
        if data.price is not None:
            await self.pricing.apply_price(db, actor, sku, data.price, 0)
        await self.links.auto_link(db, actor, sku, product, category.spec_category)
        return sku

    async def _ensure_code_free(
        self, db: AsyncSession, shop_id: UUID, code: str, field: str, *, exclude_id: UUID | None = None
    ) -> None:
        """BL-011: SKU kodi shop ichida yagona, katta-kichik harfsiz ("ABC-1" = "abc-1"). Parallel
        so'rovlar shu kod uchun tranzaksiya qulfida navbatga turadi — ikkalasi ham o'tib ketmaydi."""
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"catalog.sku_code:{shop_id}:{code.lower()}"},
        )
        query = select(Sku.id).where(Sku.shop_id == shop_id, func.lower(Sku.sku_code) == code.lower())
        if exclude_id is not None:
            query = query.where(Sku.id != exclude_id)
        if (await db.execute(query)).first() is not None:
            raise ValidationError("SKU code already used", fields=[_field(field, "not_unique")])

    async def _flush_sku(self, db: AsyncSession, field: str) -> None:
        try:
            await db.flush()
        except IntegrityError as exc:
            if "uq_skus_shop_id_sku_code" in str(exc.orig):  # BL-011: takror kod
                raise ValidationError("SKU code already used", fields=[_field(field, "not_unique")]) from exc
            raise

    async def _ensure_publishable(self, db: AsyncSession, actor: ActorContext, product: Product) -> None:
        problems: list[dict[str, Any]] = []
        if not product.title.strip():
            problems.append(_field("title", "required"))
        active = await self._skus(db, product, active_only=True)
        if not active:
            problems.append(_field("skus", "required"))
        else:
            prices = await self.pricing.active_prices(db, actor.shop_id, [s.id for s in active])
            if not prices:
                problems.append(_field("price", "required"))
            elif any(p.version.currency == "USD" for p in prices.values()):
                if await self.pricing.current_rate(db, actor.shop_id) is None:
                    problems.append(
                        _field("exchange_rate", "required")
                    )  # dollar narxini so'mda ko'rsatib bo'lmaydi
        if problems:
            raise ValidationError("Product is not ready to publish", fields=problems)

    def _ensure_editable(self, product: Product, command: str) -> None:
        if product.status == "ARCHIVED":  # arxivdagi mahsulot faqat tarix uchun (BL-014)
            raise InvalidTransitionError(
                "Product is archived", entity=PRODUCT, **{"from": "ARCHIVED"}, command=command
            )

    def _after(self, cursor: str, sort: str, column: Any, descending: bool) -> ColumnElement[bool]:
        """Cursor klientdan keladi — har shakli tekshiriladi (buzilgani 500 emas, 422)."""
        raw = decode_cursor(cursor)
        raw_value, raw_id = raw.get("v"), raw.get("id")
        try:
            if raw.get("s") != sort or not isinstance(raw_value, str) or not isinstance(raw_id, str):
                raise ValueError("cursor shape")
            if NUL in raw_value:
                raise ValueError("cursor value")
            value: Any = raw_value
            if sort != "title":
                value = datetime.fromisoformat(raw_value)
                if value.tzinfo is None or value.year < 2000:
                    raise ValueError("cursor time")
            last_id = UUID(raw_id)
        except ValueError as exc:
            raise ValidationError("Cursor is invalid", fields=[_field("cursor", "invalid_format")]) from exc
        key = tuple_(column, Product.id)
        return key < tuple_(value, last_id) if descending else key > tuple_(value, last_id)

    async def _product(
        self, db: AsyncSession, actor: ActorContext, product_id: UUID, *, for_update: bool = False
    ) -> Product:
        query = select(Product).where(Product.id == product_id, Product.shop_id == actor.shop_id)
        product = (await db.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()
        if product is None:
            raise NotFoundError("Product not found")
        return product

    async def _sku(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, *, for_update: bool = False
    ) -> Sku:
        query = select(Sku).where(Sku.id == sku_id, Sku.shop_id == actor.shop_id)
        sku = (await db.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()
        if sku is None:
            raise NotFoundError("SKU not found")
        return sku

    async def _category(self, db: AsyncSession, product: Product) -> Category:
        category = await db.get(Category, product.category_code)
        assert category is not None  # FK
        return category

    async def _skus(self, db: AsyncSession, product: Product, *, active_only: bool = False) -> list[Sku]:
        query = select(Sku).where(Sku.shop_id == product.shop_id, Sku.product_id == product.id)
        if active_only:
            query = query.where(Sku.status == "ACTIVE")
        # populate_existing: flush'dan keyin server yangilagan ustunlar (updated_at) qayta o'qilsin
        query = query.order_by(Sku.created_at, Sku.id).execution_options(populate_existing=True)
        return list((await db.execute(query)).scalars())

    async def _media(self, db: AsyncSession, product: Product) -> list[ProductMedia]:
        rows = await db.execute(
            select(ProductMedia)
            .where(ProductMedia.shop_id == product.shop_id, ProductMedia.product_id == product.id)
            .order_by(ProductMedia.position, ProductMedia.created_at)
        )
        return list(rows.scalars())

    def _sku_out(
        self, sku: Sku, price: ActivePrice | None, rate: ExchangeRate | None, link: LinkView | None
    ) -> SkuOut:
        return SkuOut(
            id=sku.id,
            product_id=sku.product_id,
            sku_code=sku.sku_code,
            variant_name=sku.variant_name,
            condition=sku.condition,
            mpn=sku.mpn,
            model_name=sku.model_name,
            attributes=sku.attributes,
            warranty_months=sku.warranty_months,
            status=sku.status,
            price=price_out(price, rate) if price else None,
            spec_link=link_out(link) if link else None,
            spec_autolink_blocked=sku.spec_autolink_blocked,
            created_at=sku.created_at,
            updated_at=sku.updated_at,
            version=sku.version,
        )

    async def _detail(self, db: AsyncSession, actor: ActorContext, product: Product) -> ProductOut:
        await db.refresh(product)
        skus = await self._skus(db, product)
        sku_ids = [s.id for s in skus]
        prices = await self.pricing.active_prices(db, actor.shop_id, sku_ids)
        links = await self.links.links_for(db, actor.shop_id, sku_ids)
        rate = await self.pricing.current_rate(db, actor.shop_id)
        media = await self._media(db, product)
        files = await self.files.by_ids(db, product.shop_id, [m.file_id for m in media])
        category = await self._category(db, product)
        return ProductOut(
            id=product.id,
            category_code=product.category_code,
            brand=product.brand,
            title=product.title,
            description=product.description,
            status=product.status,
            published_at=product.published_at,
            archived_at=product.archived_at,
            spec_category=category.spec_category,
            skus=[self._sku_out(s, prices.get(s.id), rate, links.get(s.id)) for s in skus],
            media=[
                MediaOut(
                    id=m.id,
                    file_id=m.file_id,
                    url=self.files.url_for(files[m.file_id])[0],
                    position=m.position,
                )
                for m in media
                if m.file_id in files
            ],
            created_at=product.created_at,
            updated_at=product.updated_at,
            version=product.version,
        )

    async def _list_items(
        self, db: AsyncSession, actor: ActorContext, page: list[Product]
    ) -> list[ProductListItem]:
        if not page:
            return []
        product_ids = [p.id for p in page]
        skus = list(
            (
                await db.execute(
                    select(Sku).where(Sku.shop_id == actor.shop_id, Sku.product_id.in_(product_ids))
                )
            ).scalars()
        )
        by_product: dict[UUID, list[Sku]] = defaultdict(list)
        for sku in skus:
            by_product[sku.product_id].append(sku)
        active_ids = [s.id for s in skus if s.status == "ACTIVE"]
        prices = await self.pricing.active_prices(db, actor.shop_id, active_ids)
        rate = await self.pricing.current_rate(db, actor.shop_id)
        first_media = await db.execute(
            select(ProductMedia)
            .where(ProductMedia.shop_id == actor.shop_id, ProductMedia.product_id.in_(product_ids))
            .order_by(ProductMedia.product_id, ProductMedia.position, ProductMedia.created_at)
            .ext(distinct_on(ProductMedia.product_id))
        )
        media_by_product = {m.product_id: m for m in first_media.scalars()}
        assert actor.shop_id is not None
        files = await self.files.by_ids(db, actor.shop_id, [m.file_id for m in media_by_product.values()])
        items = []
        for product in page:
            product_skus = by_product.get(product.id, [])
            active = [s for s in product_skus if s.status == "ACTIVE"]
            uzs = [uzs_amount(p.version, rate) for s in active if (p := prices.get(s.id)) is not None]
            known = [value for value in uzs if value is not None]
            media = media_by_product.get(product.id)
            image = files.get(media.file_id) if media else None
            items.append(
                ProductListItem(
                    id=product.id,
                    category_code=product.category_code,
                    brand=product.brand,
                    title=product.title,
                    status=product.status,
                    sku_count=len(product_skus),
                    active_sku_count=len(active),
                    price_from_uzs_minor=min(known) if known else None,
                    image_url=self.files.url_for(image)[0] if image else None,
                    updated_at=product.updated_at,
                    version=product.version,
                )
            )
        return items
