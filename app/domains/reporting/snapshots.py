"""Event'siz yig'malar (reporting.md §3, §5): ombor qiymati va AI xarajati kunlik.

- `stock_value_daily`: bugungi qator har soat qayta hisoblanadi (oxirgisi — kun oxiri), o'tgan kunlar
  o'zgarmaydi. Qiymat sotuv narxida va tannarxda; tannarxi/narxi noma'lum donalar alohida sanaladi.
- `ai_usage_daily`: `platform.ai_usage` dan shop kuni bo'yicha; qayta yozish idempotent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reporting.common import day_of, day_start, shop_zone
from app.domains.reporting.models.orm import AiUsageDaily, StockFact, StockValueDaily
from app.domains.reporting.projections import ensure_dims
from app.platform.llm.models.orm import AiUsage
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.reporting import ReportingSourcePort


async def compute_stock_value(
    db: AsyncSession,
    catalog: CatalogQueryPort,
    sources: ReportingSourcePort,
    shop_id: UUID,
    now: datetime,
    zone: ZoneInfo | None = None,
) -> int:
    """Bugungi `stock_value_daily` qatorlarini (filial bo'yicha) qayta yozadi. Yozilgan qatorlar soni."""
    zone = zone or await shop_zone(db, shop_id)
    stock = list((await db.execute(select(StockFact).where(StockFact.shop_id == shop_id))).scalars())
    if not stock:
        return 0
    dims = await ensure_dims(db, catalog, shop_id, {row.sku_id for row in stock}, refresh=True)
    costs = await sources.sku_costs(db, shop_id)
    per_branch: dict[UUID, dict[str, int]] = defaultdict(
        lambda: {"units": 0, "quarantine": 0, "price": 0, "cost": 0, "no_cost": 0, "no_price": 0, "costed": 0}
    )
    for row in stock:
        acc = per_branch[row.branch_id]
        acc["units"] += row.on_hand
        acc["quarantine"] += row.quarantine_qty
        dim = dims.get(row.sku_id)
        price = dim.price_uzs_minor if dim else None
        if price is None:
            acc["no_price"] += row.on_hand
        else:
            acc["price"] += row.on_hand * price
        cost = costs.get(row.sku_id)
        if cost is None:
            acc["no_cost"] += row.on_hand
        else:
            acc["cost"] += row.on_hand * cost
            acc["costed"] += row.on_hand
    today = day_of(now, zone)
    rows = [
        {
            "shop_id": shop_id,
            "day": today,
            "branch_id": branch_id,
            "units": acc["units"],
            "quarantine_units": acc["quarantine"],
            "value_at_price_minor": acc["price"],
            # Birorta ham tannarxli dona bo'lmasa raqam yo'q (NULL): 0 deb aytilmaydi (DEC-146)
            "value_at_cost_minor": acc["cost"] if acc["costed"] else None,
            "units_without_cost": acc["no_cost"],
            "units_without_price": acc["no_price"],
        }
        for branch_id, acc in per_branch.items()
    ]
    stmt = insert(StockValueDaily).values(rows)
    ex = stmt.excluded
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[StockValueDaily.shop_id, StockValueDaily.day, StockValueDaily.branch_id],
            set_={
                "units": ex.units,
                "quarantine_units": ex.quarantine_units,
                "value_at_price_minor": ex.value_at_price_minor,
                "value_at_cost_minor": ex.value_at_cost_minor,
                "units_without_cost": ex.units_without_cost,
                "units_without_price": ex.units_without_price,
                "computed_at": func.now(),
            },
        )
    )
    return len(rows)


async def rebuild_ai_usage(
    db: AsyncSession, shop_id: UUID, since_day: date | None, zone: ZoneInfo | None = None
) -> int:
    """`since_day` (shop vaqti) dan boshlab kunlik yig'ma; None — butun tarix. Yozilgan qatorlar soni."""
    zone = zone or await shop_zone(db, shop_id)
    local_day = cast(func.timezone(zone.key, AiUsage.occurred_at), Date)
    query = (
        select(
            local_day.label("day"),
            AiUsage.purpose,
            AiUsage.model_id,
            func.count().label("calls"),
            func.coalesce(func.sum(AiUsage.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(AiUsage.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(AiUsage.cache_read_tokens), 0).label("cache_read"),
            func.coalesce(func.sum(AiUsage.cache_write_tokens), 0).label("cache_write"),
            func.coalesce(func.sum(AiUsage.cost_micros), 0).label("cost"),
        )
        .where(AiUsage.shop_id == shop_id)
        .group_by(local_day, AiUsage.purpose, AiUsage.model_id)
    )
    if since_day is not None:
        query = query.where(AiUsage.occurred_at >= day_start(since_day, zone))
    rows = [
        {
            "shop_id": shop_id,
            "day": r.day,
            "purpose": r.purpose,
            "model_id": r.model_id,
            "calls": int(r.calls),
            "tokens_in": int(r.tokens_in),
            "tokens_out": int(r.tokens_out),
            "cache_read_tokens": int(r.cache_read),
            "cache_write_tokens": int(r.cache_write),
            "cost_micros": int(r.cost),
        }
        for r in (await db.execute(query)).all()
    ]
    if not rows:
        return 0
    stmt = insert(AiUsageDaily).values(rows)
    ex = stmt.excluded
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                AiUsageDaily.shop_id,
                AiUsageDaily.day,
                AiUsageDaily.purpose,
                AiUsageDaily.model_id,
            ],
            set_={
                "calls": ex.calls,
                "tokens_in": ex.tokens_in,
                "tokens_out": ex.tokens_out,
                "cache_read_tokens": ex.cache_read_tokens,
                "cache_write_tokens": ex.cache_write_tokens,
                "cost_micros": ex.cost_micros,
                "computed_at": func.now(),
            },
        )
    )
    return len(rows)
