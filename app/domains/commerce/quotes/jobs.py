"""Lead va taklif: rejali ishlar va event tinglovchisi (6a, DEC-142 Q2, DEC-103).

- `quote_expiry` (har 15 daq): yuborilgan taklif muddati o'tdi → EXPIRED (havola endi qabul qilmaydi).
- `lead_followup` (har kuni 09:00): ochiq lead 30 kun jim → mas'ulga "yopilsinmi?" vazifasi. Lead avtomatik
  yopilMAYDI — yo'qotish sababi odam qarori.
- `commerce.order.completed` → lead buyurtmasi topshirildi → lead WON (avtomatik, FSM-05).
- `messaging.message.*` → lead suhbatida yangi xabar → `last_activity_at` yangilanadi (QA 6a F17):
  faol suhbatda "yopilsinmi?" vazifasi chiqmaydi.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, update

from app.domains.commerce.orders.models.orm import Order
from app.domains.commerce.providers import CommerceServices
from app.domains.commerce.quotes.common import LEAD_FOLLOWUP_DAYS
from app.domains.commerce.quotes.models.orm import OPEN_LEAD_STATUSES, Lead
from app.domains.commerce.quotes.state_machine import LEAD
from app.platform.jobs.services.shops import open_shop_ids
from app.platform.notifications.services.tasks import LEAD_FOLLOWUP, TaskService
from app.shared.clock import utcnow
from app.shared.events.registry import EventContext, JobContext, JobResult, ScheduledJob, subscriber
from app.shared.types.actor import ActorContext

_tasks = TaskService()


async def quote_expiry(ctx: JobContext) -> JobResult:
    commerce: CommerceServices = ctx.services.commerce
    processed = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            processed += await commerce.quotes.expire_due(db, shop_id)
    return JobResult(processed=processed, affected=processed)


async def lead_followup(ctx: JobContext) -> JobResult:
    processed = created = 0
    cutoff = ctx.now - timedelta(days=LEAD_FOLLOWUP_DAYS)
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            leads = (
                (
                    await db.execute(
                        select(Lead).where(
                            Lead.shop_id == shop_id,
                            Lead.status.in_(OPEN_LEAD_STATUSES),
                            Lead.merged_into_lead_id.is_(None),
                            Lead.last_activity_at <= cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            actor = ActorContext.system(shop_id)
            for lead in leads:
                processed += 1
                task = await _tasks.open(
                    db,
                    shop_id=shop_id,
                    actor=actor,
                    type=LEAD_FOLLOWUP,
                    subject_type=LEAD,
                    subject_id=lead.id,
                    # Faollik bo'lsa (yangi xabar, taklif) — yangi oyna, yangi vazifa
                    dedup_key=f"lead_followup:{lead.id}:{lead.last_activity_at.date().isoformat()}",
                    assignee_membership_id=lead.assigned_membership_id,
                    assignee_role="MANAGER",
                    params={"lead_number": lead.number, "days": LEAD_FOLLOWUP_DAYS},
                )
                created += task is not None
    return JobResult(processed=processed, affected=created)


QUOTE_JOBS = (
    ScheduledJob("quote_expiry", quote_expiry, every_seconds=900),
    ScheduledJob("lead_followup", lead_followup, cron="0 9 * * *"),
)


@subscriber("commerce.lead_won", "commerce.order.completed", schema="commerce")
async def lead_won(ctx: EventContext) -> None:
    """Lead'ga bog'langan buyurtma topshirildi → WON (bir marta: WON dan keyin qayta o'tmaydi)."""
    commerce: CommerceServices = ctx.services.commerce
    assert ctx.envelope.shop_id is not None
    order_id = UUID(str(ctx.envelope.payload["order_id"]))
    lead_id = (
        await ctx.session.execute(
            select(Order.lead_id).where(Order.shop_id == ctx.envelope.shop_id, Order.id == order_id)
        )
    ).scalar_one_or_none()
    if lead_id is not None:
        await commerce.leads.mark_won(ctx.session, ctx.envelope.shop_id, lead_id, order_id)


@subscriber(
    "commerce.lead_activity",
    "messaging.message.received",
    "messaging.message.sent",
    "messaging.message.queued",
    schema="messaging",
)
async def lead_activity(ctx: EventContext) -> None:
    """Lead suhbatidagi kiruvchi/chiquvchi xabar — faollik (QA 6a F17). Faqat ochiq leadlar."""
    assert ctx.envelope.shop_id is not None
    conversation_id = ctx.envelope.payload.get("conversation_id")
    if conversation_id is None:
        return
    await ctx.session.execute(
        update(Lead)
        .where(
            Lead.shop_id == ctx.envelope.shop_id,
            Lead.conversation_id == UUID(str(conversation_id)),
            Lead.status.in_(OPEN_LEAD_STATUSES),
        )
        .values(last_activity_at=utcnow())
    )
