"""platform/llm moduli: PII xaritasi va AI xarajati jadvallari, tozalash ishi (M06 §7–8, 26 §5)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select

from app.platform.llm.models.orm import AiUsage, LlmPiiRef
from app.platform.shops.models.orm import Shop
from app.shared.events.registry import JobContext, JobResult, ScheduledJob
from app.shared.types.manifest import DomainManifest

USAGE_RETENTION = timedelta(days=400)  # 13 oy (sales_ai.dbml), keyin reporting agregatlari qoladi


async def llm_cleanup(ctx: JobContext) -> JobResult:
    async with ctx.database.transaction() as db:
        shop_ids = (await db.execute(select(Shop.id))).scalars().all()
    deleted = 0
    for shop_id in shop_ids:  # RLS: har shop o'z kontekstida
        async with ctx.database.transaction(shop_id) as db:
            refs = await db.execute(
                delete(LlmPiiRef).where(LlmPiiRef.shop_id == shop_id, LlmPiiRef.expires_at < ctx.now)
            )
            usage = await db.execute(
                delete(AiUsage).where(
                    AiUsage.shop_id == shop_id, AiUsage.occurred_at < ctx.now - USAGE_RETENTION
                )
            )
            deleted += int(getattr(refs, "rowcount", 0) or 0) + int(getattr(usage, "rowcount", 0) or 0)
    return JobResult(processed=len(shop_ids), affected=deleted)


MODULE_MANIFEST = DomainManifest(
    name="llm",
    schema_name="platform",
    scheduled_jobs=[ScheduledJob("llm_cleanup", llm_cleanup, cron="45 3 * * *")],
)
