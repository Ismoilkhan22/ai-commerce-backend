"""M26 rejali ish: `billing_cycle` (har kuni 06:00) — hisob chiqarish, davr almashtirish, PAST_DUE.

Har shop alohida tranzaksiyada. Natija bo'yicha egaga xabarnoma: yangi hisob, sinov tugadi, to'lov kechikdi.
"""

from __future__ import annotations

from app.platform.billing.services.billing_service import BillingService
from app.platform.jobs.services.shops import open_shop_ids
from app.platform.notifications.services.notifications import NotificationService
from app.shared.events.registry import JobContext, JobResult, ScheduledJob
from app.shared.types.actor import ActorContext

_notifications = NotificationService()
_TEMPLATES = {
    "INVOICED": "staff.billing_invoice",
    "TRIAL_ENDED": "staff.billing_trial_ended",
    "PAST_DUE": "staff.billing_past_due",
}


async def billing_cycle(ctx: JobContext) -> JobResult:
    billing: BillingService = ctx.services.billing
    shops = await open_shop_ids(ctx.database)
    totals: dict[str, int] = {}
    for shop_id in shops:
        async with ctx.database.transaction(shop_id) as db:
            outcome = await billing.cycle(db, shop_id)
            if outcome is None:
                continue
            totals[outcome] = totals.get(outcome, 0) + 1
            template = _TEMPLATES.get(outcome)
            if template is not None:
                sub = await billing.subscription(db, shop_id)
                await _notifications.notify_staff(
                    db,
                    shop_id=shop_id,
                    actor=ActorContext.system(shop_id),
                    template_key=template,
                    aggregate_type="platform.subscription",
                    aggregate_id=shop_id,
                    aggregate_version=sub.version,
                    variables={},
                    roles=("OWNER",),
                    dedup_scope=f"billing:{outcome}:{sub.period_end:%Y%m%d}",
                )
    return JobResult(processed=len(shops), affected=sum(totals.values()), details=totals)


BILLING_JOBS = (ScheduledJob("billing_cycle", billing_cycle, cron="0 6 * * *"),)
