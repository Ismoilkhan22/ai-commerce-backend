"""support rejali ishlari (db/support.md §7).

- `support_case_auto_close` (har soat): `RESOLVED` dan 7 kun o'tsa → `CLOSED` (FSM-11: "muddat o'tdi").
"""

from __future__ import annotations

from app.domains.support.providers import SupportServices
from app.platform.jobs.services.shops import open_shop_ids
from app.shared.events.registry import JobContext, JobResult, ScheduledJob


async def case_auto_close(ctx: JobContext) -> JobResult:
    support: SupportServices = ctx.services.support
    closed = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            closed += await support.lifecycle.auto_close_due(db, shop_id, ctx.now)
    return JobResult(processed=closed, affected=closed)


SUPPORT_JOBS = (ScheduledJob("support_case_auto_close", case_auto_close, every_seconds=3600),)
