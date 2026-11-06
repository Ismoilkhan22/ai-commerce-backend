"""reporting rejali ishlari (06 §6): har soat — ombor qiymati va AI xarajati kunlik yig'malari.

Har shop alohida tranzaksiyada (RLS hech qayerda o'chirilmaydi); bir shop yiqilsa qolganlari davom etadi.
Qayta ishga tushsa natija bir xil (bugungi qator qayta yoziladi).
"""

from __future__ import annotations

from datetime import timedelta

import structlog

from app.domains.reporting.common import day_of, shop_zone
from app.domains.reporting.snapshots import compute_stock_value, rebuild_ai_usage
from app.platform.jobs.services.shops import open_shop_ids
from app.shared.events.registry import JobContext, JobResult, ScheduledJob

logger = structlog.get_logger(__name__)


async def stock_value_snapshot(ctx: JobContext) -> JobResult:
    reporting = ctx.services.reporting
    shops = await open_shop_ids(ctx.database)
    written = failed = 0
    for shop_id in shops:
        try:
            async with ctx.database.transaction(shop_id) as db:
                written += await compute_stock_value(
                    db, reporting.catalog, reporting.sources, shop_id, ctx.now
                )
        except Exception:  # bitta shop butun ishni to'xtatmasin
            failed += 1
            logger.warning("reporting.stock_value_failed", shop_id=str(shop_id))
    return JobResult(processed=len(shops), affected=written, details={"failed": failed})


async def ai_usage_rollup(ctx: JobContext) -> JobResult:
    shops = await open_shop_ids(ctx.database)
    written = failed = 0
    for shop_id in shops:
        try:
            async with ctx.database.transaction(shop_id) as db:
                zone = await shop_zone(db, shop_id)
                # Bugun va kecha: kechga yaqin yozilgan chaqiruvlar kechikib kelishi mumkin
                since = day_of(ctx.now, zone) - timedelta(days=1)
                written += await rebuild_ai_usage(db, shop_id, since, zone)
        except Exception:
            failed += 1
            logger.warning("reporting.ai_usage_failed", shop_id=str(shop_id))
    return JobResult(processed=len(shops), affected=written, details={"failed": failed})


REPORTING_JOBS = (
    ScheduledJob("reporting_stock_value", stock_value_snapshot, every_seconds=3600),
    ScheduledJob("reporting_ai_usage", ai_usage_rollup, every_seconds=3600),
)
