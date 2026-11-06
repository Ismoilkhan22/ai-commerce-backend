"""Katalog importi (S1-06, 18-catalog-import.md, db/catalog_import.md, DEC-140 — taklif).

    yuklash (arzon tekshiruv) ──▶ o'qish (fon, bir marta, alohida thread — QA F1) ──▶ moslash
    ──▶ sinov (fon, 1000 qatorlik bo'laklar, hech narsa yozilmaydi) ──▶ ko'rib chiqish
    ──▶ tasdiq ──▶ yozish (fon, 500 qatorlik bo'laklar: qoralama mahsulot, SKU, narx versiyasi, bog'lash)
    ──▶ qoldiq qatorlari "kutish zali"ga ──▶ catalog.import.completed
    ──▶ commerce qo'llaydi (kirim / tuzatish)
    ──▶ commerce.import_stock.applied ──▶ import tayyor

Fon bosqichlari outbox orqali (18 §3, 2-qoida): har bo'lak o'z tranzaksiyasida, tugagach keyingi bo'lak
event'ini yozadi. Bo'lak takror kelsa — `processed_rows` nazorat nuqtasi uni o'tkazib yuboradi.
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections import Counter
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.imports.models.orm import (
    ImportBatch,
    ImportMapping,
    ImportRow,
    ImportSourceRow,
    ImportStockRow,
)
from app.domains.catalog.imports.parsing import (
    FIELDS,
    MAX_FILE_BYTES,
    MAX_ROWS,
    ImportFileError,
    SheetRow,
    csv_safe,
    normalize_header,
    normalize_row,
    parse_file,
    precheck,
    suggest_mapping,
)
from app.domains.catalog.imports.schemas import (
    DetectedColumn,
    ImportList,
    ImportMappingIn,
    ImportMappingList,
    ImportMappingOut,
    ImportOut,
    ImportReportOut,
    ImportRowOut,
    ImportRowPage,
    ImportRowUpdate,
    ImportStats,
)
from app.domains.catalog.imports.services.planning import Plan, PlanContext, load_context, plan_row
from app.domains.catalog.imports.state_machine import ENTITY
from app.domains.catalog.pc_specs.models.orm import ReferenceHardwareSpec
from app.domains.catalog.pc_specs.services.link_service import LinkService
from app.domains.catalog.pricing.services.pricing_service import PricingService
from app.domains.catalog.products.models.orm import Category, Product, Sku
from app.domains.catalog.products.schemas import ProductCreate
from app.domains.catalog.products.services.product_service import ProductService
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.notifications import NotificationService
from app.platform.shops.models.orm import Branch
from app.platform.staff.models.orm import Membership, Principal
from app.platform.staff.permissions import PermissionRegistry
from app.platform.staff.services.actors import staff_actor
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.contracts.imports import ImportStockResults
from app.shared.db.session import Database
from app.shared.errors.base import (
    DomainError,
    ForbiddenError,
    ImportAlreadyRunningError,
    ImportBusyError,
    ImportFileInvalidError,
    InvalidTransitionError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.i18n.translator import t
from app.shared.pagination import decode_cursor, encode_cursor
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

DRY_RUN_CHUNK = 1000
SOURCE_INSERT_CHUNK = 2000
COMMIT_CHUNK = 500  # 18 §3, 3-qoida
VALIDATED_TTL = timedelta(hours=24)  # tasdiqlanmagan sinov eskiradi (DEC-140, 4-qaror)
STALE_HEARTBEAT = timedelta(minutes=10)  # 06 §6: worker jim — bo'lak qayta qo'yiladi
RETENTION = timedelta(days=30)  # import qatorlari (26 §5)
CHUNK_EVENT = "catalog.import.chunk"
COMPLETED_EVENT = "catalog.import.completed"
CHANGED_EVENT = "catalog.import.changed"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PRODUCT_EDIT = "catalog.product.edit"
STOCK_RECEIVE = "commerce.stock.receive"

# Shablon sarlavhalari moslash lug'atida bor (`HEADER_SYNONYMS`): shablon qaytib kelsa o'zi moslanadi
TEMPLATE_HEADERS: dict[str, dict[str, str]] = {
    "sku_code": {"uz": "Artikul", "ru": "Артикул", "en": "SKU"},
    "title": {"uz": "Nomi", "ru": "Наименование", "en": "Name"},
    "category": {"uz": "Toifa", "ru": "Категория", "en": "Category"},
    "brand": {"uz": "Brend", "ru": "Бренд", "en": "Brand"},
    "model": {"uz": "Model", "ru": "Модель", "en": "Model"},
    "mpn": {"uz": "MPN", "ru": "MPN", "en": "MPN"},
    "variant_name": {"uz": "Variant", "ru": "Вариант", "en": "Variant"},
    "condition": {"uz": "Holati", "ru": "Состояние", "en": "Condition"},
    "price": {"uz": "Narx", "ru": "Цена", "en": "Price"},
    "currency": {"uz": "Valyuta", "ru": "Валюта", "en": "Currency"},
    "quantity": {"uz": "Miqdor", "ru": "Количество", "en": "Quantity"},
    "branch": {"uz": "Filial", "ru": "Филиал", "en": "Branch"},
    "warranty_months": {"uz": "Kafolat (oy)", "ru": "Гарантия (мес)", "en": "Warranty months"},
    "description": {"uz": "Tavsif", "ru": "Описание", "en": "Description"},
    "attributes": {"uz": "Xususiyatlar", "ru": "Характеристики", "en": "Attributes"},
}
TEMPLATE_EXAMPLE = {
    "sku_code": "RTX4060-MSI-V2X",
    "title": "MSI GeForce RTX 4060 Ventus 2X",
    "category": "GPU",
    "brand": "MSI",
    "model": "RTX 4060 Ventus 2X",
    "mpn": "V2X 8G OC",
    "variant_name": "8 GB",
    "condition": "NEW",
    "price": "4 800 000",
    "currency": "UZS",
    "quantity": "5",
    "branch": "",
    "warranty_months": "36",
    "description": "",
    "attributes": "memory_gb: 8",
}

# Xatolar CSV'si — foydalanuvchi tilida (18 §11, 11 §8.3): matnlar `app/shared/i18n/locales` da
# (`import.report.*`, `import.row_errors.<KOD>`) — QA F18


def _field(name: str, code: str, **params: object) -> dict[str, Any]:
    return {"field": name, "code": code, "params": params}


def _lock_not_available(exc: DBAPIError) -> bool:
    """PostgreSQL 55P03 (lock_not_available) — asyncpg orqali."""
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    cause = getattr(orig, "__cause__", None)
    return code == "55P03" or getattr(cause, "sqlstate", None) == "55P03"


def _row_error_text(code: str, locale: str) -> str:
    key = f"import.row_errors.{code}"
    text = t(key, locale)  # type: ignore[arg-type]
    return code if text == key else text


def _stats(raw: dict[str, Any] | None) -> ImportStats:
    return ImportStats(**{k: int(v) for k, v in (raw or {}).items() if k in ImportStats.model_fields})


def import_out(batch: ImportBatch, created_by_name: str | None = None) -> ImportOut:
    detected = batch.detected_columns or {}
    return ImportOut(
        id=batch.id,
        status=batch.status,
        file_format=batch.file_format,
        original_filename=batch.original_filename,
        sheet_name=batch.sheet_name,
        conflict_policy=batch.conflict_policy,
        mapping=batch.mapping,
        detected_columns=[DetectedColumn(**c) for c in detected.get("columns", [])],
        warnings=list(detected.get("warnings", [])),
        default_branch_id=batch.default_branch_id,
        has_stock_rows=batch.has_stock_rows,
        total_rows=batch.total_rows,
        processed_rows=batch.processed_rows,
        stats=_stats(batch.stats),
        error_code=batch.error_code,
        created_by=batch.created_by,
        created_by_name=created_by_name,
        committed_by=batch.committed_by,
        validated_at=batch.validated_at,
        committed_at=batch.committed_at,
        completed_at=batch.completed_at,
        expires_at=batch.expires_at,
        created_at=batch.created_at,
        version=batch.version,
    )


class ImportService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        files: FileService,
        products: ProductService,
        pricing: PricingService,
        links: LinkService,
        permissions: PermissionRegistry,
        stock_results: ImportStockResults,
    ) -> None:
        self.use = use
        self.audit = audit
        self.files = files
        self.products = products
        self.pricing = pricing
        self.links = links
        self.permissions = permissions
        self.stock_results = stock_results
        self.notifications = NotificationService()

    # ================================================================== shop paneli
    async def create(self, db: AsyncSession, actor: ActorContext, file_id: UUID) -> ImportOut:
        """Fayl `POST /shop/files?purpose=IMPORT_FILE` bilan yuklangan. So'rov ichida faqat ARZON tekshiruv
        (hajm, tur, ZIP katalogi, varaq o'lchami, sharedStrings, CSV kodirovkasi) — alohida thread'da;
        to'liq o'qish worker'da (`PARSE` bo'lagi), import `PARSING` holatida ochiladi (QA F1)."""
        assert actor.shop_id is not None
        try:
            stored_file = await self.files.usable(db, actor.shop_id, file_id, "IMPORT_FILE")
        except ValidationError as exc:
            raise ValidationError("File not usable", fields=[_field("file_id", "invalid")]) from exc
        data = await self.files.read_bytes(stored_file)
        if data is None:
            raise ValidationError("File not usable", fields=[_field("file_id", "invalid")])
        try:
            file_format = await asyncio.to_thread(precheck, data)
        except ImportFileError as exc:
            if exc.reason == "TOO_LARGE":
                raise PayloadTooLargeError("File too large", max_bytes=MAX_FILE_BYTES) from exc
            raise ImportFileInvalidError(
                "Import file cannot be read", reason=exc.reason, **exc.details
            ) from exc
        batch = ImportBatch(
            shop_id=actor.shop_id,
            file_id=stored_file.id,
            original_filename=stored_file.original_name or f"import.{file_format.lower()}",
            file_format=file_format,
            status="PARSING",
            detected_columns={"columns": [], "warnings": [], "headers": []},
            created_by=actor.membership_id,
            heartbeat_at=utcnow(),
        )
        db.add(batch)
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.import.uploaded",
            entity_type=ENTITY,
            entity_id=batch.id,
            actor=actor,
            diff={"format": file_format},
        )
        await self._chunk_event(db, actor, batch, "PARSE", 0)
        return await self._out(db, batch)

    async def _best_template(
        self, db: AsyncSession, shop_id: UUID, headers: list[str]
    ) -> ImportMapping | None:
        """Saqlangan shablonlardan shu fayl sarlavhalariga ENG KO'P mos kelgani (QA F13); teng bo'lsa —
        oxirgi yangilangani. Hech biri mos kelmasa — yo'q."""
        normalized = {normalize_header(h) for h in headers if h}
        best: tuple[int, ImportMapping] | None = None
        rows = await db.execute(
            select(ImportMapping)
            .where(ImportMapping.shop_id == shop_id)
            .order_by(ImportMapping.updated_at.desc())
            .limit(200)
        )
        for template in rows.scalars():
            score = sum(
                1
                for header in (template.mapping or {}).values()
                if isinstance(header, str) and normalize_header(header) in normalized
            )
            if score and (best is None or score > best[0]):
                best = (score, template)
        return best[1] if best else None

    async def list_imports(self, db: AsyncSession, actor: ActorContext) -> ImportList:
        rows = await db.execute(
            select(ImportBatch)
            .where(ImportBatch.shop_id == actor.shop_id)
            .order_by(ImportBatch.created_at.desc())
            .limit(20)
        )
        batches = list(rows.scalars())
        names = await self._names(db, [b.created_by for b in batches])
        return ImportList(items=[import_out(b, names.get(b.created_by)) for b in batches])

    async def get(self, db: AsyncSession, actor: ActorContext, batch_id: UUID) -> ImportOut:
        return await self._out(db, await self._batch(db, actor, batch_id))

    async def mappings(self, db: AsyncSession, actor: ActorContext) -> ImportMappingList:
        rows = await db.execute(
            select(ImportMapping).where(ImportMapping.shop_id == actor.shop_id).order_by(ImportMapping.name)
        )
        return ImportMappingList(
            items=[
                ImportMappingOut(
                    id=m.id,
                    name=m.name,
                    mapping=m.mapping,
                    conflict_policy=m.conflict_policy,
                    created_at=m.created_at,
                    version=m.version,
                )
                for m in rows.scalars()
            ]
        )

    async def set_mapping(
        self,
        db: AsyncSession,
        actor: ActorContext,
        batch_id: UUID,
        expected_version: int,
        data: ImportMappingIn,
    ) -> ImportOut:
        batch = await self._batch(db, actor, batch_id, for_update=True)
        check_version(batch.version, expected_version)
        rule = self.use.validate_transition(ENTITY, batch.status, "MAPPED", "MAP", actor)
        headers: list[str] = list((batch.detected_columns or {}).get("headers", []))
        problems: list[dict[str, Any]] = []
        if not data.mapping and data.mapping_id is not None:  # saqlangan shablon tanlandi (QA F13)
            template = await db.get(ImportMapping, data.mapping_id)
            if template is None or template.shop_id != actor.shop_id:
                raise ValidationError("Template not found", fields=[_field("mapping_id", "invalid")])
            derived = suggest_mapping(headers, template.mapping)
            derived = {k: v for k, v in derived.items() if k in (template.mapping or {})}
            if not derived:
                raise ValidationError(
                    "Template does not match this file", fields=[_field("mapping_id", "not_applicable")]
                )
            data = data.model_copy(update={"mapping": derived})
            batch.mapping_id = template.id
        elif data.mapping_id is not None:  # shablon qo'llangan, ustunlar qo'lda tuzatilgan — manba qayd
            template = await db.get(ImportMapping, data.mapping_id)
            if template is None or template.shop_id != actor.shop_id:
                raise ValidationError("Template not found", fields=[_field("mapping_id", "invalid")])
            batch.mapping_id = template.id
        for name, index in data.mapping.items():
            if not 0 <= index < len(headers):
                problems.append(_field(f"mapping.{name}", "invalid_choice"))
        if len(set(data.mapping.values())) != len(data.mapping):
            problems.append(_field("mapping", "not_unique"))
        policy = data.conflict_policy
        if PRODUCT_EDIT not in actor.permissions and policy != "STOCK_ONLY":
            # omborchi katalogni o'zgartirmaydi — faqat qoldiq (DEC-140, 2-qaror)
            problems.append(_field("conflict_policy", "invalid_choice", allowed=["STOCK_ONLY"]))
        required = {
            "STOCK_ONLY": ("sku_code", "quantity"),
            "UPDATE_PRICE_ONLY": ("sku_code", "price"),
        }.get(policy, ("sku_code", "title", "category"))
        problems += [_field(f"mapping.{name}", "required") for name in required if name not in data.mapping]
        if policy == "STOCK_ONLY" and STOCK_RECEIVE not in actor.permissions:
            problems.append(_field("conflict_policy", "invalid_choice"))
        if data.default_branch_id is not None:
            branch = await db.get(Branch, data.default_branch_id)
            in_scope = actor.branch_ids is None or data.default_branch_id in actor.branch_ids
            if branch is None or branch.shop_id != actor.shop_id or branch.status != "ACTIVE" or not in_scope:
                problems.append(_field("default_branch_id", "invalid"))
        if problems:
            raise ValidationError("Invalid mapping", fields=problems)
        warnings = [
            w for w in (batch.detected_columns or {}).get("warnings", []) if not w.startswith("STOCK_")
        ]
        stock_enabled = "quantity" in data.mapping and STOCK_RECEIVE in actor.permissions
        if "quantity" in data.mapping and not stock_enabled:
            warnings.append("STOCK_SKIPPED_NO_PERMISSION")  # 18 §13: qoldiq qismi o'tkazib yuboriladi
        if stock_enabled and "commerce.stock.adjust_approve" not in actor.permissions:
            warnings.append("STOCK_REQUIRES_APPROVAL")  # omborchi: mavjud qoldiq farqi tasdiqqa (DEC-134)
        if rule.from_status == "VALIDATED":  # qayta moslash — eski sinov natijasi o'chadi
            await db.execute(
                delete(ImportRow).where(ImportRow.shop_id == batch.shop_id, ImportRow.batch_id == batch.id)
            )
        batch.mapping = {str(name): index for name, index in data.mapping.items()}
        batch.conflict_policy = policy
        batch.default_branch_id = data.default_branch_id or batch.default_branch_id
        batch.has_stock_rows = stock_enabled
        batch.detected_columns = {**(batch.detected_columns or {}), "warnings": warnings}
        batch.stats, batch.processed_rows, batch.expires_at, batch.validated_at = {}, 0, None, None
        batch.status = rule.to_status
        if data.save_as:
            batch.mapping_id = await self._save_template(db, actor, data, headers)
        await db.flush()
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        return await self._out(db, batch)

    async def start_dry_run(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, expected_version: int
    ) -> ImportOut:
        batch = await self._batch(db, actor, batch_id, for_update=True)
        check_version(batch.version, expected_version)
        rule = self.use.validate_transition(ENTITY, batch.status, "VALIDATING", "VALIDATE", actor)
        await db.execute(
            delete(ImportRow).where(ImportRow.shop_id == batch.shop_id, ImportRow.batch_id == batch.id)
        )
        batch.status, batch.processed_rows, batch.stats = rule.to_status, 0, {}
        batch.heartbeat_at, batch.error_code = utcnow(), None
        await self._flush_active(db)
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        await self._chunk_event(db, actor, batch, "DRY_RUN", 0)
        await self._changed(db, actor, batch)
        return await self._out(db, batch)

    async def rows(
        self,
        db: AsyncSession,
        actor: ActorContext,
        batch_id: UUID,
        *,
        action: str | None,
        errors_only: bool,
        limit: int,
        cursor: str | None,
    ) -> ImportRowPage:
        batch = await self._batch(db, actor, batch_id)
        query = select(ImportRow).where(ImportRow.shop_id == batch.shop_id, ImportRow.batch_id == batch.id)
        if action:
            query = query.where(ImportRow.action == action)
        if errors_only:
            query = query.where((ImportRow.action == "ERROR") | (ImportRow.result == "ERROR"))
        if cursor:
            after = decode_cursor(cursor).get("r")
            # bool ham int — alohida rad; int4 doirasidan tashqari raqam — 422, 500 emas (QA F6)
            if not isinstance(after, int) or isinstance(after, bool) or not 0 <= after <= MAX_ROWS + 1:
                raise ValidationError("Invalid cursor", fields=[_field("cursor", "invalid_format")])
            query = query.where(ImportRow.row_number > after)
        rows = list((await db.execute(query.order_by(ImportRow.row_number).limit(limit + 1))).scalars())
        page = rows[:limit]
        stock = await self._stock_outcomes(db, batch, [r.sku_id for r in page if r.sku_id])
        items = [
            ImportRowOut(
                row_number=r.row_number,
                action=r.action,
                values={
                    k: v
                    for k, v in r.row_values.items()
                    if k not in ("raw", "changes", "stock", "spec_manual")
                },
                changes=r.row_values.get("changes"),
                stock=r.row_values.get("stock"),
                errors=r.errors,
                spec_match=r.spec_match,
                spec_id=r.spec_id,
                selected=r.selected,
                result=r.result,
                product_id=r.product_id,
                sku_id=r.sku_id,
                stock_result=outcome.result if (outcome := stock.get(self._stock_key(r))) else None,
                stock_error=outcome.error_code if outcome else None,
            )
            for r in page
        ]
        has_more = len(rows) > limit
        return ImportRowPage(
            items=items,
            next_cursor=encode_cursor({"r": page[-1].row_number}) if has_more and page else None,
            has_more=has_more,
        )

    @staticmethod
    def _stock_key(row: ImportRow) -> tuple[UUID | None, str | None]:
        """Qoldiq natijasi (SKU, filial) bo'yicha — bitta SKU bir necha filialda bo'ladi (QA F8)."""
        branch = row.row_values.get("branch_id")
        return row.sku_id, str(branch) if branch else None

    async def _stock_outcomes(
        self, db: AsyncSession, batch: ImportBatch, sku_ids: list[UUID] | None
    ) -> dict[tuple[UUID | None, str | None], Any]:
        if sku_ids is not None and not sku_ids:
            return {}
        outcomes = await self.stock_results.results(db, batch.shop_id, batch.id, sku_ids)
        return {(o.sku_id, str(o.branch_id)): o for o in outcomes}

    async def update_row(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, row_number: int, data: ImportRowUpdate
    ) -> ImportRowOut:
        batch = await self._batch(db, actor, batch_id, for_update=True)
        if batch.status != "VALIDATED":
            raise InvalidTransitionError(
                "Import is not under review", entity=ENTITY, **{"from": batch.status}
            )
        row = await db.get(ImportRow, (batch.shop_id, batch.id, row_number))
        if row is None:
            raise NotFoundError("Import row not found")
        if data.selected is not None:
            row.selected = data.selected
        if data.spec_id is not None:
            spec = await db.get(ReferenceHardwareSpec, data.spec_id)
            category = row.row_values.get("spec_category")
            if spec is None or spec.status != "APPROVED" or not category or spec.category != category:
                raise ValidationError("Spec cannot be linked", fields=[_field("spec_id", "invalid")])
            row.spec_id = spec.id
            # Qo'lda tanlangan model — yozishda MANUAL bog'lanish (QA F7), nomzod turi qanday bo'lmasin
            row.row_values = {**row.row_values, "spec_manual": True}
        await db.flush()
        page = await self.rows(
            db,
            actor,
            batch_id,
            action=None,
            errors_only=False,
            limit=1,
            cursor=encode_cursor({"r": row_number - 1}),
        )
        return page.items[0]

    async def commit(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, expected_version: int
    ) -> ImportOut:
        batch = await self._batch(db, actor, batch_id, for_update=True)
        check_version(batch.version, expected_version)
        rule = self.use.validate_transition(ENTITY, batch.status, "COMMITTING", "COMMIT", actor)
        if batch.expires_at is not None and batch.expires_at <= utcnow():
            raise InvalidTransitionError(
                "Dry run expired", entity=ENTITY, **{"from": "EXPIRED"}, command="COMMIT"
            )
        if batch.conflict_policy != "STOCK_ONLY" and PRODUCT_EDIT not in actor.permissions:
            raise ForbiddenError("Permission denied", permission=PRODUCT_EDIT)
        batch.status, batch.processed_rows = rule.to_status, 0
        batch.committed_by, batch.committed_at, batch.heartbeat_at = actor.membership_id, utcnow(), utcnow()
        # Qoldiq — faqat tasdiqlagan xodimda huquq bo'lsa (18 §13)
        batch.has_stock_rows = batch.has_stock_rows and STOCK_RECEIVE in actor.permissions
        await self._flush_active(db)
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        await self.audit.record(
            db, action="catalog.import.committed", entity_type=ENTITY, entity_id=batch.id, actor=actor
        )
        await self._chunk_event(db, actor, batch, "COMMIT", 0)
        await self._changed(db, actor, batch)
        return await self._out(db, batch)

    async def cancel(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, expected_version: int
    ) -> ImportOut:
        batch = await self._batch(db, actor, batch_id, for_update=True)
        check_version(batch.version, expected_version)
        rule = self.use.validate_transition(ENTITY, batch.status, "CANCELLED", "CANCEL", actor)
        batch.status = rule.to_status
        await db.flush()
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        await self._changed(db, actor, batch)
        return await self._out(db, batch)

    async def errors_report(self, db: AsyncSession, actor: ActorContext, batch_id: UUID) -> ImportReportOut:
        """Xato qatorlari CSV'si: asl ustunlar + qator raqami, xato kodlari, foydalanuvchi tilida izoh.
        HAR katak — sarlavha qatori ham — formula sifatida o'qilmaydi (`'` prefiksi, 18 §11, TC-IMP-05,
        QA F4). Matnlar — `app/shared/i18n/locales` (QA F18)."""
        batch = await self._batch(db, actor, batch_id)
        assert actor.shop_id is not None
        headers: list[str] = list((batch.detected_columns or {}).get("headers", []))
        rows = list(
            (
                await db.execute(
                    select(ImportRow)
                    .where(ImportRow.shop_id == batch.shop_id, ImportRow.batch_id == batch.id)
                    .order_by(ImportRow.row_number)
                )
            ).scalars()
        )
        stock = {
            k: o for k, o in (await self._stock_outcomes(db, batch, None)).items() if o.result == "ERROR"
        }
        locale = actor.locale if actor.locale in ("uz", "ru", "en") else "uz"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                csv_safe(v)
                for v in [
                    t("import.report.row_number", locale),  # type: ignore[arg-type]
                    *[h or f"#{i + 1}" for i, h in enumerate(headers)],
                    t("import.report.error_code", locale),  # type: ignore[arg-type]
                    t("import.report.error_message", locale),  # type: ignore[arg-type]
                ]
            ]
        )
        count = 0
        for row in rows:
            problems = list(row.errors)
            outcome = stock.get(self._stock_key(row))
            if outcome is not None and outcome.error_code:
                problems.append({"field": "quantity", "code": str(outcome.error_code)})
            if not problems and row.action != "ERROR" and row.result != "ERROR":
                continue
            raw = row.row_values.get("raw", [])
            if isinstance(raw, dict):  # QA F12 dan oldingi qatorlar — sarlavha bo'yicha
                cells = [raw.get(h or f"#{i + 1}") for i, h in enumerate(headers)]
            else:
                cells = [raw[i] if i < len(raw) else None for i in range(len(headers))]
            codes = ";".join(f"{p['field']}:{p['code']}" for p in problems)
            message = "; ".join(f"{p['field']}: {_row_error_text(str(p['code']), locale)}" for p in problems)
            writer.writerow([csv_safe(v) for v in [row.row_number, *cells, codes, message]])
            count += 1
        data = ("\ufeff" + buffer.getvalue()).encode("utf-8")  # BOM — Excel UTF-8'ni to'g'ri ochadi
        stored = await self.files.store_document(
            db,
            actor.shop_id,
            "EXPORT_FILE",
            data,
            mime_type="text/csv",
            extension=".csv",
            original_name=f"import-errors-{batch.id}.csv",
            uploaded_by=actor.membership_id,
        )
        url, expires_at = self.files.url_for(stored)
        return ImportReportOut(file_id=stored.id, url=url, url_expires_at=expires_at, rows=count)

    @staticmethod
    def template(locale: str, file_format: str) -> tuple[bytes, str]:
        lang = locale if locale in ("uz", "ru", "en") else "uz"
        headers = [names[lang] for names in TEMPLATE_HEADERS.values()]
        example = [TEMPLATE_EXAMPLE[name] for name in TEMPLATE_HEADERS]
        if file_format == "xlsx":
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.append(headers)
            sheet.append(example)
            out = io.BytesIO()
            workbook.save(out)
            return out.getvalue(), XLSX_MIME
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(headers)
        writer.writerow(example)
        return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv"

    # ================================================================== fon bosqichlari (worker)
    async def run_chunk(
        self, database: Database, shop_id: UUID, batch_id: UUID, phase: str, offset: int
    ) -> None:
        """Bitta bo'lak. Kutilmagan xato — import FAILED (qayta urinish yangi import bilan).

        Bo'lakni faqat bitta worker bajaradi — tranzaksiya darajasidagi advisory lock (QA F5); import
        yozuvi bo'lak davomida QULFLANMAYDI: xodim so'rovlari (bekor qilish, moslash) kutib qolmaydi."""
        if phase == "PARSE":
            await self._parse(database, shop_id, batch_id)
            return
        try:
            async with database.transaction(shop_id) as db:
                if not await self._try_lock(db, batch_id):
                    return  # shu import bo'lagini boshqa worker bajaryapti
                batch = await self._fresh(db, shop_id, batch_id)
                expected = "VALIDATING" if phase == "DRY_RUN" else "COMMITTING"
                if batch is None or batch.status != expected or batch.processed_rows != offset:
                    return  # takroriy yoki eskirgan bo'lak
                actor = await self._worker_actor(
                    db, batch, batch.created_by if phase == "DRY_RUN" else batch.committed_by
                )
                if actor is None:
                    await self._fail(db, batch, "IMPORTER_INACTIVE")
                    return
                if phase == "DRY_RUN":
                    await self._dry_run_chunk(db, actor, batch, offset)
                else:
                    await self._commit_chunk(db, actor, batch, offset)
        except Exception as exc:
            logger.exception("catalog.import.chunk_failed", phase=phase, error=type(exc).__name__)
            async with database.transaction(shop_id) as db:
                batch = await self._locked(db, shop_id, batch_id)
                if batch is not None and batch.status in ("VALIDATING", "COMMITTING"):
                    await self._fail(db, batch, self._failure_code(exc))

    @staticmethod
    def _failure_code(exc: BaseException) -> str:
        """Mahsulot xato kodi — drayver ichki atributi emas (QA F16)."""
        if isinstance(exc, ImportFileError):
            return exc.reason
        if isinstance(exc, DomainError):
            return exc.code
        return "IMPORT_FAILED"

    @staticmethod
    async def _try_lock(db: AsyncSession, batch_id: UUID) -> bool:
        return bool(
            await db.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"catalog.import:{batch_id}"},
            )
        )

    @staticmethod
    async def _fresh(db: AsyncSession, shop_id: UUID, batch_id: UUID) -> ImportBatch | None:
        return (
            await db.execute(
                select(ImportBatch)
                .where(ImportBatch.id == batch_id, ImportBatch.shop_id == shop_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def _parse(self, database: Database, shop_id: UUID, batch_id: UUID) -> None:
        """Faylni BIR marta o'qish (QA F1): alohida thread'da, vaqt chegarasi bilan, DB tranzaksiyasidan
        tashqarida; qatorlar `import_source_rows` ga, sarlavha va moslash taklifi importga yoziladi."""
        async with database.transaction(shop_id) as db:
            batch = await self._fresh(db, shop_id, batch_id)
            if batch is None or batch.status != "PARSING":
                return
            data = await self._file_bytes(db, batch)
        try:
            parsed = await asyncio.to_thread(parse_file, data)
        except ImportFileError as exc:
            await self._fail_parse(database, shop_id, batch_id, exc.reason)
            return
        except Exception as exc:
            logger.exception("catalog.import.parse_failed", error=type(exc).__name__)
            await self._fail_parse(database, shop_id, batch_id, "NOT_TABLE")
            return
        async with database.transaction(shop_id) as db:
            if not await self._try_lock(db, batch_id):
                return
            batch = await self._fresh(db, shop_id, batch_id)
            if batch is None or batch.status != "PARSING":
                return
            await self._stage(db, batch, parsed.rows)
            table = parsed.table
            saved = await self._best_template(db, shop_id, list(table.headers))
            suggestion = suggest_mapping(table.headers, saved.mapping if saved else None)
            by_index = {index: name for name, index in suggestion.items()}
            samples = parsed.rows[:3]
            columns = [
                {
                    "index": index,
                    "header": header,
                    "suggested_field": by_index.get(index),
                    "samples": [
                        (row.cells[index] or "")[:100]
                        for row in samples
                        if index < len(row.cells) and row.cells[index]
                    ],
                }
                for index, header in enumerate(table.headers)
            ]
            branches = list(
                (
                    await db.execute(
                        select(Branch.id).where(Branch.shop_id == shop_id, Branch.status == "ACTIVE")
                    )
                ).scalars()
            )
            actor = ActorContext.system(shop_id)
            rule = self.use.validate_transition(ENTITY, batch.status, "UPLOADED", "PARSE", actor)
            batch.sheet_name = table.sheet_name
            batch.detected_columns = {
                "columns": columns,
                "warnings": list(table.warnings),
                "suggested_mapping": suggestion,
                "headers": list(table.headers),
            }
            batch.mapping = suggestion or None
            batch.mapping_id = saved.id if saved else None
            batch.default_branch_id = branches[0] if len(branches) == 1 else None  # bitta filial — o'sha
            batch.total_rows, batch.status, batch.heartbeat_at = table.total_rows, rule.to_status, utcnow()
            await db.flush()
            await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
            await self._changed(db, actor, batch)

    async def _fail_parse(self, database: Database, shop_id: UUID, batch_id: UUID, code: str) -> None:
        async with database.transaction(shop_id) as db:
            batch = await self._locked(db, shop_id, batch_id)
            if batch is not None and batch.status == "PARSING":
                await self._fail(db, batch, code)

    async def _stage(self, db: AsyncSession, batch: ImportBatch, rows: list[SheetRow]) -> None:
        await db.execute(
            delete(ImportSourceRow).where(
                ImportSourceRow.shop_id == batch.shop_id, ImportSourceRow.batch_id == batch.id
            )
        )
        for start in range(0, len(rows), SOURCE_INSERT_CHUNK):
            chunk = rows[start : start + SOURCE_INSERT_CHUNK]
            await db.execute(
                insert(ImportSourceRow).values(
                    [
                        {
                            "shop_id": batch.shop_id,
                            "batch_id": batch.id,
                            "row_number": row.row_number,
                            "cells": list(row.cells),
                        }
                        for row in chunk
                    ]
                )
            )

    async def _source_rows(self, db: AsyncSession, batch: ImportBatch, offset: int) -> list[SheetRow]:
        if offset == 0:
            exists = await db.scalar(
                select(func.count())
                .select_from(ImportSourceRow)
                .where(ImportSourceRow.shop_id == batch.shop_id, ImportSourceRow.batch_id == batch.id)
            )
            if not exists:  # QA F1 dan oldin ochilgan import — fayl bir marta o'qilib saqlanadi
                parsed = await asyncio.to_thread(parse_file, await self._file_bytes(db, batch))
                await self._stage(db, batch, parsed.rows)
        rows = await db.execute(
            select(ImportSourceRow.row_number, ImportSourceRow.cells)
            .where(ImportSourceRow.shop_id == batch.shop_id, ImportSourceRow.batch_id == batch.id)
            .order_by(ImportSourceRow.row_number)
            .offset(offset)
            .limit(DRY_RUN_CHUNK)
        )
        return [SheetRow(number, tuple(cells)) for number, cells in rows.all()]

    async def finish_stock(
        self, db: AsyncSession, shop_id: UUID, batch_id: UUID, counts: dict[str, Any]
    ) -> None:
        """commerce qoldiqni qo'lladi (commerce.import_stock.applied) — import tayyor."""
        batch = await self._locked(db, shop_id, batch_id)
        if batch is None or batch.status != "STOCK_PENDING":
            return
        actor = ActorContext.system(shop_id)
        rule = self.use.validate_transition(ENTITY, batch.status, "COMPLETED", "COMPLETE", actor)
        batch.stats = {
            **(batch.stats or {}),
            "stock_applied": int(counts.get("applied", 0)),
            "stock_no_change": int(counts.get("no_change", 0)),
            "stock_pending": int(counts.get("pending", 0)),
            "stock_errors": int(counts.get("errors", 0)),
        }
        batch.status, batch.completed_at = rule.to_status, utcnow()
        await db.flush()
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        await self._notify(db, actor, batch, "staff.import_completed")
        await self._changed(db, actor, batch)

    async def maintain(self, database: Database, shop_id: UUID) -> dict[str, int]:
        """Rejali ish: 24 soatlik sinov eskiradi, jim qolgan bo'lak qayta qo'yiladi, 30 kunlik qatorlar
        tozalanadi."""
        now = utcnow()
        counts = Counter[str]()
        async with database.transaction(shop_id) as db:
            actor = ActorContext.system(shop_id)
            batches = (
                await db.execute(
                    select(ImportBatch).where(
                        ImportBatch.shop_id == shop_id,
                        ImportBatch.status.in_(("PARSING", "VALIDATED", "VALIDATING", "COMMITTING")),
                    )
                )
            ).scalars()
            for batch in batches:
                if batch.status == "VALIDATED" and batch.expires_at is not None and batch.expires_at <= now:
                    rule = self.use.validate_transition(ENTITY, batch.status, "EXPIRED", "EXPIRE", actor)
                    batch.status = rule.to_status
                    await db.flush()
                    await self.use.log_transition(
                        db, entity_id=batch.id, rule=rule, actor=actor, reason="ttl"
                    )
                    counts["expired"] += 1
                elif batch.status in ("PARSING", "VALIDATING", "COMMITTING") and (
                    batch.heartbeat_at is None or batch.heartbeat_at <= now - STALE_HEARTBEAT
                ):
                    phase = {"PARSING": "PARSE", "VALIDATING": "DRY_RUN"}.get(batch.status, "COMMIT")
                    batch.heartbeat_at = now
                    await db.flush()
                    await self._chunk_event(db, actor, batch, phase, batch.processed_rows)
                    counts["requeued"] += 1
            old = select(ImportBatch.id).where(
                ImportBatch.shop_id == shop_id, ImportBatch.created_at <= now - RETENTION
            )
            purged = await db.execute(
                delete(ImportRow).where(ImportRow.shop_id == shop_id, ImportRow.batch_id.in_(old))
            )
            for table in (ImportStockRow, ImportSourceRow):
                await db.execute(delete(table).where(table.shop_id == shop_id, table.batch_id.in_(old)))
            counts["purged_rows"] += purged.rowcount or 0  # type: ignore[attr-defined]
        return dict(counts)

    # ------------------------------------------------------------------ sinov
    async def _dry_run_chunk(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, offset: int
    ) -> None:
        headers: list[str] = list((batch.detected_columns or {}).get("headers", []))
        mapping = batch.mapping or {}
        sheet_rows = await self._source_rows(db, batch, offset)  # fayl qayta o'qilmaydi (QA F1)
        normalized = [(r.row_number, normalize_row(r.cells, headers, mapping)) for r in sheet_rows]
        ctx = await self._context(db, actor, batch, [v.values.get("sku_code") or "" for _, v in normalized])
        plans = [(n, row, plan_row(ctx, row.values, row.errors)) for n, row in normalized]
        stock_keys = [(p.existing.sku.id, p.stock[0]) for _, _, p in plans if p.stock and p.existing]
        levels = await self.stock_results.stock_levels(db, batch.shop_id, stock_keys) if stock_keys else {}
        for _, _, plan in plans:
            self._apply_stock_level(plan, levels)
        records: list[dict[str, Any]] = []
        for row_number, row, plan in plans:
            spec_category = self._spec_category(ctx, plan)
            match, spec_id = "NOT_APPLICABLE", None
            if plan.action in ("CREATE", "UPDATE") and batch.conflict_policy in (
                "CREATE_ONLY",
                "UPDATE_EXISTING",
            ):
                values = row.values
                existing = plan.existing
                match, spec_id = await self.links.preview_match(
                    db,
                    spec_category,
                    brand=values.get("brand") or (existing.product.brand if existing else None),
                    title=values.get("title") or (existing.product.title if existing else ""),
                    mpn=values.get("mpn") or (existing.sku.mpn if existing else None),
                    model_name=values.get("model") or (existing.sku.model_name if existing else None),
                    variant_name=values.get("variant_name")
                    or (existing.sku.variant_name if existing else None),
                    attributes=values.get("attributes") or {},
                )
            stored = {**row.values, "raw": row.raw}
            if plan.category is not None:
                stored["category_code"] = plan.category.code
            if spec_category:
                stored["spec_category"] = spec_category
            if plan.price is not None:
                stored["amount_minor"] = plan.price.amount_minor
                stored["currency"] = plan.price.currency
            if plan.stock is not None:
                stored["branch_id"] = str(plan.stock[0])
                existing_sku = plan.existing.sku.id if plan.existing else None
                level = levels.get((existing_sku, plan.stock[0])) if existing_sku else None
                stored["stock"] = {
                    "branch_id": str(plan.stock[0]),
                    "current": level.on_hand if level else None,
                    "committed": level.committed if level else None,
                    "new": plan.stock[1],
                }
            changes = self._changes(plan)
            if changes:
                stored["changes"] = changes
            if plan.skip_reason:
                stored["skip_reason"] = plan.skip_reason
            records.append(
                {
                    "shop_id": batch.shop_id,
                    "batch_id": batch.id,
                    "row_number": row_number,
                    "sku_code_normalized": (row.values.get("sku_code") or "").lower() or None,
                    "row_values": stored,
                    "action": plan.action,
                    "errors": plan.errors,
                    "spec_match": match,
                    "spec_id": spec_id,
                    "selected": True,
                }
            )
        if records:
            statement = insert(ImportRow).values(records)
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=["shop_id", "batch_id", "row_number"],
                    set_={
                        c: statement.excluded[c]
                        for c in (
                            "sku_code_normalized",
                            "row_values",
                            "action",
                            "errors",
                            "spec_match",
                            "spec_id",
                        )
                    },
                )
            )
        batch.processed_rows = offset + len(sheet_rows)
        batch.heartbeat_at = utcnow()
        await db.flush()
        if len(sheet_rows) == DRY_RUN_CHUNK and batch.processed_rows < batch.total_rows:
            await self._chunk_event(db, actor, batch, "DRY_RUN", batch.processed_rows)
            return
        await self._mark_duplicates(db, batch)
        counts = dict(
            (
                await db.execute(
                    select(ImportRow.action, func.count())
                    .where(ImportRow.shop_id == batch.shop_id, ImportRow.batch_id == batch.id)
                    .group_by(ImportRow.action)
                )
            ).all()
        )
        with_stock = await db.scalar(
            select(func.count()).where(
                ImportRow.shop_id == batch.shop_id,
                ImportRow.batch_id == batch.id,
                ImportRow.action != "ERROR",
                ImportRow.row_values.has_key("branch_id"),
            )
        )
        batch.stats = {k.lower(): int(counts.get(k, 0)) for k in ("CREATE", "UPDATE", "SKIP", "ERROR")}
        batch.stats["with_stock"] = int(with_stock or 0)
        rule = self.use.validate_transition(ENTITY, batch.status, "VALIDATED", "FINISH_VALIDATION", actor)
        batch.status, batch.validated_at = rule.to_status, utcnow()
        batch.expires_at = batch.validated_at + VALIDATED_TTL
        await db.flush()
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        await self._notify(db, actor, batch, "staff.import_ready")
        await self._changed(db, actor, batch)

    async def _mark_duplicates(self, db: AsyncSession, batch: ImportBatch) -> None:
        """Faylda bir xil artikul ikki marta — hammasi xato (qaysi biri to'g'ri ekanini odam hal qiladi).
        Qoldiq importida (STOCK_ONLY) kalit — artikul + filial: bitta SKU bir necha filialda bo'ladi.

        Ikki qadam (QA O1): oyna funksiyasi bilan dublikat qator raqamlari bitta o'qishda topiladi, keyin
        asosiy kalit bo'yicha yangilanadi. Statistikasi hali yo'q yangi jadvalda ham reja barqaror (eski
        `IN (… GROUP BY … HAVING)` va `UPDATE … FROM` so'rovlari 5 soniyalik chegaradan oshgan edi)."""
        key = "sku_code_normalized"
        if batch.conflict_policy == "STOCK_ONLY":
            key = "sku_code_normalized || '|' || coalesce(row_values->>'branch_id', '')"
        duplicated = list(
            (
                await db.execute(
                    text(
                        f"""
                        SELECT row_number FROM (
                            SELECT row_number, count(*) OVER (PARTITION BY {key}) AS copies
                            FROM catalog.import_rows
                            WHERE shop_id = :shop_id AND batch_id = :batch_id
                              AND sku_code_normalized IS NOT NULL
                        ) counted
                        WHERE copies > 1
                        """  # noqa: S608 — `key` faqat yuqoridagi ikki doimiy ifodadan biri
                    ),
                    {"shop_id": batch.shop_id, "batch_id": batch.id},
                )
            ).scalars()
        )
        for start in range(0, len(duplicated), 1000):  # asosiy kalit bo'yicha — har biri indeks orqali
            await db.execute(
                text(
                    """
                    UPDATE catalog.import_rows
                    SET action = 'ERROR',
                        errors = CASE
                            WHEN errors @> '[{"code": "DUPLICATE_IN_FILE"}]'::jsonb THEN errors
                            ELSE errors || '[{"field": "sku_code", "code": "DUPLICATE_IN_FILE"}]'::jsonb
                        END
                    WHERE shop_id = :shop_id AND batch_id = :batch_id
                      AND row_number = ANY(CAST(:numbers AS integer[]))
                    """
                ),
                {"shop_id": batch.shop_id, "batch_id": batch.id, "numbers": duplicated[start : start + 1000]},
            )
        await db.flush()

    @staticmethod
    def _apply_stock_level(plan: Plan, levels: dict[tuple[UUID, UUID], Any]) -> None:
        """Sinovda joriy qoldiqni hisobga olish: o'zgarmagan qoldiq — o'tkaziladi (QA F9); band
        qilinganidan kam — qator xatosi, yozishdagi rad etishni oldindan ko'rsatadi (QA F10)."""
        if plan.stock is None or plan.existing is None or plan.action != "UPDATE":
            return
        level = levels.get((plan.existing.sku.id, plan.stock[0]))
        quantity = plan.stock[1]
        if level is not None and quantity < level.committed and quantity != level.on_hand:
            plan.error("quantity", "STOCK_BELOW_COMMITTED")
            plan.action = "ERROR"
            return
        catalog_changed = plan.product_changes or plan.sku_changes or plan.price_changed
        if not catalog_changed and level is not None and level.on_hand == quantity:
            plan.action, plan.skip_reason = "SKIP", "UNCHANGED"
        elif not catalog_changed and level is None and quantity == 0:
            plan.action, plan.skip_reason = "SKIP", "UNCHANGED"

    async def _commit_chunk(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, offset: int
    ) -> None:
        rows = list(
            (
                await db.execute(
                    select(ImportRow)
                    .where(ImportRow.shop_id == batch.shop_id, ImportRow.batch_id == batch.id)
                    .order_by(ImportRow.row_number)
                    .offset(offset)
                    .limit(COMMIT_CHUNK)
                )
            ).scalars()
        )
        ctx = await self._context(db, actor, batch, [r.row_values.get("sku_code") or "" for r in rows])
        tally = Counter[str]()
        for row in rows:
            if row.action == "ERROR":
                row.result = "ERROR"
            elif not row.selected:
                row.result = "SKIPPED"
            else:
                await self._apply_row(db, actor, batch, ctx, row)
        await self._settle_stock_only(db, batch, rows)
        for row in rows:
            tally[str(row.result).lower()] += 1
        stats = dict(batch.stats or {})
        for key, name in (
            ("created", "created"),
            ("updated", "updated"),
            ("skipped", "skipped"),
            ("error", "errors"),
        ):
            stats[name] = int(stats.get(name, 0)) + tally.get(key, 0)
        batch.stats = stats
        batch.processed_rows = offset + len(rows)
        batch.heartbeat_at = utcnow()
        await db.flush()
        if len(rows) == COMMIT_CHUNK:
            await self._chunk_event(db, actor, batch, "COMMIT", batch.processed_rows)
            return
        stock_rows = await db.scalar(
            select(func.count()).where(
                ImportStockRow.shop_id == batch.shop_id, ImportStockRow.batch_id == batch.id
            )
        )
        if stock_rows:
            rule = self.use.validate_transition(ENTITY, batch.status, "STOCK_PENDING", "AWAIT_STOCK", actor)
        else:
            rule = self.use.validate_transition(ENTITY, batch.status, "COMPLETED", "COMPLETE", actor)
            batch.completed_at = utcnow()
        batch.status = rule.to_status
        await db.flush()
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor)
        await write_outbox(  # 18 §14: commerce qoldiq qatorlarini o'zi qo'llaydi
            db,
            schema="catalog",
            event_type=COMPLETED_EVENT,
            actor=actor,
            shop_id=batch.shop_id,
            aggregate_type=ENTITY,
            aggregate_id=batch.id,
            aggregate_version=batch.version,
            payload={
                "batch_id": batch.id,
                "committed_by": batch.committed_by,
                "stock_rows": int(stock_rows or 0),
                "stats": {k: int(v) for k, v in stats.items()},
            },
        )
        if not stock_rows:
            await self._notify(db, actor, batch, "staff.import_completed")
        await self._changed(db, actor, batch)

    async def _apply_row(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, ctx: PlanContext, row: ImportRow
    ) -> None:
        values = row.row_values
        plan = plan_row(ctx, values, [])
        if plan.errors:
            row.result, row.errors = "ERROR", plan.errors
            return
        try:
            async with db.begin_nested():  # qator xatosi bo'lakni buzmaydi
                product, sku = await self._write(db, actor, batch, plan, values)
                manual = bool(values.get("spec_manual"))  # ko'rib chiqishda qo'lda tanlangan (QA F7)
                if row.spec_id is not None and sku is not None and (row.spec_match == "MULTIPLE" or manual):
                    await self.links.set_link(db, actor, sku.id, row.spec_id)
                if plan.stock is not None and batch.has_stock_rows and sku is not None:
                    branch_id, quantity = plan.stock
                    await db.execute(
                        insert(ImportStockRow)
                        .values(
                            shop_id=batch.shop_id,
                            batch_id=batch.id,
                            sku_id=sku.id,
                            branch_id=branch_id,
                            quantity=quantity,
                            row_number=row.row_number,
                        )
                        .on_conflict_do_nothing()
                    )
        except DomainError as exc:
            row.result = "ERROR"
            row.errors = [*row.errors, {"field": "row", "code": exc.code}]
            return
        row.product_id = product.id if product else None
        row.sku_id = sku.id if sku else None
        row.result = {"CREATE": "CREATED", "UPDATE": "UPDATED"}.get(plan.action, "SKIPPED")
        if plan.action == "UPDATE" and not (plan.product_changes or plan.sku_changes or plan.price_changed):
            # Faqat qoldiq: natija `_settle_stock_only` da — joriy qoldiq bilan solishtirib (QA F9)
            row.result = "SKIPPED" if plan.stock is None else "UPDATED"
            if plan.stock is not None:
                row.stock_only = True  # type: ignore[attr-defined]  # vaqtinchalik belgi, bazaga yozilmaydi
        if sku is not None and row.result != "SKIPPED":
            await self.audit.record(  # 18 §3, 6-qoida: har o'zgargan SKU import bilan bog'lanadi
                db,
                action="catalog.import.row_applied",
                entity_type="catalog.sku",
                entity_id=sku.id,
                actor=actor,
                diff={"import_batch_id": str(batch.id), "result": row.result, "row": row.row_number},
            )
        if plan.action == "CREATE" and sku is not None:
            ctx.existing[sku.sku_code.lower()] = await self._existing_after_create(sku, product, plan)

    async def _settle_stock_only(self, db: AsyncSession, batch: ImportBatch, rows: list[ImportRow]) -> None:
        """Katalogi o'zgarmagan, faqat qoldiqli qatorlar: qoldiq haqiqatan o'zgarsa — UPDATED, aks holda
        SKIPPED (sinovdagi tasnif bilan bir xil, QA F9)."""
        pending = [r for r in rows if getattr(r, "stock_only", False)]
        if not pending:
            return
        keys = [
            (r.sku_id, UUID(str(r.row_values["branch_id"])))
            for r in pending
            if r.sku_id is not None and r.row_values.get("branch_id")
        ]
        levels = await self.stock_results.stock_levels(db, batch.shop_id, keys) if keys else {}
        for row in pending:
            branch = row.row_values.get("branch_id")
            level = levels.get((row.sku_id, UUID(str(branch)))) if row.sku_id and branch else None
            quantity = row.row_values.get("quantity")
            unchanged = (level is not None and level.on_hand == quantity) or (level is None and quantity == 0)
            row.result = "SKIPPED" if unchanged else "UPDATED"
        await db.flush()

    async def _write(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, plan: Plan, values: dict[str, Any]
    ) -> tuple[Product | None, Sku | None]:
        if plan.action == "CREATE":
            assert plan.category is not None and plan.sku_in is not None
            data = ProductCreate(
                category_code=plan.category.code,
                title=values["title"],
                brand=values.get("brand"),
                description=values.get("description"),
                skus=[plan.sku_in],
            )
            return await self.products.import_create(db, actor, plan.category, data)
        existing = plan.existing
        if existing is None:
            return None, None
        if plan.action == "UPDATE" and batch.conflict_policy != "STOCK_ONLY":
            if plan.product_changes or plan.sku_changes:
                await self.products.import_update(
                    db, actor, existing.product, existing.sku, plan.product_changes, plan.sku_changes
                )
            if plan.price is not None and plan.price_changed:
                await self.pricing.apply_price(db, actor, existing.sku, plan.price, existing.price_version)
        return existing.product, existing.sku

    @staticmethod
    async def _existing_after_create(sku: Sku, product: Product | None, plan: Plan) -> Any:
        from app.domains.catalog.imports.services.planning import Existing

        assert product is not None
        price = plan.price
        return Existing(
            sku,
            product,
            price.amount_minor if price else None,
            price.currency if price else None,
            1 if price else 0,
        )

    # ------------------------------------------------------------------ yordamchilar
    async def _names(self, db: AsyncSession, membership_ids: list[UUID]) -> dict[UUID, str]:
        if not membership_ids:
            return {}
        rows = await db.execute(
            select(Membership.id, Principal.full_name)
            .join(Principal, Principal.id == Membership.principal_id)
            .where(Membership.id.in_(set(membership_ids)))
        )
        return {m: n for m, n in rows.all()}

    async def _out(self, db: AsyncSession, batch: ImportBatch) -> ImportOut:
        return import_out(batch, (await self._names(db, [batch.created_by])).get(batch.created_by))

    async def _context(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, codes: list[str]
    ) -> PlanContext:
        return await load_context(
            db,
            actor,
            self.pricing,
            codes,
            policy=batch.conflict_policy,
            stock_enabled=batch.has_stock_rows,
            default_branch_id=batch.default_branch_id,
        )

    @staticmethod
    def _changes(plan: Plan) -> dict[str, Any] | None:
        """Ko'rib chiqish uchun: maydon bo'yicha eski → yangi va narx farqi."""
        existing = plan.existing
        if existing is None or plan.action != "UPDATE":
            return None
        fields = {
            **{k: {"old": getattr(existing.product, k), "new": v} for k, v in plan.product_changes.items()},
            **{k: {"old": getattr(existing.sku, k), "new": v} for k, v in plan.sku_changes.items()},
        }
        out: dict[str, Any] = {}
        if fields:
            out["fields"] = fields
        if plan.price is not None and plan.price_changed:
            out["price"] = {
                "old": existing.price_amount,
                "old_currency": existing.price_currency,
                "new": plan.price.amount_minor,
                "currency": plan.price.currency,
            }
        return out or None

    @staticmethod
    def _spec_category(ctx: PlanContext, plan: Plan) -> str | None:
        if plan.category is not None:
            return plan.category.spec_category
        if plan.existing is not None:
            category: Category | None = ctx.categories.get(plan.existing.product.category_code)
            return category.spec_category if category else None
        return None

    async def _file_bytes(self, db: AsyncSession, batch: ImportBatch) -> bytes:
        files = await self.files.by_ids(db, batch.shop_id, [batch.file_id])
        stored = files.get(batch.file_id)
        data = await self.files.read_bytes(stored) if stored is not None else None
        if data is None:
            raise ImportFileInvalidError("Import file is gone", reason="FILE_MISSING")
        return data

    async def _worker_actor(
        self, db: AsyncSession, batch: ImportBatch, membership_id: UUID | None
    ) -> ActorContext | None:
        if membership_id is None:
            return None
        return await staff_actor(db, batch.shop_id, membership_id, self.permissions)

    async def _fail(self, db: AsyncSession, batch: ImportBatch, code: str) -> None:
        actor = ActorContext.system(batch.shop_id)
        rule = self.use.validate_transition(ENTITY, batch.status, "FAILED", "FAIL", actor)
        batch.status, batch.error_code = rule.to_status, code[:100]
        await db.flush()
        await self.use.log_transition(db, entity_id=batch.id, rule=rule, actor=actor, reason=code[:100])
        await self._notify(db, actor, batch, "staff.import_failed")
        await self._changed(db, actor, batch)

    async def _chunk_event(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, phase: str, offset: int
    ) -> None:
        await write_outbox(
            db,
            schema="catalog",
            event_type=CHUNK_EVENT,
            actor=actor,
            shop_id=batch.shop_id,
            aggregate_type=ENTITY,
            aggregate_id=batch.id,
            aggregate_version=batch.version,
            payload={"batch_id": batch.id, "phase": phase, "offset": offset},
        )

    async def _changed(self, db: AsyncSession, actor: ActorContext, batch: ImportBatch) -> None:
        """Realtime signal (08 §6): import ekrani holatni qayta o'qiydi."""
        await write_outbox(
            db,
            schema="catalog",
            event_type=CHANGED_EVENT,
            actor=actor,
            shop_id=batch.shop_id,
            aggregate_type=ENTITY,
            aggregate_id=batch.id,
            aggregate_version=batch.version,
            payload={
                "batch_id": batch.id,
                "status": batch.status,
                "created_by": batch.created_by,
                "committed_by": batch.committed_by,
            },
        )

    async def _notify(
        self, db: AsyncSession, actor: ActorContext, batch: ImportBatch, template_key: str
    ) -> None:
        stats = batch.stats or {}
        target = (
            batch.committed_by
            if template_key != "staff.import_ready" and batch.committed_by
            else batch.created_by
        )
        targets = [target]
        if await self._worker_actor(db, batch, target) is None:
            # Import egasi o'chirilgan — xabar shop egasi va menejerlariga (QA F16)
            targets = list(
                (
                    await db.execute(
                        select(Membership.id).where(
                            Membership.shop_id == batch.shop_id,
                            Membership.status == "ACTIVE",
                            Membership.role.in_(("OWNER", "MANAGER")),
                        )
                    )
                ).scalars()
            )
            if not targets:
                return
        await self.notifications.notify_staff(
            db,
            shop_id=batch.shop_id,
            actor=actor,
            template_key=template_key,
            aggregate_type=ENTITY,
            aggregate_id=batch.id,
            aggregate_version=batch.version,
            variables={
                "rows": batch.total_rows,
                "errors": int(stats.get("error", 0)) + int(stats.get("errors", 0)),
                "created": int(stats.get("created", stats.get("create", 0))),
                "updated": int(stats.get("updated", stats.get("update", 0))),
            },
            membership_ids=targets,
            dedup_scope=f"import:{batch.id}:{batch.status}",
        )

    async def _save_template(
        self, db: AsyncSession, actor: ActorContext, data: ImportMappingIn, headers: list[str]
    ) -> UUID:
        assert actor.shop_id is not None and data.save_as is not None
        by_header: dict[str, Any] = {
            str(name): headers[index] for name, index in data.mapping.items() if name in FIELDS
        }
        existing = (
            await db.execute(
                select(ImportMapping).where(
                    ImportMapping.shop_id == actor.shop_id, ImportMapping.name == data.save_as
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.mapping, existing.conflict_policy = by_header, data.conflict_policy
            await db.flush()
            return existing.id
        template = ImportMapping(
            shop_id=actor.shop_id,
            name=data.save_as,
            mapping=by_header,
            conflict_policy=data.conflict_policy,
            created_by=actor.membership_id,
        )
        db.add(template)
        await db.flush()
        return template.id

    async def _flush_active(self, db: AsyncSession) -> None:
        try:
            await db.flush()
        except IntegrityError as exc:
            if "uq_import_batches_one_active" in str(exc.orig):
                raise ImportAlreadyRunningError("Another import is running") from exc
            raise

    async def _batch(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, *, for_update: bool = False
    ) -> ImportBatch:
        query = select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.shop_id == actor.shop_id)
        if for_update:
            # NOWAIT (QA F5): fon bosqichi yozuvni yangilayotgan bo'lsa — kutish va timeout o'rniga darhol 409
            query = query.with_for_update(nowait=True)
        try:
            batch = (await db.execute(query)).scalar_one_or_none()
        except DBAPIError as exc:
            if _lock_not_available(exc):
                raise ImportBusyError("Import is being updated, retry shortly") from exc
            raise
        if batch is None:
            raise NotFoundError("Import not found")
        return batch

    @staticmethod
    async def _locked(db: AsyncSession, shop_id: UUID, batch_id: UUID) -> ImportBatch | None:
        return (
            await db.execute(
                select(ImportBatch)
                .where(ImportBatch.id == batch_id, ImportBatch.shop_id == shop_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
