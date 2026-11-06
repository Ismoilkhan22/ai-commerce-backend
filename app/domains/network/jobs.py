"""network rejali ishlari: `price_alerts_check` (har soat, M36) — narx tushsa global bot orqali xabar;
`buyer_cleanup` (kunlik) — eski xaridor kirish kodlari va sessiyalari."""

from __future__ import annotations

from app.domains.network.providers import NetworkServices
from app.domains.network.services.buyers import BuyerService
from app.shared.events.registry import JobContext, JobResult, ScheduledJob


async def price_alerts_check(ctx: JobContext) -> JobResult:
    network: NetworkServices = ctx.services.network
    sent = await network.global_bot.check_alerts(ctx.database)
    return JobResult(processed=sent, affected=sent)


async def buyer_cleanup(ctx: JobContext) -> JobResult:
    """Kunlik: bir kundan eski kirish kodlari va muddati o'tgan/bekor qilinganiga 7 kun bo'lgan sessiyalar."""
    async with ctx.database.transaction() as db:
        deleted = await BuyerService.cleanup(db)
    return JobResult(processed=deleted, affected=deleted)


NETWORK_JOBS = (
    ScheduledJob("price_alerts_check", price_alerts_check, every_seconds=3600),
    ScheduledJob("buyer_cleanup", buyer_cleanup, every_seconds=86400),
)
