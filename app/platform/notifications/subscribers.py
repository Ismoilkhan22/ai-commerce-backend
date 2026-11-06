"""platform/notifications tinglovchilari va rejali ishlari.

- `platform.notification.created` → platforma botiga yetkazish (tranzaksiyasiz: Telegram — tashqi chaqiruv;
  idempotentlik — xabar holati).
- `notifications_cleanup` (har kecha): xabarnomalar 90 kun, ishlatilgan/eskirgan bog'lash kodlari 1 kun.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select

from app.platform.notifications.models.orm import Notification, TelegramLinkCode
from app.platform.notifications.providers import from_state
from app.platform.shops.models.orm import Shop
from app.shared.events.registry import EventContext, JobContext, JobResult, subscriber

NOTIFICATION_RETENTION = timedelta(days=90)  # db/notifications.md §2 (taklif)
CODE_RETENTION = timedelta(days=1)


@subscriber(
    "platform.notifications.telegram", "platform.notification.created", schema="platform", transactional=False
)
async def deliver_to_platform_bot(ctx: EventContext) -> None:
    if ctx.envelope.shop_id is None:
        return
    notification_id = UUID(str(ctx.envelope.payload["notification_id"]))
    await from_state(ctx.services).delivery.deliver(ctx.database, ctx.envelope.shop_id, notification_id)


async def notifications_cleanup(ctx: JobContext) -> JobResult:
    deleted_codes = 0
    async with ctx.database.transaction() as db:
        result = await db.execute(
            delete(TelegramLinkCode).where(TelegramLinkCode.expires_at < ctx.now - CODE_RETENTION)
        )
        deleted_codes = int(getattr(result, "rowcount", 0) or 0)
        shop_ids = (await db.execute(select(Shop.id))).scalars().all()
    deleted = 0
    for shop_id in shop_ids:  # notifications — RLS: har shop o'z kontekstida
        async with ctx.database.transaction(shop_id) as db:
            result = await db.execute(
                delete(Notification).where(
                    Notification.shop_id == shop_id,
                    Notification.created_at < ctx.now - NOTIFICATION_RETENTION,
                )
            )
            deleted += int(getattr(result, "rowcount", 0) or 0)
    return JobResult(
        processed=len(shop_ids), affected=deleted + deleted_codes, details={"codes": deleted_codes}
    )
