"""Xodim xabarini platforma botiga yetkazish (FSM-12, 06 §4.2 `notification_send`).

Uch qadam, tashqi chaqiruv tranzaksiyadan TASHQARIDA (05 §6, 3-qoida):
1. o'qish TX: holat, sozlama, ulanish → qaror (yuborish / to'xtatish / tinch soatdan keyin);
2. Telegram'ga yuborish;
3. yozish TX: SENT / FAILED / qayta urinish.

Idempotent: `SENT`, `FAILED`, `SUPPRESSED` bo'lsa hech narsa qilmaydi — event qayta kelsa ham bitta xabar.
5 marta vaqtinchalik xatodan keyin `FAILED` (FSM-12). Panelda xabar baribir ko'rinadi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.platform.notifications.models.orm import Notification, StaffNotificationSettings, StaffTelegramLink
from app.platform.notifications.telegram import TelegramSender, TelegramSendError
from app.platform.shops.models.orm import Shop
from app.platform.staff.models.orm import Membership
from app.shared.clock import utcnow
from app.shared.db.session import Database
from app.shared.events.registry import RetryLater

MAX_ATTEMPTS = 5
FINAL_STATUSES = frozenset({"SENT", "FAILED", "SUPPRESSED"})


@dataclass(frozen=True)
class _Plan:
    chat_id: int
    text: str
    attempt: int


def _in_quiet_hours(settings: StaffNotificationSettings | None, now_local: datetime) -> datetime | None:
    """Tinch soat ichida bo'lsa — yuborish vaqti (quiet_to, mahalliy vaqt), aks holda None."""
    if settings is None or settings.quiet_from is None or settings.quiet_to is None:
        return None
    start, end, current = settings.quiet_from, settings.quiet_to, now_local.timetz().replace(tzinfo=None)
    inside = start <= current < end if start < end else (current >= start or current < end)
    if not inside:
        return None
    resume = now_local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    return resume if resume > now_local else resume + timedelta(days=1)


class TelegramDelivery:
    def __init__(self, sender: TelegramSender) -> None:
        self.sender = sender

    async def deliver(self, database: Database, shop_id: UUID, notification_id: UUID) -> str:
        """Natija holati (SENT, SCHEDULED, SUPPRESSED, FAILED yoki o'zgarmagan yakuniy holat)."""
        plan = await self._prepare(database, shop_id, notification_id)
        if isinstance(plan, str):
            return plan
        try:
            await self.sender.send_message(plan.chat_id, plan.text)
        except TelegramSendError as exc:
            return await self._failed(database, shop_id, notification_id, plan, exc)
        async with database.transaction(shop_id) as db:
            row = await db.get(Notification, notification_id, with_for_update=True)
            if row is not None and row.status not in FINAL_STATUSES:
                row.status, row.sent_at, row.last_error_code = "SENT", utcnow(), None
        return "SENT"

    async def _prepare(self, database: Database, shop_id: UUID, notification_id: UUID) -> _Plan | str:
        async with database.transaction(shop_id) as db:
            row = await db.get(Notification, notification_id, with_for_update=True)
            if row is None or row.recipient_type != "STAFF":
                return "MISSING"
            if row.status in FINAL_STATUSES:
                return row.status
            now = utcnow()
            if row.scheduled_at is not None and row.scheduled_at > now:
                return row.status  # tinch soat tugashini kutmoqda — rekonsilyatsiya qaytadan chaqiradi
            membership = await db.get(Membership, row.recipient_membership_id)
            settings = await db.get(StaffNotificationSettings, row.recipient_membership_id)
            link = await db.get(StaffTelegramLink, membership.principal_id) if membership else None
            reason = None
            if membership is None or membership.status != "ACTIVE" or link is None or link.unlinked_at:
                reason = "NOT_LINKED"
            elif settings is not None and not settings.telegram_enabled:
                reason = "MUTED"
            elif row.priority != "HIGH" and settings is not None and row.template_key in settings.muted_types:
                reason = "MUTED"
            if reason is not None:
                row.status, row.suppressed_reason = "SUPPRESSED", reason
                return "SUPPRESSED"
            if row.priority != "HIGH":
                shop = await db.get(Shop, shop_id)
                tz = ZoneInfo(shop.timezone if shop else "Asia/Tashkent")
                resume = _in_quiet_hours(settings, now.astimezone(tz))
                if resume is not None:
                    row.status, row.scheduled_at = "SCHEDULED", resume
                    return "SCHEDULED"
            assert link is not None
            row.status, row.attempts = "SCHEDULED", row.attempts + 1
            text = "\n".join(part for part in (row.title, row.body) if part)
            return _Plan(chat_id=link.telegram_chat_id, text=text, attempt=row.attempts)

    async def _failed(
        self, database: Database, shop_id: UUID, notification_id: UUID, plan: _Plan, exc: TelegramSendError
    ) -> str:
        async with database.transaction(shop_id) as db:
            row = await db.get(Notification, notification_id, with_for_update=True)
            if row is None or row.status in FINAL_STATUSES:
                return row.status if row else "MISSING"
            row.last_error_code = exc.code
            if not exc.retryable:
                if exc.code == "BLOCKED":  # bot bloklangan — ulanish uziladi, keyingilar yuborilmaydi
                    membership = await db.get(Membership, row.recipient_membership_id)
                    link = await db.get(StaffTelegramLink, membership.principal_id) if membership else None
                    if link is not None and link.unlinked_at is None:
                        link.unlinked_at, link.last_error_code = utcnow(), exc.code
                row.status, row.failed_at = "FAILED", utcnow()
                return "FAILED"
            if plan.attempt >= MAX_ATTEMPTS:
                row.status, row.failed_at = "FAILED", utcnow()
                return "FAILED"
        raise RetryLater(exc.retry_after or min(2**plan.attempt * 5, 300))


async def due_scheduled(database: Database, now: datetime, limit: int = 200) -> list[tuple[UUID, UUID]]:
    """Rekonsilyatsiya: tinch soati tugagan yoki navbati yo'qolgan xodim xabarlari `(shop_id, id)`.

    `notifications` RLS bilan — har shop alohida o'qiladi (shoplar ro'yxati RLS'siz)."""
    result: list[tuple[UUID, UUID]] = []
    async with database.transaction() as db:
        shop_ids = (await db.execute(select(Shop.id).where(Shop.status != "CLOSED"))).scalars().all()
    for shop_id in shop_ids:
        async with database.transaction(shop_id) as db:
            rows = await db.execute(
                select(Notification.id)
                .where(
                    Notification.shop_id == shop_id,
                    Notification.recipient_type == "STAFF",
                    Notification.status.in_(("PENDING", "SCHEDULED")),
                    Notification.created_at < now - timedelta(minutes=5),
                    (Notification.scheduled_at.is_(None)) | (Notification.scheduled_at <= now),
                )
                .limit(limit)
            )
            result.extend((shop_id, notification_id) for notification_id in rows.scalars())
    return result
