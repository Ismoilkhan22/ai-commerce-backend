"""Proyeksiyalarni mavjud ma'lumotdan qayta qurish (19 §3.3): bitta shop, bitta tranzaksiya.

Tartib: shopning fakt jadvallari tozalanadi → manba port'idan sintetik event'lar (jonli bilan bir xil
shakl) o'sha `apply_event` orqali qo'llanadi → ombor qiymati va AI xarajati yig'malari qayta hisoblanadi.
Natija jonli proyeksiya bilan bir xil. Tarixiy `stock_value_daily` (kun oxiri surati) manbadan tiklanmaydi va
saqlanadi. Bir tranzaksiya: yiqilsa eski holat qoladi.

Diqqat: jonli event'lar oqayotganda ishga tushirish xavfsiz emas (oraliqdagi event ikki marta yoki yo'qolishi
mumkin) — bir martalik dev/migratsiya vositasi. Chaqiruvchi — `app/workers/reporting_backfill.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reporting.models.orm import (
    ConversationFact,
    HandoffFact,
    MessageFact,
    OrderFact,
    OrderLineFact,
    ProjectionCheckpoint,
    QuickSaleFact,
    StockFact,
    SupportCaseFact,
)
from app.domains.reporting.projections import ALL_PROJECTIONS, apply_event
from app.domains.reporting.snapshots import compute_stock_value, rebuild_ai_usage
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.reporting import ReportingSourcePort

FACT_TABLES = (
    OrderLineFact,
    OrderFact,
    QuickSaleFact,
    StockFact,
    SupportCaseFact,
    MessageFact,
    ConversationFact,
    HandoffFact,
    ProjectionCheckpoint,
)


async def rebuild_shop(
    db: AsyncSession, catalog: CatalogQueryPort, sources: ReportingSourcePort, shop_id: UUID, now: datetime
) -> dict[str, int]:
    for table in FACT_TABLES:
        await db.execute(delete(table).where(table.shop_id == shop_id))
    counts: dict[str, int] = {}
    for name, events in (
        ("orders", await sources.orders(db, shop_id)),
        ("quick_sales", await sources.quick_sales(db, shop_id)),
        ("stock", await sources.stock(db, shop_id)),
        ("cases", await sources.cases(db, shop_id)),
        ("conversations", await sources.conversations(db, shop_id)),
    ):
        for event in events:
            await apply_event(db, catalog, event)
        counts[name] = len(events)
    counts["stock_value_rows"] = await compute_stock_value(db, catalog, sources, shop_id, now)
    counts["ai_usage_rows"] = await rebuild_ai_usage(db, shop_id, None)
    stmt = insert(ProjectionCheckpoint).values(
        [{"shop_id": shop_id, "projection": name, "rebuilt_at": now} for name in ALL_PROJECTIONS]
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ProjectionCheckpoint.shop_id, ProjectionCheckpoint.projection],
            set_={"rebuilt_at": stmt.excluded.rebuilt_at, "updated_at": func.now()},
        )
    )
    return counts
