"""Yetkazib beruvchi narx ro'yxati (DEC-149, 1-qism).

```
POST /catalog/price-lists {file_id}  ──▶ READING + outbox `catalog.price_list.read`
worker: fayl → AI qatorlarni o'qiydi → kod bo'yicha aniq moslash → qolganiga 5 nomzod, AI tanlaydi
        → taklif narxi (ustama, yaxlitlash) ──▶ READY
ega: ustama/yaxlitlash, qator tanlash, qo'lda moslash yoki narx ──▶ POST .../apply ──▶ APPLIED
```

- AI faqat o'qiydi va moslashni taklif qiladi; narxni ega tasdiqlaydi (BL-038). Qo'llash — oddiy narx
  o'zgarishi (`PricingService.apply_price`: versiya, audit, `catalog.price.changed`), qator bo'yicha:
  bittasi xato bo'lsa qolganlari qo'llanadi.
- LLM chaqiruvi tranzaksiyadan TASHQARIDA; xarajat `PRICE_LIST_READ` bilan yoziladi va shop AI limitiga kiradi
  (DEC-119). Limit tugagan yoki AI sozlanmagan bo'lsa ro'yxat ochilmaydi (422 `AI_UNAVAILABLE`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.imports.parsing import ImportFileError, parse_file
from app.domains.catalog.price_lists.models.orm import PriceListItem, PriceListRun
from app.domains.catalog.price_lists.schemas import (
    PriceListCreateIn,
    PriceListItemIn,
    PriceListItemOut,
    PriceListList,
    PriceListOut,
    PriceListSettingsIn,
    PriceListSummary,
)
from app.domains.catalog.price_lists.services import reading
from app.domains.catalog.price_lists.services.reading import ExtractedItem, SkuOption
from app.domains.catalog.pricing.models.orm import CurrentPrice, PriceVersion
from app.domains.catalog.pricing.services.pricing_service import PricingService
from app.domains.catalog.products.models.orm import Product, Sku
from app.domains.catalog.products.schemas import PriceIn
from app.platform.audit.services.audit_service import AuditService
from app.platform.llm.port import (
    LlmError,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    MediaPart,
    SystemBlock,
    TextPart,
)
from app.platform.llm.router import LlmRouter
from app.platform.llm.usage import record_usage_entry
from app.platform.storage.services.file_service import PDF_MIME, XLSX_MIME, FileService
from app.platform.storage.sniff import IMAGE_TYPES
from app.shared.clock import utcnow
from app.shared.contracts.sales_ai import AiBudgetPort
from app.shared.db.session import Database
from app.shared.errors.base import (
    DomainError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

ENTITY = "catalog.price_list"
READ_EVENT = "catalog.price_list.read"
PURPOSE = "PRICE_LIST_READ"
MAX_SKU_OPTIONS = 20_000
_FORMATS = {XLSX_MIME: "XLSX", "text/csv": "CSV", PDF_MIME: "PDF"} | {m: "IMAGE" for m in IMAGE_TYPES}


def _unavailable(reason: str) -> ValidationError:
    return ValidationError(
        "AI is not available",
        fields=[{"field": "file_id", "code": "ai_unavailable", "params": {"reason": reason}}],
    )


class PriceListService:
    def __init__(self, audit: AuditService, files: FileService, pricing: PricingService) -> None:
        self.audit = audit
        self.files = files
        self.pricing = pricing
        self.llm: LlmRouter | None = None
        self.budget: AiBudgetPort | None = None

    def connect(self, llm: LlmRouter | None, budget: AiBudgetPort | None) -> None:
        """composition root: AI qatlami katalogdan keyin quriladi."""
        self.llm, self.budget = llm, budget

    # ------------------------------------------------------------------ yaratish
    async def create(self, db: AsyncSession, actor: ActorContext, data: PriceListCreateIn) -> PriceListOut:
        assert actor.shop_id is not None
        stored = await self.files.usable(db, actor.shop_id, data.file_id, "PRICE_LIST")
        if self.llm is None or self.budget is None:
            raise _unavailable("NOT_CONFIGURED")
        reason = await self.budget.allowance(db, actor.shop_id)
        if reason is not None:
            raise _unavailable(reason)
        run = PriceListRun(
            shop_id=actor.shop_id,
            file_id=stored.id,
            source_format=_FORMATS.get(stored.mime_type, "CSV"),
            supplier_name=(data.supplier_name or "").strip() or None,
            markup_percent=data.markup_percent,
            created_by=actor.membership_id,
            version=1,
        )
        db.add(run)
        await db.flush()
        await self.audit.record(
            db, action="catalog.price_list.created", entity_type=ENTITY, entity_id=run.id, actor=actor
        )
        await write_outbox(
            db,
            schema="catalog",
            event_type=READ_EVENT,
            actor=actor,
            shop_id=actor.shop_id,
            aggregate_type=ENTITY,
            aggregate_id=run.id,
            aggregate_version=run.version,
            payload={"price_list_id": run.id},
        )
        return await self._out(db, run)

    # ------------------------------------------------------------------ o'qish (worker)
    async def read(self, database: Database, shop_id: UUID, run_id: UUID) -> str:
        """Natija: ready | skipped | failed:<sabab>."""
        async with database.transaction(shop_id) as db:
            run = await self._locked(db, shop_id, run_id)
            if run is None or run.status != "READING":
                return "skipped"
            stored = await self.files.usable(db, shop_id, run.file_id, "PRICE_LIST")
            data = await self.files.read_bytes(stored)
            mime = stored.mime_type
            options = await self._sku_options(db, shop_id)
        if self.llm is None:
            return await self._fail(database, shop_id, run_id, "NOT_CONFIGURED")
        if not data:
            return await self._fail(database, shop_id, run_id, "FILE_UNREADABLE")
        responses: list[LlmResponse] = []
        try:
            items = await self._extract(data, mime, responses)
            if not items:
                await self._save_usage(database, shop_id, run_id, responses)
                return await self._fail(database, shop_id, run_id, "NO_ITEMS")
            matches = await self._match(items, options, responses)
        except ImportFileError as exc:
            return await self._fail(database, shop_id, run_id, f"FILE_{exc.reason}"[:40])
        except LlmError as exc:
            logger.warning("catalog.price_list.llm_failed", code=exc.code)
            await self._save_usage(database, shop_id, run_id, responses)
            return await self._fail(database, shop_id, run_id, "AI_ERROR")
        async with database.transaction(shop_id) as db:
            run = await self._locked(db, shop_id, run_id)
            if run is None or run.status != "READING":
                return "skipped"
            await self._record_usage(db, shop_id, run_id, responses)
            for line_no, item in enumerate(items, start=1):
                sku_id, method = matches.get(line_no, (None, "NONE"))
                db.add(
                    PriceListItem(
                        shop_id=shop_id,
                        run_id=run.id,
                        line_no=line_no,
                        name=item.name,
                        code=item.code,
                        supplier_price_minor=item.price_minor,
                        currency=item.currency,
                        sku_id=sku_id,
                        match_method=method,
                    )
                )
            await db.flush()
            run.item_count, run.matched_count = len(items), sum(1 for m in matches.values() if m[0])
            await self._recompute(db, run, select_changed=True)
            run.status = "READY"
            await db.flush()
        logger.info("catalog.price_list.ready", items=len(items), matched=len(matches))
        return "ready"

    async def _extract(self, data: bytes, mime: str, responses: list[LlmResponse]) -> list[ExtractedItem]:
        assert self.llm is not None
        if mime in (XLSX_MIME, "text/csv"):
            parsed = await asyncio.to_thread(parse_file, data)
            rows = [(1, parsed.table.headers), *((r.row_number, r.cells) for r in parsed.rows)]
            inputs: list[tuple[Any, ...]] = [(TextPart(chunk),) for chunk in reading.table_chunks(rows)]
        else:
            inputs = [(MediaPart(mime, data), TextPart("Extract the price list rows from this file."))]
        items: list[ExtractedItem] = []
        for parts in inputs:
            response = await self.llm.generate(
                LlmRequest(
                    model_alias="seller",
                    system=(SystemBlock(reading.EXTRACT_PROMPT),),
                    messages=(LlmMessage("user", parts),),
                    max_output_tokens=16000,
                    effort="low",
                    timeout_s=90.0,
                ),
                deadline_s=180,
            )
            responses.append(response)
            items.extend(reading.parse_items(response.text))
            if len(items) >= reading.MAX_ITEMS:
                break
        return items[: reading.MAX_ITEMS]

    async def _match(
        self, items: Sequence[ExtractedItem], options: Sequence[SkuOption], responses: list[LlmResponse]
    ) -> dict[int, tuple[UUID | None, str]]:
        assert self.llm is not None
        matches: dict[int, tuple[UUID | None, str]] = {}
        pending: list[tuple[int, ExtractedItem, list[SkuOption]]] = []
        for line_no, item in enumerate(items, start=1):
            exact = reading.exact_code_match(item, options)
            if exact is not None:
                matches[line_no] = (exact, "CODE")
                continue
            found = reading.candidates(item, options)
            if found:
                pending.append((line_no, item, found))
        for start in range(0, len(pending), reading.MATCH_BATCH):
            batch = pending[start : start + reading.MATCH_BATCH]
            response = await self.llm.generate(
                LlmRequest(
                    model_alias="seller",
                    system=(SystemBlock(reading.MATCH_PROMPT),),
                    messages=(LlmMessage("user", (TextPart(reading.match_request(batch)),)),),
                    max_output_tokens=4000,
                    effort="low",
                    timeout_s=60.0,
                ),
                deadline_s=120,
            )
            responses.append(response)
            picks = reading.parse_matches(response.text)
            for line_no, _item, found in batch:
                pick = picks.get(line_no)
                if pick is not None and pick <= len(found):
                    matches[line_no] = (found[pick - 1].sku_id, "AI")
        return matches

    async def _sku_options(self, db: AsyncSession, shop_id: UUID) -> list[SkuOption]:
        rows = await db.execute(
            select(Sku.id, Product.title, Sku.variant_name, Sku.sku_code, Sku.mpn_normalized)
            .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
            .where(Sku.shop_id == shop_id, Sku.status == "ACTIVE", Product.status != "ARCHIVED")
            .order_by(Sku.id)
            .limit(MAX_SKU_OPTIONS)
        )
        return [
            SkuOption(sku_id, f"{title} · {variant}" if variant else title, code, mpn)
            for sku_id, title, variant, code, mpn in rows
        ]

    async def _fail(self, database: Database, shop_id: UUID, run_id: UUID, code: str) -> str:
        async with database.transaction(shop_id) as db:
            run = await self._locked(db, shop_id, run_id)
            if run is not None and run.status == "READING":
                run.status, run.error_code = "FAILED", code
        return f"failed:{code}"

    async def _save_usage(
        self, database: Database, shop_id: UUID, run_id: UUID, responses: Sequence[LlmResponse]
    ) -> None:
        if responses:
            async with database.transaction(shop_id) as db:
                await self._record_usage(db, shop_id, run_id, responses)

    async def _record_usage(
        self, db: AsyncSession, shop_id: UUID, run_id: UUID, responses: Sequence[LlmResponse]
    ) -> None:
        assert self.llm is not None
        for response in responses:
            await record_usage_entry(
                db,
                shop_id=shop_id,
                response=response,
                price=self.llm.price_for(response),
                purpose=PURPOSE,
                ref_id=run_id,
            )

    # ------------------------------------------------------------------ ko'rib chiqish
    async def list_runs(self, db: AsyncSession, actor: ActorContext) -> PriceListList:
        rows = (
            await db.execute(
                select(PriceListRun)
                .where(PriceListRun.shop_id == actor.shop_id)
                .order_by(PriceListRun.created_at.desc(), PriceListRun.id.desc())
                .limit(20)
            )
        ).scalars()
        return PriceListList(
            items=[
                PriceListSummary(
                    id=r.id,
                    status=r.status,
                    supplier_name=r.supplier_name,
                    item_count=r.item_count,
                    matched_count=r.matched_count,
                    applied_count=r.applied_count,
                    created_at=r.created_at,
                )
                for r in rows
            ]
        )

    async def get(self, db: AsyncSession, actor: ActorContext, run_id: UUID) -> PriceListOut:
        return await self._out(db, await self._run(db, actor, run_id))

    async def update_settings(
        self, db: AsyncSession, actor: ActorContext, run_id: UUID, version: int, data: PriceListSettingsIn
    ) -> PriceListOut:
        run = await self._ready(db, actor, run_id, version, "UPDATE")
        if data.markup_percent is not None:
            run.markup_percent = data.markup_percent
        if data.uzs_round_minor is not None:
            run.uzs_round_minor = data.uzs_round_minor
        await self._recompute(db, run, select_changed=False)
        run.updated_at = utcnow()
        await db.flush()
        return await self._out(db, run)

    async def update_item(
        self,
        db: AsyncSession,
        actor: ActorContext,
        run_id: UUID,
        item_id: UUID,
        version: int,
        data: PriceListItemIn,
    ) -> PriceListOut:
        run = await self._ready(db, actor, run_id, version, "UPDATE")
        item = (
            await db.execute(
                select(PriceListItem).where(
                    PriceListItem.shop_id == run.shop_id,
                    PriceListItem.run_id == run.id,
                    PriceListItem.id == item_id,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("Price list item not found")
        if data.unmatch:
            item.sku_id, item.match_method, item.selected, item.manual_price = None, "NONE", False, False
        elif data.sku_id is not None:
            sku = (
                await db.execute(
                    select(Sku).where(
                        Sku.shop_id == run.shop_id, Sku.id == data.sku_id, Sku.status == "ACTIVE"
                    )
                )
            ).scalar_one_or_none()
            if sku is None:
                raise ValidationError(
                    "SKU not found", fields=[{"field": "sku_id", "code": "invalid", "params": {}}]
                )
            item.sku_id, item.match_method, item.manual_price = sku.id, "MANUAL", False
            item.selected = True
        if data.proposed_amount_minor is not None:
            if item.sku_id is None:
                raise ValidationError(
                    "Item is not matched",
                    fields=[{"field": "proposed_amount_minor", "code": "invalid", "params": {}}],
                )
            item.proposed_amount_minor, item.manual_price = data.proposed_amount_minor, True
        if data.selected is not None:
            item.selected = data.selected and item.sku_id is not None
        await db.flush()
        await self._recompute(db, run, select_changed=False)
        run.matched_count = (
            await db.scalar(
                select(func.count()).where(
                    PriceListItem.shop_id == run.shop_id,
                    PriceListItem.run_id == run.id,
                    PriceListItem.sku_id.is_not(None),
                )
            )
            or 0
        )
        run.updated_at = utcnow()
        await db.flush()
        return await self._out(db, run)

    async def cancel(self, db: AsyncSession, actor: ActorContext, run_id: UUID, version: int) -> PriceListOut:
        run = await self._run(db, actor, run_id, lock=True)
        check_version(run.version, version)
        if run.status not in ("READING", "READY", "FAILED"):
            raise InvalidTransitionError(
                "Price list is closed", entity=ENTITY, **{"from": run.status}, command="CANCEL"
            )
        run.status = "CANCELLED"
        await db.flush()
        return await self._out(db, run)

    # ------------------------------------------------------------------ qo'llash
    async def apply(self, db: AsyncSession, actor: ActorContext, run_id: UUID, version: int) -> PriceListOut:
        if "catalog.price.change" not in actor.permissions:
            raise ValidationError(
                "Not allowed", fields=[{"field": "price", "code": "forbidden", "params": {}}]
            )
        run = await self._ready(db, actor, run_id, version, "APPLY")
        items = (
            await db.execute(
                select(PriceListItem)
                .where(
                    PriceListItem.shop_id == run.shop_id,
                    PriceListItem.run_id == run.id,
                    PriceListItem.selected.is_(True),
                    PriceListItem.sku_id.is_not(None),
                )
                .order_by(PriceListItem.line_no)
            )
        ).scalars()
        reason = f"Narx ro'yxati: {run.supplier_name}" if run.supplier_name else "Narx ro'yxati"
        applied = 0
        for item in items:
            if item.proposed_amount_minor is None or item.proposed_currency is None:
                item.result, item.error_code = "ERROR", "NO_PROPOSAL"
                continue
            assert item.sku_id is not None
            sku = await db.get(Sku, item.sku_id)
            product = await db.get(Product, sku.product_id) if sku else None
            if sku is None or sku.status != "ACTIVE" or product is None or product.status == "ARCHIVED":
                item.result, item.error_code = "ERROR", "SKU_ARCHIVED"
                continue
            now = (await self._current_prices(db, sku.shop_id, [sku.id])).get(sku.id)
            if now == (item.proposed_amount_minor, item.proposed_currency):
                item.result = "UNCHANGED"
                continue
            version_now = await db.scalar(
                select(CurrentPrice.version).where(
                    CurrentPrice.shop_id == sku.shop_id, CurrentPrice.sku_id == sku.id
                )
            )
            try:
                async with db.begin_nested():
                    await self.pricing.apply_price(
                        db,
                        actor,
                        sku,
                        PriceIn(
                            currency=item.proposed_currency,
                            amount_minor=item.proposed_amount_minor,
                            reason=reason,
                        ),
                        version_now or 0,
                    )
            except (DomainError, ValueError) as exc:
                item.result = "ERROR"
                item.error_code = (exc.code if isinstance(exc, DomainError) else "INVALID")[:40]
                continue
            item.result = "APPLIED"
            applied += 1
        run.status, run.applied_count = "APPLIED", applied
        run.applied_by, run.applied_at = actor.membership_id, utcnow()
        await db.flush()
        await self.audit.record(
            db,
            action="catalog.price_list.applied",
            entity_type=ENTITY,
            entity_id=run.id,
            actor=actor,
            entity_version=run.version,
            diff={"applied": applied},
        )
        return await self._out(db, run)

    # ------------------------------------------------------------------ yordamchilar
    async def _recompute(self, db: AsyncSession, run: PriceListRun, *, select_changed: bool) -> None:
        """Taklif narxi har moslangan qator uchun: SKU joriy narxi valyutasida (narxi yo'q — yetkazib beruvchi
        valyutasida). Ega yozgan narx (`manual_price`) o'zgarmaydi."""
        items = list(
            (
                await db.execute(
                    select(PriceListItem).where(
                        PriceListItem.shop_id == run.shop_id, PriceListItem.run_id == run.id
                    )
                )
            ).scalars()
        )
        current = await self._current_prices(db, run.shop_id, [i.sku_id for i in items if i.sku_id])
        rate_row = await self.pricing.current_rate(db, run.shop_id)
        rate = Decimal(rate_row.rate) if rate_row is not None else None
        for item in items:
            if item.sku_id is None:
                item.proposed_amount_minor = item.proposed_currency = None
                continue
            now = current.get(item.sku_id)
            target = now[1] if now else item.currency
            if not item.manual_price or item.proposed_currency != target:
                item.manual_price = False
                item.proposed_currency = target
                item.proposed_amount_minor = reading.propose(
                    item.supplier_price_minor,
                    item.currency,
                    target,
                    rate,
                    run.markup_percent,
                    run.uzs_round_minor,
                )
            item.error_code = None if item.proposed_amount_minor is not None else "NO_RATE"
            if select_changed:
                item.selected = item.proposed_amount_minor is not None and (
                    now is None or now != (item.proposed_amount_minor, item.proposed_currency)
                )
        await db.flush()

    @staticmethod
    async def _current_prices(
        db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[int, str]]:
        if not sku_ids:
            return {}
        rows = await db.execute(
            select(CurrentPrice.sku_id, PriceVersion.amount_minor, PriceVersion.currency)
            .join(
                PriceVersion,
                (PriceVersion.shop_id == CurrentPrice.shop_id)
                & (PriceVersion.id == CurrentPrice.price_version_id),
            )
            .where(CurrentPrice.shop_id == shop_id, CurrentPrice.sku_id.in_(set(sku_ids)))
        )
        return {sku_id: (amount, currency) for sku_id, amount, currency in rows}

    async def _out(self, db: AsyncSession, run: PriceListRun) -> PriceListOut:
        items = list(
            (
                await db.execute(
                    select(PriceListItem)
                    .where(PriceListItem.shop_id == run.shop_id, PriceListItem.run_id == run.id)
                    .order_by(PriceListItem.line_no)
                )
            ).scalars()
        )
        sku_ids = [i.sku_id for i in items if i.sku_id]
        current = await self._current_prices(db, run.shop_id, sku_ids)
        titles: dict[UUID, tuple[str, str]] = {}
        if sku_ids:
            rows = await db.execute(
                select(Sku.id, Product.title, Sku.variant_name, Sku.sku_code)
                .join(Product, (Product.shop_id == Sku.shop_id) & (Product.id == Sku.product_id))
                .where(Sku.shop_id == run.shop_id, Sku.id.in_(set(sku_ids)))
            )
            titles = {sid: (f"{t} · {v}" if v else t, code) for sid, t, v, code in rows}
        out_items: list[PriceListItemOut] = []
        for i in items:
            now = current.get(i.sku_id) if i.sku_id else None
            proposal = (i.proposed_amount_minor, i.proposed_currency)
            out_items.append(
                PriceListItemOut(
                    id=i.id,
                    line_no=i.line_no,
                    name=i.name,
                    code=i.code,
                    supplier_price_minor=i.supplier_price_minor,
                    currency=i.currency,
                    sku_id=i.sku_id,
                    sku_title=titles.get(i.sku_id, (None, None))[0] if i.sku_id else None,
                    sku_code=titles.get(i.sku_id, (None, None))[1] if i.sku_id else None,
                    match_method=i.match_method,
                    current_amount_minor=now[0] if now else None,
                    current_currency=now[1] if now else None,
                    proposed_amount_minor=i.proposed_amount_minor,
                    proposed_currency=i.proposed_currency,
                    manual_price=i.manual_price,
                    changed=i.proposed_amount_minor is not None and (now is None or now != proposal),
                    selected=i.selected,
                    result=i.result,
                    error_code=i.error_code,
                )
            )
        return PriceListOut(
            id=run.id,
            version=run.version,
            status=run.status,
            source_format=run.source_format,
            supplier_name=run.supplier_name,
            markup_percent=run.markup_percent,
            uzs_round_minor=run.uzs_round_minor,
            item_count=run.item_count,
            matched_count=run.matched_count,
            selected_count=sum(1 for i in items if i.selected),
            applied_count=run.applied_count,
            error_code=run.error_code,
            created_at=run.created_at,
            applied_at=run.applied_at,
            items=out_items,
        )

    async def _run(
        self, db: AsyncSession, actor: ActorContext, run_id: UUID, *, lock: bool = False
    ) -> PriceListRun:
        query = select(PriceListRun).where(PriceListRun.shop_id == actor.shop_id, PriceListRun.id == run_id)
        run = (await db.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
        if run is None:
            raise NotFoundError("Price list not found")
        return run

    async def _ready(
        self, db: AsyncSession, actor: ActorContext, run_id: UUID, version: int, command: str
    ) -> PriceListRun:
        run = await self._run(db, actor, run_id, lock=True)
        check_version(run.version, version)
        if run.status != "READY":
            raise InvalidTransitionError(
                "Price list is not ready", entity=ENTITY, **{"from": run.status}, command=command
            )
        return run

    @staticmethod
    async def _locked(db: AsyncSession, shop_id: UUID, run_id: UUID) -> PriceListRun | None:
        return (
            await db.execute(
                select(PriceListRun)
                .where(PriceListRun.shop_id == shop_id, PriceListRun.id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
