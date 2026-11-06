"""M22: tashqi tizim (kassa / ERP) qoldig'ini qo'llash — BR-X12, TC-019. Qoldiq yozuvchisi — commerce.

`network.pos_stock.received` (hamkor API) → har qator:
- `observed_at` shu SKU+filialdagi oxirgi daftar yozuvidan ESKI → `STALE` (nizo: ustidan yozilmaydi);
- joriy qoldiq bilan teng → `UNCHANGED`;
- band qilinganidan kam → `BELOW_COMMITTED` (nizo);
- aks holda tuzatish (`target_on_hand` — absolyut, farq tasdiqda qayta hisoblanadi): kalitda avtomatik
  qo'llash yoqilgan bo'lsa darhol (`APPLIED`), bo'lmasa ega/menejer tasdig'iga (`PENDING_APPROVAL`). Shu
  SKU+filial uchun avvalgi kutilayotgan tashqi tuzatish almashtiriladi (ustma-ust qo'shilmaydi).
Natija — `commerce.pos_stock.applied` (faqat sonlar va qator holatlari).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.inventory.models.orm import StockBalance, StockLedger
from app.domains.commerce.inventory.schemas import AdjustmentIn
from app.domains.commerce.inventory.services.stock_service import StockService
from app.shared.clock import utcnow
from app.shared.errors.base import DomainError
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

APPROVE = "commerce.stock.adjust_approve"
FUTURE_TOLERANCE = timedelta(minutes=5)  # kassa soati biroz oldinda bo'lishi mumkin


class PosStockService:
    def __init__(self, stock: StockService) -> None:
        self.stock = stock

    async def apply(self, db: AsyncSession, shop_id: UUID, payload: dict[str, Any]) -> dict[str, int]:
        report_id = UUID(str(payload["report_id"]))
        auto = bool(payload.get("auto_apply"))
        owner = payload.get("requested_by")
        actor = ActorContext(  # tuzatish kalitni yaratgan ega nomidan (so'rovchi majburiy)
            actor_type="SYSTEM",
            actor_id=None,
            shop_id=shop_id,
            surface="worker",
            permissions=frozenset({APPROVE}) if auto else frozenset(),
            membership_id=UUID(str(owner)) if owner else None,
        )
        counts: dict[str, int] = {}
        for item in payload.get("items") or []:
            try:
                status = await self._one(db, actor, report_id, item)
            except (ValueError, TypeError, KeyError):  # buzuq qator butun paketni to'xtatmaydi (QA #3)
                status = "ERROR"
            counts[status] = counts.get(status, 0) + 1
        await write_outbox(
            db,
            schema="commerce",
            event_type="commerce.pos_stock.applied",
            actor=actor,
            shop_id=shop_id,
            aggregate_type="network.stock_report",
            aggregate_id=report_id,
            aggregate_version=1,
            payload={"report_id": report_id, "summary": counts},
        )
        return counts

    async def _one(self, db: AsyncSession, actor: ActorContext, report_id: UUID, item: dict[str, Any]) -> str:
        assert actor.shop_id is not None
        sku_id, branch_id = UUID(str(item["sku_id"])), UUID(str(item["branch_id"]))
        target, observed = int(item["on_hand"]), datetime.fromisoformat(str(item["observed_at"]))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        if observed > utcnow() + FUTURE_TOLERANCE:
            return "FUTURE"  # kelajakdagi vaqt STALE tekshiruvini aylanib o'tmasin
        last = await db.scalar(
            select(func.max(StockLedger.created_at)).where(
                StockLedger.shop_id == actor.shop_id,
                StockLedger.branch_id == branch_id,
                StockLedger.sku_id == sku_id,
            )
        )
        if last is not None and observed < last:
            return "STALE"
        balance = (
            await db.execute(
                select(StockBalance).where(
                    StockBalance.shop_id == actor.shop_id,
                    StockBalance.branch_id == branch_id,
                    StockBalance.sku_id == sku_id,
                )
            )
        ).scalar_one_or_none()
        current = balance.on_hand if balance else 0
        if target == current:
            return "UNCHANGED"
        if balance is not None and target < balance.reserved + balance.allocated:
            return "BELOW_COMMITTED"
        try:
            async with db.begin_nested():
                await self.stock.supersede_import_adjustments(
                    db, actor, branch_id, sku_id, "Tashqi tizim: yangi qoldiq bilan almashtirildi"
                )
                out = await self.stock.create_adjustment(
                    db,
                    actor,
                    AdjustmentIn(
                        branch_id=branch_id,
                        sku_id=sku_id,
                        kind="ADJUSTMENT",
                        delta=target - current,
                        reason="Tashqi tizim (kassa/ERP) qoldig'i",
                    ),
                    import_batch_id=report_id,  # tashqi paket — eski kutilayotgani almashtiriladi
                    target_on_hand=target,
                )
        except DomainError:
            return "ERROR"
        return "APPLIED" if out.status == "APPROVED" else "PENDING_APPROVAL"
