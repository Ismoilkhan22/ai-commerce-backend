"""Xodim xabarnomalari (db/notifications.md §2, 20 §2).

**Qachon** xabar ketishini domen hal qiladi (`notify_staff` — o'z tranzaksiyasida), **qanday** yetkazishni —
platforma: panelda doim ko'rinadi (realtime signal), bog'langan bo'lsa platforma botiga ham ketadi
(`platform.notification.created` → `TelegramDelivery`). Bir hodisa — bitta xabar: `dedup_key` unikal.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.notifications.models.orm import Notification, StaffNotificationSettings, StaffTelegramLink
from app.platform.notifications.schemas import (
    NotificationList,
    NotificationOut,
    NotificationSettingsIn,
    NotificationSettingsOut,
    TaskLink,
)
from app.platform.notifications.services.recipients import resolve_members
from app.platform.notifications.templates import STAFF_TEMPLATE_VERSION, priority_of, render
from app.shared.clock import utcnow
from app.shared.errors.base import NotFoundError, ValidationError, VersionConflictError
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.pagination import DEFAULT_LIMIT, decode_cursor, encode_cursor
from app.shared.types.actor import ActorContext

NOTIFICATION = "platform.notification"
_AGGREGATE_LINKS = {
    "commerce.order": "order",
    "commerce.stock_adjustment": "adjustment",
    "messaging.conversation": "conversation",
}


def _link(aggregate_type: str, aggregate_id: UUID, template_key: str) -> TaskLink | None:
    route = _AGGREGATE_LINKS.get(aggregate_type)
    if route is not None:
        return TaskLink(route=route, id=aggregate_id)
    if template_key == "staff.stock_reconcile_mismatch":
        return TaskLink(route="stock")
    if template_key == "staff.exchange_rate_stale":
        return TaskLink(route="exchange_rates")
    return None


def notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        template_key=row.template_key,
        priority=row.priority,
        title=row.title,
        body=row.body,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        link=_link(row.aggregate_type, row.aggregate_id, row.template_key),
        created_at=row.created_at,
        read_at=row.read_at,
        delivery_status=row.status,
    )


class NotificationService:
    async def notify_staff(
        self,
        db: AsyncSession,
        *,
        shop_id: UUID,
        actor: ActorContext,
        template_key: str,
        aggregate_type: str,
        aggregate_id: UUID,
        aggregate_version: int,
        variables: dict[str, Any],
        membership_ids: Iterable[UUID | None] = (),
        roles: Iterable[str] = (),
        branch_id: UUID | None = None,
        exclude: Iterable[UUID | None] = (),
        dedup_scope: str | None = None,
    ) -> list[UUID]:
        """Har qabul qiluvchiga bitta qator; takroriy chaqiruv (event qayta keldi) yangi qator bermaydi.
        `dedup_scope` — hodisa oynasi (masalan "24h"), bo'lmasa agregat versiyasi."""
        recipients = await resolve_members(
            db, shop_id, membership_ids=membership_ids, roles=roles, branch_id=branch_id
        )
        skip = {m for m in exclude if m is not None}
        priority = priority_of(template_key)
        created: list[UUID] = []
        for recipient in recipients:
            if recipient.membership_id in skip:
                continue  # o'zi qilgan amal haqida o'ziga xabar shart emas
            title, body = render(template_key, recipient.locale, variables)
            scope = dedup_scope or str(aggregate_version)
            notification_id = await db.scalar(
                insert(Notification)
                .values(
                    shop_id=shop_id,
                    template_key=template_key,
                    template_version=STAFF_TEMPLATE_VERSION,
                    locale=recipient.locale,
                    recipient_type="STAFF",
                    recipient_membership_id=recipient.membership_id,
                    priority=priority,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    aggregate_version=aggregate_version,
                    variables=variables,
                    title=title,
                    body=body,
                    dedup_key=f"{template_key}:{aggregate_type}:{aggregate_id}:{scope}:{recipient.membership_id}",
                )
                .on_conflict_do_nothing(index_elements=["shop_id", "dedup_key"])
                .returning(Notification.id)
            )
            if notification_id is None:
                continue
            created.append(notification_id)
            await write_outbox(
                db,
                schema="platform",
                event_type="platform.notification.created",
                actor=actor,
                shop_id=shop_id,
                aggregate_type=NOTIFICATION,
                aggregate_id=notification_id,
                aggregate_version=1,
                payload={
                    "notification_id": notification_id,
                    "recipient_membership_id": recipient.membership_id,
                    "template_key": template_key,
                    "priority": priority,
                },
            )
        return created

    # ------------------------------------------------------------------ bildirishnomalar markazi
    @staticmethod
    def _mine(actor: ActorContext) -> Any:
        return and_(
            Notification.shop_id == actor.shop_id, Notification.recipient_membership_id == actor.membership_id
        )

    async def unread_count(self, db: AsyncSession, actor: ActorContext) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(self._mine(actor), Notification.read_at.is_(None))
            )
            or 0
        )

    async def list(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        unread_only: bool,
        cursor: str | None,
        limit: int = DEFAULT_LIMIT,
    ) -> NotificationList:
        query = select(Notification).where(self._mine(actor))
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        if cursor:
            values = decode_cursor(cursor)
            try:
                at, last_id = datetime.fromisoformat(str(values["t"])), UUID(str(values["id"]))
            except (KeyError, ValueError) as exc:
                raise ValidationError(
                    "Cursor is invalid", fields=[{"field": "cursor", "code": "invalid_format", "params": {}}]
                ) from exc
            query = query.where(
                or_(
                    Notification.created_at < at,
                    and_(Notification.created_at == at, Notification.id < last_id),
                )
            )
        rows = (
            (
                await db.execute(
                    query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page, has_more = list(rows[:limit]), len(rows) > limit
        next_cursor = (
            encode_cursor({"t": page[-1].created_at.isoformat(), "id": str(page[-1].id)})
            if has_more and page
            else None
        )
        return NotificationList(
            items=[notification_out(n) for n in page],
            next_cursor=next_cursor,
            has_more=has_more,
            unread_count=await self.unread_count(db, actor),
        )

    async def mark_read(
        self, db: AsyncSession, actor: ActorContext, notification_id: UUID
    ) -> NotificationOut:
        row = (
            await db.execute(
                select(Notification).where(self._mine(actor), Notification.id == notification_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Notification not found")
        if row.read_at is None:
            row.read_at = utcnow()
            await db.flush()
        return notification_out(row)

    async def mark_all_read(self, db: AsyncSession, actor: ActorContext) -> int:
        result = await db.execute(
            update(Notification)
            .where(self._mine(actor), Notification.read_at.is_(None))
            .values(read_at=utcnow())
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # ------------------------------------------------------------------ sozlama
    async def settings(self, db: AsyncSession, actor: ActorContext) -> NotificationSettingsOut:
        row = await db.get(StaffNotificationSettings, actor.membership_id)
        linked = await self._linked(db, actor)
        if row is None:
            return NotificationSettingsOut(
                quiet_from=None,
                quiet_to=None,
                telegram_enabled=True,
                muted_types=[],
                telegram_linked=linked,
                version=0,
            )
        return NotificationSettingsOut(
            quiet_from=row.quiet_from,
            quiet_to=row.quiet_to,
            telegram_enabled=row.telegram_enabled,
            muted_types=list(row.muted_types),
            telegram_linked=linked,
            version=row.version,
        )

    async def save_settings(
        self, db: AsyncSession, actor: ActorContext, data: NotificationSettingsIn, expected_version: int
    ) -> NotificationSettingsOut:
        assert actor.shop_id is not None and actor.membership_id is not None
        row = (
            await db.execute(
                select(StaffNotificationSettings)
                .where(StaffNotificationSettings.membership_id == actor.membership_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        check_version(row.version if row else 0, expected_version)
        values = {
            "quiet_from": data.quiet_from,
            "quiet_to": data.quiet_to,
            "telegram_enabled": data.telegram_enabled,
            "muted_types": sorted(set(data.muted_types)),
        }
        if row is None:
            # Yo'q qatorni FOR UPDATE qulflamaydi: ikki parallel "birinchi saqlash" — bittasi yozadi,
            # qolganlari 409 oladi (QA 5a F2), unikal kalit xatosi 500 bo'lmaydi
            inserted = await db.scalar(
                insert(StaffNotificationSettings)
                .values(shop_id=actor.shop_id, membership_id=actor.membership_id, **values)
                .on_conflict_do_nothing(index_elements=["membership_id"])
                .returning(StaffNotificationSettings.membership_id)
            )
            if inserted is None:
                raise VersionConflictError(
                    "Version mismatch", current_version=1, your_version=expected_version
                )
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await db.flush()
        return await self.settings(db, actor)

    @staticmethod
    async def _linked(db: AsyncSession, actor: ActorContext) -> bool:
        link = await db.get(StaffTelegramLink, actor.actor_id)
        return link is not None and link.unlinked_at is None
