"""Hisobot proyeksiyalarini mavjud ma'lumotdan qayta qurish (bir martalik, 19 §3.3).

    make reporting-backfill                       # hamma ochiq shop
    uv run python -m app.workers.reporting_backfill --shop <uuid>

Har shop alohida tranzaksiyada (RLS). Takror ishga tushirish xavfsiz: natija bir xil. Jonli worker'lar
to'xtatilgan holatda ishga tushiring (dev: `make worker` ni to'xtating).
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

import structlog

from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.dependencies import get_catalog_query, get_reporting_sources
from app.domains.reporting.backfill import rebuild_shop
from app.platform.jobs.services.shops import open_shop_ids
from app.shared.clock import utcnow
from app.shared.db.session import Database

logger = structlog.get_logger(__name__)


async def run(shop_ids: list[UUID] | None = None) -> dict[UUID, dict[str, int]]:
    settings = get_settings()
    database = Database(settings.database_config())
    catalog, sources = get_catalog_query(), get_reporting_sources()
    result: dict[UUID, dict[str, int]] = {}
    try:
        for shop_id in shop_ids or await open_shop_ids(database):
            async with database.transaction(shop_id) as db:
                result[shop_id] = await rebuild_shop(db, catalog, sources, shop_id, utcnow())
            logger.info("reporting.backfill_done", shop_id=str(shop_id), **result[shop_id])
    finally:
        await database.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", type=UUID, action="append", help="faqat shu shop (takrorlash mumkin)")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "local")
    result = asyncio.run(run(args.shop))
    for shop_id, counts in result.items():
        print(shop_id, counts)  # noqa: T201 — CLI natijasi
    print(f"{len(result)} ta shop qayta qurildi")  # noqa: T201


if __name__ == "__main__":
    main()
