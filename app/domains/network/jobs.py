"""network rejali ishlari: `price_alerts_check` (har soat, M36) — narx tushsa global bot orqali xabar."""

from __future__ import annotations

from app.domains.network.providers import NetworkServices
from app.shared.events.registry import JobContext, JobResult, ScheduledJob


async def price_alerts_check(ctx: JobContext) -> JobResult:
    network: NetworkServices = ctx.services.network
    sent = await network.global_bot.check_alerts(ctx.database)
    return JobResult(processed=sent, affected=sent)


NETWORK_JOBS = (ScheduledJob("price_alerts_check", price_alerts_check, every_seconds=3600),)
