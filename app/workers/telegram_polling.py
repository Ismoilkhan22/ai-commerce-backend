"""Lokal Telegram long polling (5b): ochiq HTTPS manzil yo'q — webhook o'rniga `getUpdates`.

`TELEGRAM_MODE=polling` (lokalda standart): `make worker` shu tsiklni ham ishga tushiradi. Har shopning
ulangan (polling rejimidagi) botlari navbat bilan so'raladi; har update webhook bilan BIR XIL yo'ldan o'tadi
(`InboundService.ingest`: takror himoyasi, xaridor, suhbat, FSM-04). Oxirgi update raqami akkaunt
sozlamasida (`settings.polling_offset`) — PII emas. Production'da webhook (bu tsikl ishlamaydi).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import select

from app.domains.messaging.channels.base import ChannelSendError
from app.domains.messaging.channels.telegram import parse_update
from app.domains.messaging.common import SENDABLE_CHANNEL_STATUSES
from app.domains.messaging.models.orm import ChannelAccount
from app.domains.messaging.providers import from_state
from app.platform.jobs.services.shops import open_shop_ids
from app.workers.runtime import WorkerRuntime

logger = structlog.get_logger(__name__)
IDLE_SECONDS = 2.0
BUSY_SECONDS = 0.3


def _update_id(update: dict[str, Any]) -> int:
    value = update.get("update_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


async def poll_once(rt: WorkerRuntime) -> int:
    svc = from_state(rt.services)
    if svc.config.telegram_mode != "polling":
        return 0
    handled = 0
    for shop_id in await open_shop_ids(rt.database):
        async with rt.database.transaction(shop_id) as db:
            accounts = [
                (a.id, a.token_enc, (a.settings or {}).get("polling_offset"))
                for a in await svc.channels.polling_accounts(db, shop_id)
            ]
        for account_id, token, offset in accounts:
            if not token:
                continue
            try:
                updates = await svc.adapters.telegram.get_updates(
                    token, offset if isinstance(offset, int) else None, 0
                )
            except ChannelSendError as exc:
                logger.warning("telegram.polling_failed", code=exc.code)
                continue
            for update in sorted(updates, key=_update_id):
                update_id = _update_id(update)
                if update_id < 0:
                    continue
                async with rt.database.transaction(shop_id) as db:
                    account = (
                        await db.execute(
                            select(ChannelAccount).where(ChannelAccount.id == account_id).with_for_update()
                        )
                    ).scalar_one_or_none()
                    if account is None or account.status not in SENDABLE_CHANNEL_STATUSES:
                        break
                    inbound = parse_update(update)
                    if inbound is not None:
                        await svc.inbound.ingest(db, account, inbound)
                    account.settings = {**(account.settings or {}), "polling_offset": update_id + 1}
                handled += 1
    return handled


async def run_forever(rt: WorkerRuntime) -> None:
    logger.info("telegram.polling_started")
    while True:
        try:
            handled = await poll_once(rt)
        except Exception as exc:  # tsikl to'xtamasin; xato turi logga (matn PII bo'lishi mumkin)
            logger.error("telegram.polling_error", error=type(exc).__name__)
            handled = 0
        await asyncio.sleep(BUSY_SECONDS if handled else IDLE_SECONDS)
