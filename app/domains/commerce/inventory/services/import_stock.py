"""Katalog importining qoldiq qismi (18 §7, db/catalog_import.md §5, DEC-140 — taklif).

Qoldiqning yagona yozuvchisi — commerce (BL-019, BL-022). Fayldagi miqdor oddiy 3-modul hujjatlari bilan
qo'llanadi (1-qaror):
- filialda qoldig'i yo'q SKU → kirim (tasdiqsiz, DEC-136), filial bo'yicha 100 qatordan;
- mavjud SKU, farq bor → tuzatish: ega/menejer importi darhol, omborchiniki — tasdiq kutadi (DEC-134).
  Tuzatishda fayldagi ABSOLYUT qoldiq saqlanadi (`target_on_hand`): farq tasdiq paytida hisoblanadi, shu
  SKU+filial uchun eski kutilayotgan import tuzatishi rad etiladi (QA F3);
- yangi qoldiq buyurtmalarga band qilinganidan kam → xato `STOCK_BELOW_COMMITTED`, qoldiq o'zgarmaydi.

Takror himoyasi: `import_stock_results` asosiy kaliti — event qayta kelsa qator qayta qo'llanmaydi
(TC-IMP-09).
Bo'laklab: bir chaqiruvda 300 qator; qolgani bo'lsa `commerce.import_stock.continue` o'zi qo'yiladi.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.inventory.models.orm import (
    ImportStockResult,
    StockBalance,
)
from app.domains.commerce.inventory.schemas import MAX_QTY, AdjustmentIn, ReceiptIn, ReceiptLineIn
from app.domains.commerce.inventory.services.stock_service import StockService
from app.platform.staff.permissions import PermissionRegistry
from app.platform.staff.services.actors import staff_actor
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.imports import ImportStockRow, ImportStockSource
from app.shared.db.session import Database
from app.shared.errors.base import (
    BranchClosedError,
    DomainError,
    ForbiddenError,
    InsufficientStockError,
    ProductNotAvailableError,
    ValidationError,
)
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

CHUNK = 300
RECEIPT_LINES = 100  # ReceiptIn chegarasi
APPLIED_EVENT = "commerce.import_stock.applied"
CONTINUE_EVENT = "commerce.import_stock.continue"
AGGREGATE = "commerce.import_stock"


def _error_code(exc: DomainError) -> str:
    if isinstance(exc, BranchClosedError):
        return "BRANCH_CLOSED"
    if isinstance(exc, ForbiddenError):
        return "OUT_OF_SCOPE"
    if isinstance(exc, InsufficientStockError):
        return "STOCK_BELOW_COMMITTED"
    if isinstance(exc, ProductNotAvailableError):
        return "PRODUCT_NOT_AVAILABLE"
    if isinstance(exc, ValidationError):
        fields = exc.details.get("fields")
        names = [f.get("field") for f in fields if isinstance(f, dict)] if isinstance(fields, list) else []
        return "UNKNOWN_BRANCH" if "branch_id" in names else "INVALID"
    return exc.code


class ImportStockService:
    def __init__(
        self,
        stock: StockService,
        catalog: CatalogQueryPort,
        source: ImportStockSource,
        permissions: PermissionRegistry,
    ) -> None:
        self.stock = stock
        self.catalog = catalog
        self.source = source
        self.permissions = permissions

    async def apply_chunk(
        self,
        database: Database,
        shop_id: UUID,
        batch_id: UUID,
        committed_by: UUID | None,
        after: tuple[UUID, UUID] | None,
    ) -> None:
        async with database.transaction(shop_id) as db:
            actor = await staff_actor(db, shop_id, committed_by, self.permissions) if committed_by else None
            rows = await self.source.stock_rows(db, shop_id, batch_id, after, CHUNK)
            done = await self._done(db, shop_id, batch_id, rows)
            pending = [r for r in rows if (r.sku_id, r.branch_id) not in done]
            results: list[dict[str, Any]] = []
            if pending:
                if actor is None:  # tasdiqlagan xodim o'chirilgan — qoldiq qo'llanmaydi
                    results = [
                        self._result(batch_id, shop_id, r, "ERROR", "IMPORTER_INACTIVE") for r in pending
                    ]
                else:
                    results = await self._apply(db, actor, batch_id, pending)
            if results:
                await db.execute(insert(ImportStockResult).values(results).on_conflict_do_nothing())
            system = actor or ActorContext.system(shop_id)
            if len(rows) == CHUNK:
                last = rows[-1]
                await write_outbox(
                    db,
                    schema="commerce",
                    event_type=CONTINUE_EVENT,
                    actor=system,
                    shop_id=shop_id,
                    aggregate_type=AGGREGATE,
                    aggregate_id=batch_id,
                    aggregate_version=1,
                    payload={
                        "batch_id": batch_id,
                        "committed_by": committed_by,
                        "after_branch_id": last.branch_id,
                        "after_sku_id": last.sku_id,
                    },
                )
                return
            counts = dict(
                (
                    await db.execute(
                        select(ImportStockResult.result, func.count())
                        .where(ImportStockResult.shop_id == shop_id, ImportStockResult.batch_id == batch_id)
                        .group_by(ImportStockResult.result)
                    )
                ).all()
            )
            await write_outbox(  # 18 §14: catalog import holatini yakunlaydi
                db,
                schema="commerce",
                event_type=APPLIED_EVENT,
                actor=system,
                shop_id=shop_id,
                aggregate_type=AGGREGATE,
                aggregate_id=batch_id,
                aggregate_version=2,
                payload={
                    "batch_id": batch_id,
                    "applied": int(counts.get("APPLIED", 0)),
                    "no_change": int(counts.get("NO_CHANGE", 0)),
                    "pending": int(counts.get("PENDING_APPROVAL", 0)),
                    "errors": int(counts.get("ERROR", 0)),
                },
            )

    async def _apply(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, rows: list[ImportStockRow]
    ) -> list[dict[str, Any]]:
        assert actor.shop_id is not None
        shop_id = actor.shop_id
        tag = f"Import #{str(batch_id)[:8]}"
        balances = {
            (b.branch_id, b.sku_id): b
            for b in (
                await db.execute(
                    select(StockBalance).where(
                        StockBalance.shop_id == shop_id,
                        tuple_(StockBalance.branch_id, StockBalance.sku_id).in_(
                            [(r.branch_id, r.sku_id) for r in rows]
                        ),
                    )
                )
            ).scalars()
        }
        snapshots = await self.catalog.get_skus(db, shop_id, list({r.sku_id for r in rows}))
        results: list[dict[str, Any]] = []
        new_by_branch: dict[UUID, list[ImportStockRow]] = defaultdict(list)
        for row in rows:
            snap = snapshots.get(row.sku_id)
            if snap is None or snap.sku_status != "ACTIVE" or snap.product_status == "ARCHIVED":
                results.append(self._result(batch_id, shop_id, row, "ERROR", "PRODUCT_NOT_AVAILABLE"))
                continue
            if row.quantity > MAX_QTY:
                results.append(self._result(batch_id, shop_id, row, "ERROR", "INVALID_NUMBER"))
                continue
            balance = balances.get((row.branch_id, row.sku_id))
            if balance is None:
                if row.quantity == 0:
                    results.append(self._result(batch_id, shop_id, row, "NO_CHANGE", None))
                else:
                    new_by_branch[row.branch_id].append(row)
                continue
            delta = row.quantity - balance.on_hand
            if delta == 0:
                results.append(self._result(batch_id, shop_id, row, "NO_CHANGE", None))
            elif row.quantity < balance.reserved + balance.allocated:
                results.append(self._result(batch_id, shop_id, row, "ERROR", "STOCK_BELOW_COMMITTED"))
            else:
                results.append(await self._adjust(db, actor, batch_id, row, delta, tag))
        for branch_id, items in new_by_branch.items():
            for start in range(0, len(items), RECEIPT_LINES):
                results += await self._receive(
                    db, actor, batch_id, branch_id, items[start : start + RECEIPT_LINES], tag
                )
        return results

    async def _adjust(
        self, db: AsyncSession, actor: ActorContext, batch_id: UUID, row: ImportStockRow, delta: int, tag: str
    ) -> dict[str, Any]:
        assert actor.shop_id is not None
        try:
            async with db.begin_nested():
                # Eski kutilayotgan import tuzatishi almashtiriladi — farqlar ustma-ust qo'shilmaydi (QA F3)
                await self.stock.supersede_import_adjustments(
                    db, actor, row.branch_id, row.sku_id, f"{tag}: yangi import bilan almashtirildi"
                )
                out = await self.stock.create_adjustment(
                    db,
                    actor,
                    AdjustmentIn(
                        branch_id=row.branch_id,
                        sku_id=row.sku_id,
                        kind="ADJUSTMENT",
                        delta=delta,
                        reason=f"{tag}: sinxronlash",
                    ),
                    import_batch_id=batch_id,
                    target_on_hand=row.quantity,  # tasdiqda farq joriy qoldiqdan qayta hisoblanadi
                )
        except DomainError as exc:
            return self._result(batch_id, actor.shop_id, row, "ERROR", _error_code(exc))
        status = "APPLIED" if out.status == "APPROVED" else "PENDING_APPROVAL"
        return self._result(batch_id, actor.shop_id, row, status, None, adjustment_id=out.id)

    async def _receive(
        self,
        db: AsyncSession,
        actor: ActorContext,
        batch_id: UUID,
        branch_id: UUID,
        items: list[ImportStockRow],
        tag: str,
    ) -> list[dict[str, Any]]:
        assert actor.shop_id is not None
        shop_id = actor.shop_id
        try:
            async with db.begin_nested():
                out = await self.stock.create_receipt(
                    db,
                    actor,
                    ReceiptIn(
                        branch_id=branch_id,
                        note=tag,
                        lines=[ReceiptLineIn(sku_id=r.sku_id, qty=r.quantity) for r in items],
                    ),
                    import_batch_id=batch_id,
                )
        except DomainError as exc:
            code = _error_code(exc)
            return [self._result(batch_id, shop_id, r, "ERROR", code) for r in items]
        return [self._result(batch_id, shop_id, r, "APPLIED", None, receipt_id=out.id) for r in items]

    @staticmethod
    async def _done(
        db: AsyncSession, shop_id: UUID, batch_id: UUID, rows: list[ImportStockRow]
    ) -> set[tuple[UUID, UUID]]:
        if not rows:
            return set()
        found = await db.execute(
            select(ImportStockResult.sku_id, ImportStockResult.branch_id).where(
                ImportStockResult.shop_id == shop_id,
                ImportStockResult.batch_id == batch_id,
                tuple_(ImportStockResult.sku_id, ImportStockResult.branch_id).in_(
                    [(r.sku_id, r.branch_id) for r in rows]
                ),
            )
        )
        return {(s, b) for s, b in found.all()}

    @staticmethod
    def _result(
        batch_id: UUID,
        shop_id: UUID,
        row: ImportStockRow,
        result: str,
        error_code: str | None,
        *,
        receipt_id: UUID | None = None,
        adjustment_id: UUID | None = None,
    ) -> dict[str, Any]:
        return {
            "shop_id": shop_id,
            "batch_id": batch_id,
            "sku_id": row.sku_id,
            "branch_id": row.branch_id,
            "result": result,
            "error_code": error_code,
            "receipt_id": receipt_id,
            "adjustment_id": adjustment_id,
        }
