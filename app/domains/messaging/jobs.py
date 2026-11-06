"""messaging rejali ishlari (06 §5.2, §6; 26 §5). Har shop alohida tranzaksiyada, o'z konteksti bilan (RLS).

- `messaging_handoff_reminders` (har 2 daq): operator kutayotgan suhbat `handoff_reminder_minutes`
  dan oshdi → xodimlarga bir marta eslatma. Ish vaqtidan tashqari (`inbox_hours`) — kutadi, ish
  boshlanganda ketadi.
- `messaging_stuck_sending` (har 5 daq): 5 daqiqadan beri `SENDING` — `UNKNOWN` (jarayon o'lgan).
- `messaging_retention` (har kecha): oxirgi faollikdan 12 oy o'tgan suhbat xabarlari, rasmlari va izohlari
  o'chiriladi; suhbat qatori (raqamlar uchun) qoladi (26 §5).
- `messaging_provider_events_cleanup` (har kecha): 30 kundan eski webhook dedup yozuvlari (5-qaror).
- `messaging_webchat_sessions_cleanup` (har kecha): muddati 30 kundan oldin tugagan sayt chati sessiyalari.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import CONVERSATION, channel_label, within_inbox_hours
from app.domains.messaging.models.orm import (
    Attachment,
    Conversation,
    ConversationNote,
    Handoff,
    Message,
    ProviderEvent,
    WebchatSession,
)
from app.domains.messaging.providers import from_state
from app.platform.jobs.services.shops import open_shop_ids
from app.platform.notifications.services.notifications import NotificationService
from app.platform.shops.models.orm import Shop, ShopPolicy
from app.platform.storage.models.orm import StoredFile
from app.shared.events.registry import JobContext, JobResult, ScheduledJob
from app.shared.types.actor import ActorContext

MESSAGE_RETENTION = timedelta(days=365)
PROVIDER_EVENT_RETENTION = timedelta(days=30)
SESSION_GRACE = timedelta(days=30)
_notifications = NotificationService()


async def _reminders(db: AsyncSession, shop_id: UUID, ctx: JobContext) -> tuple[int, int]:
    policy = await db.get(ShopPolicy, shop_id)
    shop = await db.get(Shop, shop_id)
    if policy is None or shop is None:
        return 0, 0
    if not within_inbox_hours(policy.inbox_hours, shop.timezone, ctx.now):
        return 0, 0
    minutes = policy.handoff_reminder_minutes
    rows = (
        await db.execute(
            select(Handoff, Conversation)
            .join(
                Conversation,
                and_(Conversation.shop_id == Handoff.shop_id, Conversation.id == Handoff.conversation_id),
            )
            .where(
                Handoff.shop_id == shop_id,
                Handoff.status == "OPEN",
                Handoff.reminded_at.is_(None),
                Handoff.created_at <= ctx.now - timedelta(minutes=minutes),
            )
            .with_for_update(of=Handoff, skip_locked=True)
        )
    ).all()
    actor = ActorContext.system(shop_id)
    for handoff, conversation in rows:
        await _notifications.notify_staff(
            db,
            shop_id=shop_id,
            actor=actor,
            template_key="staff.handoff_reminder",
            aggregate_type=CONVERSATION,
            aggregate_id=conversation.id,
            aggregate_version=conversation.version,
            variables={"minutes": minutes, "channel": channel_label(conversation.channel)},
            membership_ids=[conversation.assignee_membership_id],
            roles=("OWNER", "MANAGER", "SALES")
            if conversation.assignee_membership_id is None
            else ("OWNER", "MANAGER"),
            dedup_scope=f"reminder:{handoff.id}",
        )
        handoff.reminded_at = ctx.now
    return len(rows), len(rows)


async def handoff_reminders(ctx: JobContext) -> JobResult:
    processed = affected = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            seen, sent = await _reminders(db, shop_id, ctx)
        processed, affected = processed + seen, affected + sent
    return JobResult(processed=processed, affected=affected)


async def stuck_sending(ctx: JobContext) -> JobResult:
    sending = from_state(ctx.services).sending
    affected = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            affected += await sending.mark_stuck_unknown(db, shop_id)
    return JobResult(affected=affected)


async def _purge_shop(db: AsyncSession, shop_id: UUID, cutoff_at: datetime) -> int:
    stale = select(Conversation.id).where(
        Conversation.shop_id == shop_id, Conversation.last_message_at < cutoff_at
    )
    file_ids = list(
        (
            await db.execute(
                select(Attachment.file_id)
                .join(
                    Message, and_(Message.shop_id == Attachment.shop_id, Message.id == Attachment.message_id)
                )
                .where(
                    Attachment.shop_id == shop_id,
                    Message.conversation_id.in_(stale),
                    Attachment.file_id.is_not(None),
                )
            )
        ).scalars()
    )
    if file_ids:
        await db.execute(
            update(StoredFile)
            .where(StoredFile.shop_id == shop_id, StoredFile.id.in_(file_ids))
            .values(status="DELETED")
        )
    await db.execute(
        update(ProviderEvent)
        .where(
            ProviderEvent.shop_id == shop_id,
            ProviderEvent.message_id.in_(
                select(Message.id).where(Message.shop_id == shop_id, Message.conversation_id.in_(stale))
            ),
        )
        .values(message_id=None)
    )
    result = await db.execute(
        delete(Message).where(Message.shop_id == shop_id, Message.conversation_id.in_(stale))
    )
    await db.execute(
        delete(ConversationNote).where(
            ConversationNote.shop_id == shop_id, ConversationNote.conversation_id.in_(stale)
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def retention(ctx: JobContext) -> JobResult:
    cutoff = ctx.now - MESSAGE_RETENTION
    deleted = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            deleted += await _purge_shop(db, shop_id, cutoff)
    return JobResult(affected=deleted, details={"messages_deleted": deleted})


async def provider_events_cleanup(ctx: JobContext) -> JobResult:
    deleted = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            result = await db.execute(
                delete(ProviderEvent).where(
                    ProviderEvent.shop_id == shop_id,
                    ProviderEvent.received_at < ctx.now - PROVIDER_EVENT_RETENTION,
                )
            )
            deleted += int(result.rowcount or 0)  # type: ignore[attr-defined]
    return JobResult(affected=deleted)


async def webchat_sessions_cleanup(ctx: JobContext) -> JobResult:
    deleted = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            result = await db.execute(
                delete(WebchatSession).where(
                    WebchatSession.shop_id == shop_id, WebchatSession.expires_at < ctx.now - SESSION_GRACE
                )
            )
            deleted += int(result.rowcount or 0)  # type: ignore[attr-defined]
    return JobResult(affected=deleted)


MESSAGING_JOBS = [
    ScheduledJob("messaging_handoff_reminders", handoff_reminders, every_seconds=120),
    ScheduledJob("messaging_stuck_sending", stuck_sending, every_seconds=300),
    ScheduledJob("messaging_retention", retention, cron="10 4 * * *"),
    ScheduledJob("messaging_provider_events_cleanup", provider_events_cleanup, cron="20 4 * * *"),
    ScheduledJob("messaging_webchat_sessions_cleanup", webchat_sessions_cleanup, cron="25 4 * * *"),
]
