"""commerce rejali ishlari (06 §5.2, DEC-104, DEC-134). Hech biri buyurtma yoki bandni avtomatik bekor
QILMAYDI — faqat vazifa va xabar (business/05, 4-qism). Har ish holat bo'yicha tanlaydi va `dedup_key` bilan
ishlaydi: ikki marta ishlasa ham bitta vazifa, o'tkazib yuborilgan ishga tushish keyingisida yetib olinadi.

- `order_confirm_reminder` (har 15 daq): "tasdiq kutilmoqda" 24 soatdan (shop sozlamasi) eski.
- `reservation_review` (har 15 daq): ochiq band `review_at` dan o'tgan → menejerga "Kutamiz / Bekor".
- `stock_reconcile` (har kecha 03:30): daftar yig'indisi ≠ qoldiq → vazifa va alert; AVTOMATIK TUZATILMAYDI.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import RESERVATION_REVIEW_HOURS, load_policy
from app.domains.commerce.orders.models.orm import Order, Reservation
from app.domains.commerce.orders.services.views import OPEN_RESERVATIONS, REVIEWABLE
from app.domains.commerce.providers import CommerceServices
from app.domains.commerce.state_machine import ORDER
from app.platform.jobs.services.shops import open_shop_ids
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import (
    ORDER_CONFIRM_REMINDER,
    RESERVATION_REVIEW,
    STOCK_RECONCILE_MISMATCH,
    TaskService,
)
from app.shared.events.registry import JobContext, JobResult, ScheduledJob
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

_tasks = TaskService()
_notifications = NotificationService()
SUPERVISORS = ("OWNER", "MANAGER")


async def _confirm_reminders(db: AsyncSession, shop_id: UUID, now: datetime) -> tuple[int, int]:
    policy = await load_policy(db, shop_id)
    hours = policy.unconfirmed_after_hours
    orders = (
        (
            await db.execute(
                select(Order).where(
                    Order.shop_id == shop_id,
                    Order.status == "PENDING_CONFIRMATION",
                    Order.submitted_at <= now - timedelta(hours=hours),
                )
            )
        )
        .scalars()
        .all()
    )
    actor = ActorContext.system(shop_id)
    created = 0
    for order in orders:
        task = await _tasks.open(
            db,
            shop_id=shop_id,
            actor=actor,
            type=ORDER_CONFIRM_REMINDER,
            subject_type=ORDER,
            subject_id=order.id,
            dedup_key=f"order_reminder:{order.id}:{hours}h",
            assignee_membership_id=order.assigned_membership_id,
            assignee_role="MANAGER",
            branch_id=order.branch_id,
            params={"order_number": order.number, "hours": hours},
        )
        if task is None:
            continue
        created += 1
        await _notifications.notify_staff(
            db,
            shop_id=shop_id,
            actor=actor,
            template_key="staff.order_confirm_reminder",
            aggregate_type=ORDER,
            aggregate_id=order.id,
            aggregate_version=order.version,
            variables={"order_number": order.number, "hours": hours},
            membership_ids=[order.assigned_membership_id],
            roles=SUPERVISORS,
            branch_id=order.branch_id,
            dedup_scope=f"{hours}h",
        )
    return len(orders), created


async def order_confirm_reminder(ctx: JobContext) -> JobResult:
    processed = affected = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            seen, created = await _confirm_reminders(db, shop_id, ctx.now)
        processed, affected = processed + seen, affected + created
    return JobResult(processed=processed, affected=affected)


async def _reservation_reviews(db: AsyncSession, shop_id: UUID, now: datetime) -> tuple[int, int]:
    rows = (
        await db.execute(
            select(Order, func.min(Reservation.review_at))
            .join(Reservation, (Reservation.shop_id == Order.shop_id) & (Reservation.order_id == Order.id))
            .where(
                Order.shop_id == shop_id,
                Order.status.in_(REVIEWABLE),
                Reservation.status.in_(OPEN_RESERVATIONS),
                Reservation.review_at <= now,
            )
            .group_by(Order.id)
        )
    ).all()
    actor = ActorContext.system(shop_id)
    created = 0
    for order, review_at in rows:
        window = int(review_at.timestamp())  # "Kutamiz" muddatni suradi → yangi oyna, yangi vazifa
        task = await _tasks.open(
            db,
            shop_id=shop_id,
            actor=actor,
            type=RESERVATION_REVIEW,
            subject_type=ORDER,
            subject_id=order.id,
            dedup_key=f"reservation_review:{order.id}:{window}",
            assignee_role="MANAGER",
            branch_id=order.branch_id,
            params={"order_number": order.number, "hours": RESERVATION_REVIEW_HOURS},
            due_at=review_at,
        )
        if task is None:
            continue
        created += 1
        await _notifications.notify_staff(
            db,
            shop_id=shop_id,
            actor=actor,
            template_key="staff.reservation_review",
            aggregate_type=ORDER,
            aggregate_id=order.id,
            aggregate_version=order.version,
            variables={"order_number": order.number, "hours": RESERVATION_REVIEW_HOURS},
            roles=SUPERVISORS,
            branch_id=order.branch_id,
            dedup_scope=f"review:{window}",
        )
    return len(rows), created


async def reservation_review(ctx: JobContext) -> JobResult:
    processed = affected = 0
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            seen, created = await _reservation_reviews(db, shop_id, ctx.now)
        processed, affected = processed + seen, affected + created
    return JobResult(processed=processed, affected=affected)


async def stock_reconcile(ctx: JobContext) -> JobResult:
    """Farq — xato belgisi; uni avtomatik "yashirish" xavfli (BL-022, DEC-138 5-qaror)."""
    commerce: CommerceServices = ctx.services.commerce
    shops = await open_shop_ids(ctx.database)
    shops_with_mismatch = mismatches = 0
    day = ctx.now.date().isoformat()
    for shop_id in shops:
        async with ctx.database.transaction(shop_id) as db:
            found = await commerce.stock.reconcile(db, shop_id)
            if not found:
                continue
            shops_with_mismatch += 1
            mismatches += len(found)
            logger.error("stock.reconcile_mismatch", shop_id=str(shop_id), count=len(found))  # Sentry alert
            actor = ActorContext.system(shop_id)
            task = await _tasks.open(
                db,
                shop_id=shop_id,
                actor=actor,
                type=STOCK_RECONCILE_MISMATCH,
                subject_type="commerce.stock",
                subject_id=shop_id,
                dedup_key=f"stock_reconcile:{shop_id}:{day}",
                assignee_role="OWNER",
                priority="HIGH",
                params={"count": len(found), "day": day},
            )
            if task is not None:
                await _notifications.notify_staff(
                    db,
                    shop_id=shop_id,
                    actor=actor,
                    template_key="staff.stock_reconcile_mismatch",
                    aggregate_type="commerce.stock",
                    aggregate_id=shop_id,
                    aggregate_version=1,
                    variables={"count": len(found)},
                    roles=SUPERVISORS,
                    dedup_scope=day,
                )
    return JobResult(
        processed=len(shops),
        affected=shops_with_mismatch,
        # `alert` — platforma panelidagi "Fon ishlari" sahifasida ogohlantirish (QA 5a I7).
        # Vazifa esa shop egasiga: qoldiq — uning mulki, tekshirish ham uniki
        details={
            "shops_with_mismatch": shops_with_mismatch,
            "mismatches": mismatches,
            "alert": mismatches > 0,
        },
    )


COMMERCE_JOBS = (
    ScheduledJob("order_confirm_reminder", order_confirm_reminder, every_seconds=900),
    ScheduledJob("reservation_review", reservation_review, every_seconds=900),
    ScheduledJob("stock_reconcile", stock_reconcile, cron="30 3 * * *"),
)
