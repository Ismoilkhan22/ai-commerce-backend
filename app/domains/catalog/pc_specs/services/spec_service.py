"""Texnik ma'lumotlar kutubxonasi — platforma paneli (engineering/17 §10, DEC-011, DEC-120).

"Ikki ko'z": har yangi model va har o'zgarish avval taklif (PENDING), uni BOSHQA odam tasdiqlaydi
(`SELF_APPROVAL_NOT_ALLOWED`). Tasdiqgacha eski ma'lumot ishlayveradi:

    Yangi model:  spec DRAFT + 1-versiya PENDING ──(boshqa odam tasdiqladi)──▶ spec APPROVED
    O'zgarish:    spec APPROVED + yangi versiya PENDING ──(tasdiqlandi)──▶ ma'lumot ko'chadi, version oshadi
                                                         ──(rad etildi)──▶ spec o'zgarmaydi

Shop so'rovlari ham shu yerda hal qilinadi: so'ralgan SKU topilgan modelga bog'lanadi (shop kontekstida).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pc_specs.attributes import validate_attributes
from app.domains.catalog.pc_specs.models.orm import (
    ReferenceHardwareSpec,
    ReferenceHardwareSpecVersion,
    SkuSpecLink,
    SpecRequest,
)
from app.domains.catalog.pc_specs.normalize import normalize_brand, normalize_code
from app.domains.catalog.pc_specs.schemas import (
    HardwareSpecDetail,
    HardwareSpecIn,
    HardwareSpecList,
    PlatformSpecRequestList,
    PlatformSpecRequestOut,
    SpecRequestOut,
    SpecReviewQueue,
    SpecReviewQueueItem,
    SpecVersionIn,
    SpecVersionOut,
)
from app.domains.catalog.pc_specs.services.link_service import spec_out
from app.domains.catalog.products.models.orm import Category, Product, Sku
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Shop
from app.platform.staff.models.orm import Principal
from app.shared.clock import utcnow
from app.shared.db.session import set_identity_context
from app.shared.errors.base import (
    InvalidTransitionError,
    NotFoundError,
    SelfApprovalError,
    ValidationError,
)
from app.shared.types.actor import ActorContext

SPEC = "catalog.hardware_spec"
REQUEST = "catalog.spec_request"


def _field_error(field: str, code: str, message: str) -> ValidationError:
    return ValidationError(message, fields=[{"field": field, "code": code, "params": {}}])


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SpecLibraryService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    # ================================================================== kutubxona: o'qish
    async def list_specs(
        self,
        db: AsyncSession,
        *,
        q: str | None,
        category: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> HardwareSpecList:
        query = select(ReferenceHardwareSpec)
        if category:
            query = query.where(ReferenceHardwareSpec.category == category)
        if status:
            query = query.where(ReferenceHardwareSpec.status == status)
        if q and q.strip():
            pattern = f"%{_escape_like(q.strip())}%"
            query = query.where(
                or_(
                    ReferenceHardwareSpec.brand.ilike(pattern, escape="\\"),
                    ReferenceHardwareSpec.model_name.ilike(pattern, escape="\\"),
                    ReferenceHardwareSpec.mpn.ilike(pattern, escape="\\"),
                )
            )
        total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        rows = list(
            (
                await db.execute(
                    query.order_by(
                        ReferenceHardwareSpec.category,
                        ReferenceHardwareSpec.brand,
                        ReferenceHardwareSpec.model_name,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        pending = await self._pending_versions(db, [s.id for s in rows])
        return HardwareSpecList(items=[spec_out(s, pending.get(s.id)) for s in rows], total=total)

    async def get(self, db: AsyncSession, spec_id: UUID) -> HardwareSpecDetail:
        spec = await self._spec(db, spec_id)
        versions = list(
            (
                await db.execute(
                    select(ReferenceHardwareSpecVersion)
                    .where(ReferenceHardwareSpecVersion.spec_id == spec_id)
                    .order_by(ReferenceHardwareSpecVersion.version.desc())
                )
            ).scalars()
        )
        people: list[UUID | None] = [v.proposed_by for v in versions]
        names = await self._names(db, people + [v.reviewed_by for v in versions])
        pending = next((v.version for v in versions if v.status == "PENDING"), None)
        return HardwareSpecDetail(
            **spec_out(spec, pending).model_dump(),
            versions=[
                SpecVersionOut(
                    version=v.version,
                    brand=v.brand,
                    model_name=v.model_name,
                    variant_key=v.variant_key,
                    mpn=v.mpn,
                    attributes=v.attributes,
                    source_url=v.source_url,
                    status=v.status,
                    proposed_by=v.proposed_by,
                    proposed_by_name=names.get(v.proposed_by),
                    proposed_at=v.proposed_at,
                    reviewed_by=v.reviewed_by,
                    reviewed_by_name=names.get(v.reviewed_by) if v.reviewed_by else None,
                    reviewed_at=v.reviewed_at,
                    review_note=v.review_note,
                )
                for v in versions
            ],
        )

    async def review_queue(self, db: AsyncSession) -> SpecReviewQueue:
        rows = list(
            (
                await db.execute(
                    select(ReferenceHardwareSpecVersion, ReferenceHardwareSpec)
                    .join(
                        ReferenceHardwareSpec,
                        ReferenceHardwareSpec.id == ReferenceHardwareSpecVersion.spec_id,
                    )
                    .where(ReferenceHardwareSpecVersion.status == "PENDING")
                    .order_by(ReferenceHardwareSpecVersion.proposed_at)  # eng uzoq kutayotgan birinchi
                )
            ).all()
        )
        names = await self._names(db, [v.proposed_by for v, _ in rows])
        return SpecReviewQueue(
            items=[
                SpecReviewQueueItem(
                    spec_id=spec.id,
                    category=spec.category,
                    brand=version.brand,
                    model_name=version.model_name,
                    variant_key=version.variant_key,
                    version=version.version,
                    is_new=spec.status == "DRAFT",
                    proposed_by=version.proposed_by,
                    proposed_by_name=names.get(version.proposed_by),
                    proposed_at=version.proposed_at,
                )
                for version, spec in rows
            ]
        )

    # ================================================================== kutubxona: yozish
    async def create(self, db: AsyncSession, actor: ActorContext, data: HardwareSpecIn) -> HardwareSpecDetail:
        values = self._prepared(data.category, data)
        await self._ensure_unique(db, data.category, values, exclude_id=None)
        spec = ReferenceHardwareSpec(
            category=data.category, status="DRAFT", version=1, created_by=actor.actor_id, **values
        )
        db.add(spec)
        await self._flush_unique(db)
        db.add(self._version_row(spec.id, 1, values, actor))
        await db.flush()
        await self.audit.record(
            db, action="catalog.spec.proposed", entity_type=SPEC, entity_id=spec.id, actor=actor
        )
        return await self.get(db, spec.id)

    async def propose(
        self, db: AsyncSession, actor: ActorContext, spec_id: UUID, data: SpecVersionIn
    ) -> HardwareSpecDetail:
        spec = await self._spec(db, spec_id, for_update=True)
        if spec.status == "RETIRED":
            raise InvalidTransitionError(
                "Spec is retired", entity=SPEC, **{"from": "RETIRED"}, command="PROPOSE"
            )
        if spec.id in await self._pending_versions(db, [spec.id]):
            raise InvalidTransitionError(
                "A pending change already exists", entity=SPEC, **{"from": "PENDING"}, command="PROPOSE"
            )
        values = self._prepared(spec.category, data)
        await self._ensure_unique(db, spec.category, values, exclude_id=spec.id)
        last = (
            await db.execute(
                select(func.max(ReferenceHardwareSpecVersion.version)).where(
                    ReferenceHardwareSpecVersion.spec_id == spec.id
                )
            )
        ).scalar_one()
        number = (last or 0) + 1
        db.add(self._version_row(spec.id, number, values, actor))
        if spec.status == "DRAFT":
            # Hali tasdiqlanmagan model — kartochkada oxirgi taklif ko'rinadi (unga hech narsa bog'lanmagan)
            for key, value in values.items():
                setattr(spec, key, value)
        await self._flush_unique(db)
        await self.audit.record(
            db,
            action="catalog.spec.proposed",
            entity_type=SPEC,
            entity_id=spec.id,
            actor=actor,
            diff={"version": {"new": number}},
        )
        return await self.get(db, spec.id)

    async def approve(
        self, db: AsyncSession, actor: ActorContext, spec_id: UUID, number: int
    ) -> HardwareSpecDetail:
        spec = await self._spec(db, spec_id, for_update=True)
        version = await self._version(db, spec_id, number)
        if version.proposed_by == actor.actor_id:
            raise SelfApprovalError("Proposer cannot approve own change")  # "ikki ko'z" (17 §10)
        values = self._prepared(
            spec.category,
            SpecVersionIn(
                brand=version.brand,
                model_name=version.model_name,
                variant_key=version.variant_key,
                mpn=version.mpn,
                attributes=version.attributes,
                source_url=version.source_url,
            ),
        )
        await self._ensure_unique(db, spec.category, values, exclude_id=spec.id)
        now = utcnow()
        for key, value in values.items():
            setattr(spec, key, value)
        spec.version = number
        spec.status = "APPROVED"
        spec.approved_by, spec.approved_at = actor.actor_id, now
        version.status, version.reviewed_by, version.reviewed_at = "APPROVED", actor.actor_id, now
        await self._flush_unique(db)
        await self.audit.record(
            db,
            action="catalog.spec.approved",
            entity_type=SPEC,
            entity_id=spec.id,
            actor=actor,
            diff={"version": {"new": number}},
        )
        return await self.get(db, spec.id)

    async def reject(
        self, db: AsyncSession, actor: ActorContext, spec_id: UUID, number: int, note: str
    ) -> HardwareSpecDetail:
        await self._spec(db, spec_id, for_update=True)
        version = await self._version(db, spec_id, number)
        version.status, version.reviewed_by, version.reviewed_at = "REJECTED", actor.actor_id, utcnow()
        version.review_note = note.strip()
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.spec.rejected",
            entity_type=SPEC,
            entity_id=spec_id,
            actor=actor,
            reason=version.review_note,
            diff={"version": {"new": number}},
        )
        return await self.get(db, spec_id)

    async def retire(
        self, db: AsyncSession, actor: ActorContext, spec_id: UUID, reason: str
    ) -> HardwareSpecDetail:
        """Eskirgan model: yangi bog'lanish yo'q, eskilari qoladi. Kutayotgan taklif rad etiladi."""
        spec = await self._spec(db, spec_id, for_update=True)
        if spec.status == "RETIRED":
            raise InvalidTransitionError(
                "Spec is retired", entity=SPEC, **{"from": "RETIRED"}, command="RETIRE"
            )
        now = utcnow()
        pending = (
            await db.execute(
                select(ReferenceHardwareSpecVersion).where(
                    ReferenceHardwareSpecVersion.spec_id == spec_id,
                    ReferenceHardwareSpecVersion.status == "PENDING",
                )
            )
        ).scalars()
        for version in pending:
            version.status, version.reviewed_by, version.reviewed_at = "REJECTED", actor.actor_id, now
            version.review_note = reason.strip()
        old_status = spec.status
        spec.status = "RETIRED"
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.spec.retired",
            entity_type=SPEC,
            entity_id=spec_id,
            actor=actor,
            reason=reason.strip(),
            diff={"status": {"old": old_status, "new": "RETIRED"}},
        )
        return await self.get(db, spec_id)

    # ================================================================== shop so'rovlari navbati
    async def list_requests(
        self, db: AsyncSession, *, status: str | None, limit: int, offset: int
    ) -> PlatformSpecRequestList:
        """Hamma shoplar bo'yicha bitta navbat (spec_requests'da RLS yo'q — platforma ro'yxati).
        Platforma faqat model nomlarini ko'radi, shopning boshqa ma'lumotini emas (10 §9)."""
        query = select(SpecRequest, Shop).join(Shop, Shop.id == SpecRequest.shop_id)
        count = select(func.count()).select_from(SpecRequest)
        if status:
            query = query.where(SpecRequest.status == status)
            count = count.where(SpecRequest.status == status)
        total = (await db.execute(count)).scalar_one()
        rows = list(
            (await db.execute(query.order_by(SpecRequest.created_at).limit(limit).offset(offset))).all()
        )
        sku_categories = await self._sku_categories(
            db, [(request.shop_id, request.sku_id) for request, _ in rows if request.sku_id is not None]
        )
        return PlatformSpecRequestList(
            items=[
                PlatformSpecRequestOut(
                    **SpecRequestOut.model_validate(request).model_dump(),
                    shop_id=shop.id,
                    shop_name=shop.name,
                    shop_slug=shop.slug,
                    sku_spec_category=sku_categories.get(request.sku_id) if request.sku_id else None,
                )
                for request, shop in rows
            ],
            total=total,
        )

    async def resolve_request(
        self, db: AsyncSession, actor: ActorContext, request_id: UUID, spec_id: UUID
    ) -> SpecRequestOut:
        request = await self._request(db, request_id)
        spec = await db.get(ReferenceHardwareSpec, spec_id)
        if spec is None or spec.status != "APPROVED" or spec.category != request.category:
            raise _field_error("spec_id", "invalid", "Spec must be approved and of the requested category")
        if request.sku_id is not None:
            # SKU so'rovdan keyin o'zgargan bo'lishi mumkin: arxivlangan yoki mahsulot toifasi almashgan
            await self._linkable_sku(db, request.shop_id, request.sku_id, spec)
        request.status, request.resolved_spec_id = "RESOLVED", spec.id
        request.resolved_by, request.resolved_at = actor.actor_id, utcnow()
        await db.flush()
        on_shop = replace(actor, shop_id=request.shop_id)  # jurnal shopga bog'lanadi (business/15 §4)
        if request.sku_id is not None:
            await self._link_requested_sku(db, on_shop, request.shop_id, request.sku_id, spec.id)
        await self.audit.record(
            db,
            action="catalog.spec_request.resolved",
            entity_type=REQUEST,
            entity_id=request.id,
            actor=on_shop,
        )
        return SpecRequestOut.model_validate(request)

    async def reject_request(
        self, db: AsyncSession, actor: ActorContext, request_id: UUID, note: str
    ) -> SpecRequestOut:
        request = await self._request(db, request_id)
        request.status, request.resolution_note = "REJECTED", note.strip()
        request.resolved_by, request.resolved_at = actor.actor_id, utcnow()
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.spec_request.rejected",
            entity_type=REQUEST,
            entity_id=request.id,
            actor=replace(actor, shop_id=request.shop_id),
            reason=request.resolution_note,
        )
        return SpecRequestOut.model_validate(request)

    # ================================================================== ichki
    def _prepared(self, category: str, data: SpecVersionIn | HardwareSpecIn) -> dict[str, Any]:
        model_normalized = normalize_code(data.model_name)
        if not model_normalized:
            raise _field_error("model_name", "invalid", "Model name must contain letters or digits")
        brand_normalized = normalize_brand(data.brand)
        if not brand_normalized:
            raise _field_error("brand", "invalid", "Brand must contain letters or digits")
        mpn = (data.mpn or "").strip() or None
        return {
            "brand": data.brand.strip(),
            "brand_normalized": brand_normalized,
            "model_name": data.model_name.strip(),
            "model_normalized": model_normalized,
            "variant_key": normalize_code(data.variant_key) or "",
            "mpn": mpn,
            "mpn_normalized": normalize_code(mpn),
            "attributes": validate_attributes(category, data.attributes),
            "source_url": data.source_url,
        }

    def _version_row(
        self, spec_id: UUID, number: int, values: dict[str, Any], actor: ActorContext
    ) -> ReferenceHardwareSpecVersion:
        assert actor.actor_id is not None
        return ReferenceHardwareSpecVersion(
            spec_id=spec_id,
            version=number,
            brand=values["brand"],
            model_name=values["model_name"],
            variant_key=values["variant_key"],
            mpn=values["mpn"],
            attributes=values["attributes"],
            source_url=values["source_url"],
            proposed_by=actor.actor_id,
        )

    async def _ensure_unique(
        self, db: AsyncSession, category: str, values: dict[str, Any], *, exclude_id: UUID | None
    ) -> None:
        """Bitta model ikki marta kiritilmaydi: brend (katta-kichik harfsiz) + model + variant; MPN yagona.
        Eskirgan (RETIRED) model hisobga olinmaydi — uni qayta kiritish mumkin (qaytarish amali yo'q).
        Parallel kiritishni bazadagi qisman unikal indeks ushlaydi (`_flush_unique`)."""
        query = select(ReferenceHardwareSpec.id).where(
            ReferenceHardwareSpec.category == category,
            ReferenceHardwareSpec.brand_normalized == values["brand_normalized"],
            ReferenceHardwareSpec.model_normalized == values["model_normalized"],
            ReferenceHardwareSpec.variant_key == values["variant_key"],
            ReferenceHardwareSpec.status != "RETIRED",
        )
        if exclude_id is not None:
            query = query.where(ReferenceHardwareSpec.id != exclude_id)
        if (await db.execute(query)).first() is not None:
            raise _field_error("model_name", "not_unique", "Model already in the library")
        if values["mpn_normalized"]:
            mpn_query = select(ReferenceHardwareSpec.id).where(
                ReferenceHardwareSpec.mpn_normalized == values["mpn_normalized"],
                ReferenceHardwareSpec.status != "RETIRED",
            )
            if exclude_id is not None:
                mpn_query = mpn_query.where(ReferenceHardwareSpec.id != exclude_id)
            if (await db.execute(mpn_query)).first() is not None:
                raise _field_error("mpn", "not_unique", "MPN already in the library")

    async def _flush_unique(self, db: AsyncSession) -> None:
        try:
            await db.flush()
        except IntegrityError as exc:  # parallel kiritish — tekshiruvdan keyin boshqasi ulgurdi
            text = str(exc.orig)
            field = "mpn" if "mpn_normalized" in text else "model_name"
            raise _field_error(field, "not_unique", "Model already in the library") from exc

    async def _linkable_sku(
        self, db: AsyncSession, shop_id: UUID, sku_id: UUID, spec: ReferenceHardwareSpec
    ) -> Sku:
        """So'ralgan SKU hali bog'lanadigan holatda va xuddi shu turdagi (M02 §4.4: boshqa turdagi model
        bog'lanmaydi) — shop panelidagi `PUT /skus/{id}/spec-link` bilan bir xil qoida."""
        await set_identity_context(db, shop_id=shop_id)  # skus RLS: shu shop konteksti
        row = (
            await db.execute(
                select(Sku, Product, Category)
                .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
                .join(Category, Category.code == Product.category_code)
                .where(Sku.id == sku_id, Sku.shop_id == shop_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("SKU not found")
        sku, product, category = row
        if sku.status != "ACTIVE" or product.status == "ARCHIVED":
            raise InvalidTransitionError(
                "SKU is archived", entity="catalog.sku", **{"from": "ARCHIVED"}, command="RESOLVE"
            )
        if category.spec_category != spec.category:
            raise _field_error("spec_id", "invalid", "Spec type does not match the SKU's product category")
        return sku

    async def _sku_categories(
        self, db: AsyncSession, pairs: Sequence[tuple[UUID, UUID]]
    ) -> dict[UUID, str | None]:
        """So'ralgan SKU'lar mahsulotining hozirgi turi — har shop o'z RLS kontekstida o'qiladi."""
        by_shop: dict[UUID, list[UUID]] = defaultdict(list)
        for shop_id, sku_id in pairs:
            by_shop[shop_id].append(sku_id)
        result: dict[UUID, str | None] = {}
        for shop_id, sku_ids in by_shop.items():
            await set_identity_context(db, shop_id=shop_id)
            rows = await db.execute(
                select(Sku.id, Category.spec_category)
                .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
                .join(Category, Category.code == Product.category_code)
                .where(Sku.shop_id == shop_id, Sku.id.in_(sku_ids))
            )
            result.update({key: value for key, value in rows})
        return result

    async def _link_requested_sku(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, sku_id: UUID, spec_id: UUID
    ) -> None:
        await set_identity_context(db, shop_id=shop_id)  # sku_spec_links RLS: shu shop konteksti
        sku = (await db.execute(select(Sku).where(Sku.id == sku_id, Sku.shop_id == shop_id))).scalar_one()
        if await db.get(SkuSpecLink, (shop_id, sku_id)) is not None:
            return  # shop allaqachon o'zi bog'lagan — tegmaymiz
        db.add(SkuSpecLink(shop_id=shop_id, sku_id=sku_id, spec_id=spec_id, method="MANUAL"))
        sku.spec_autolink_blocked = False  # platforma ataylab bog'ladi — xodim tanlovi kabi
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.sku.spec_linked",
            entity_type="catalog.sku",
            entity_id=sku_id,
            actor=actor,
            diff={"method": {"new": "MANUAL"}},
        )

    async def _pending_versions(self, db: AsyncSession, spec_ids: list[UUID]) -> dict[UUID, int]:
        if not spec_ids:
            return {}
        rows = await db.execute(
            select(ReferenceHardwareSpecVersion.spec_id, ReferenceHardwareSpecVersion.version).where(
                ReferenceHardwareSpecVersion.spec_id.in_(spec_ids),
                ReferenceHardwareSpecVersion.status == "PENDING",
            )
        )
        return {key: value for key, value in rows}

    async def _names(self, db: AsyncSession, principal_ids: Sequence[UUID | None]) -> dict[UUID, str]:
        ids = {pid for pid in principal_ids if pid is not None}
        if not ids:
            return {}
        rows = await db.execute(select(Principal.id, Principal.full_name).where(Principal.id.in_(ids)))
        return {key: value for key, value in rows}

    async def _spec(
        self, db: AsyncSession, spec_id: UUID, *, for_update: bool = False
    ) -> ReferenceHardwareSpec:
        # populate_existing: flush'dan keyin server yangilagan ustunlar (updated_at) qayta o'qilsin
        spec = await db.get(
            ReferenceHardwareSpec, spec_id, with_for_update=for_update, populate_existing=True
        )
        if spec is None:
            raise NotFoundError("Spec not found")
        return spec

    async def _version(self, db: AsyncSession, spec_id: UUID, number: int) -> ReferenceHardwareSpecVersion:
        version = await db.get(ReferenceHardwareSpecVersion, (spec_id, number), with_for_update=True)
        if version is None:
            raise NotFoundError("Spec version not found")
        if version.status != "PENDING":
            raise InvalidTransitionError(
                "Version already reviewed",
                entity="catalog.hardware_spec_version",
                **{"from": version.status},
                command="REVIEW",
            )
        return version

    async def _request(self, db: AsyncSession, request_id: UUID) -> SpecRequest:
        request = await db.get(SpecRequest, request_id, with_for_update=True)
        if request is None:
            raise NotFoundError("Spec request not found")
        if request.status != "OPEN":
            raise InvalidTransitionError(
                "Request already handled", entity=REQUEST, **{"from": request.status}, command="RESOLVE"
            )
        return request
