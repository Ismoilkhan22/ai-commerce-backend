"""Katalog importi fon bosqichlari (18 §3, §14) — outbox event'lari orqali.

- `catalog.import.chunk` — sinov yoki yozishning bitta bo'lagi; tugagach keyingisini o'zi qo'yadi.
- `commerce.import_stock.applied` — commerce qoldiqni qo'lladi → import tayyor.
- `catalog_import_maintenance` (har 15 daqiqa): 24 soatlik sinov eskiradi, jim qolgan bo'lak qayta qo'yiladi
  (06 §6), 30 kundan eski import qatorlari tozalanadi.
"""

from __future__ import annotations

from uuid import UUID

from app.domains.catalog.providers import CatalogServices
from app.platform.jobs.services.shops import open_shop_ids
from app.shared.events.registry import EventContext, JobContext, JobResult, ScheduledJob, subscriber


@subscriber("catalog.import_runner", "catalog.import.chunk", schema="catalog", transactional=False)
async def run_import_chunk(ctx: EventContext) -> None:
    catalog: CatalogServices = ctx.services.catalog
    payload = ctx.envelope.payload
    assert ctx.envelope.shop_id is not None
    await catalog.imports.run_chunk(
        ctx.database,
        ctx.envelope.shop_id,
        UUID(str(payload["batch_id"])),
        str(payload["phase"]),
        int(payload["offset"]),
    )


@subscriber("catalog.import_finish", "commerce.import_stock.applied", schema="catalog")
async def finish_import(ctx: EventContext) -> None:
    catalog: CatalogServices = ctx.services.catalog
    payload = ctx.envelope.payload
    assert ctx.envelope.shop_id is not None
    await catalog.imports.finish_stock(
        ctx.session, ctx.envelope.shop_id, UUID(str(payload["batch_id"])), dict(payload)
    )


async def catalog_import_maintenance(ctx: JobContext) -> JobResult:
    catalog: CatalogServices = ctx.services.catalog
    shops = await open_shop_ids(ctx.database)
    totals: dict[str, int] = {}
    for shop_id in shops:
        for key, value in (await catalog.imports.maintain(ctx.database, shop_id)).items():
            totals[key] = totals.get(key, 0) + value
    return JobResult(processed=len(shops), affected=sum(totals.values()), details=totals)


IMPORT_JOBS = (ScheduledJob("catalog_import_maintenance", catalog_import_maintenance, every_seconds=900),)
