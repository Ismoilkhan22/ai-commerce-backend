"""catalog tinglovchilari va rejali ishlari (S0-06).

- `catalog.hardware_spec.updated` → har shopda bog'lanmagan SKU'larni kutubxonaga avtomatik qayta bog'lash
  (2-modulda qo'lda "Qayta tekshirish" tugmasi edi). Ehtiyotkor qoidalar o'sha-o'sha: faqat aniq bitta mos
  kelsa; xodim tanlagan yoki uzgan bog'lanishga tegilmaydi. Tranzaksiyasiz — har shop alohida tranzaksiyada;
  takror ishlasa natija bir xil.
- `exchange_rate_staleness` (har soat): dollar narxi bor, lekin kursi 3 kundan eski (yoki yo'q) shop →
  ega va menejerga vazifa va xabar, kunda bir marta (BL-018). Yangi kurs kiritilganda vazifa o'zi yopiladi.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pricing.models.orm import CurrentPrice, ExchangeRate, PriceVersion
from app.domains.catalog.pricing.services.pricing_service import RATE_MAX_AGE, RATES_SUBJECT
from app.domains.catalog.providers import CatalogServices
from app.platform.jobs.services.shops import open_shop_ids
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import EXCHANGE_RATE_STALE, TaskService
from app.shared.events.registry import EventContext, JobContext, JobResult, ScheduledJob, subscriber
from app.shared.types.actor import ActorContext

_tasks = TaskService()
_notifications = NotificationService()
STALE_HOURS = int(RATE_MAX_AGE.total_seconds() // 3600)


@subscriber(
    "catalog.relink_on_spec_updated", "catalog.hardware_spec.updated", schema="catalog", transactional=False
)
async def relink_on_spec_updated(ctx: EventContext) -> None:
    catalog: CatalogServices = ctx.services.catalog
    for shop_id in await open_shop_ids(ctx.database):
        async with ctx.database.transaction(shop_id) as db:
            await catalog.links.auto_link_all(db, ActorContext.system(shop_id))


async def _stale(db: AsyncSession, shop_id: UUID, now: datetime) -> tuple[bool, datetime | None]:
    """(eskirganmi, oxirgi kurs vaqti). Dollar narxi bo'lmasa — eskirgan hisoblanmaydi."""
    usd_prices = await db.scalar(
        select(
            exists().where(
                CurrentPrice.shop_id == shop_id,
                PriceVersion.id == CurrentPrice.price_version_id,
                PriceVersion.currency == "USD",
            )
        )
    )
    if not usd_prices:
        return False, None
    latest: datetime | None = await db.scalar(
        select(func.max(ExchangeRate.effective_at)).where(
            ExchangeRate.shop_id == shop_id, ExchangeRate.effective_at <= now
        )
    )
    return latest is None or latest < now - RATE_MAX_AGE, latest


async def exchange_rate_staleness(ctx: JobContext) -> JobResult:
    shops = await open_shop_ids(ctx.database)
    stale = created = 0
    for shop_id in shops:
        async with ctx.database.transaction(shop_id) as db:
            is_stale, latest = await _stale(db, shop_id, ctx.now)
            if not is_stale:
                continue
            stale += 1
            actor = ActorContext.system(shop_id)
            task = await _tasks.open(
                db,
                shop_id=shop_id,
                actor=actor,
                type=EXCHANGE_RATE_STALE,
                subject_type=RATES_SUBJECT,
                subject_id=shop_id,
                # Bitta "eskirish davri" — bitta vazifa: kalit oxirgi kurs vaqtiga bog'liq, kun bo'yicha emas.
                # Yopilgan vazifa yangi davrni to'smaydi, har kuni dublikat ochilmaydi (QA 5a F5)
                dedup_key=f"fx_stale:{shop_id}:{latest.isoformat() if latest else 'none'}",
                assignee_role="OWNER",
                params={"hours": STALE_HOURS, "has_rate": latest is not None},
            )
            if task is None:
                continue
            created += 1
            await _notifications.notify_staff(
                db,
                shop_id=shop_id,
                actor=actor,
                template_key="staff.exchange_rate_stale",
                aggregate_type=RATES_SUBJECT,
                aggregate_id=shop_id,
                aggregate_version=1,
                variables={"hours": STALE_HOURS},
                roles=("OWNER", "MANAGER"),
                dedup_scope=f"task:{task.id}",
            )
    return JobResult(processed=len(shops), affected=created, details={"stale_shops": stale})


CATALOG_JOBS = (ScheduledJob("exchange_rate_staleness", exchange_rate_staleness, every_seconds=3600),)
