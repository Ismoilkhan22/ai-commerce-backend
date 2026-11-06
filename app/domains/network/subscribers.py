"""network tinglovchilari: ommaviy taklif proyeksiyasini manba o'zgarganda yangilash (db/network.md).

`catalog`/`commerce` kodi import qilinmaydi — faqat event turi, shop_id va payload'dagi `sku_id`
(TC-NET-04). SKU'siz event (mahsulot holati, kurs) — shopning barcha ommaviy takliflari tekshiriladi.
Takror kelsa natija bir xil: o'zgarish bo'lmasa `listing_version` oshmaydi.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.domains.network.models.orm import PublicOffer, StockReport
from app.domains.network.providers import NetworkServices
from app.shared.clock import utcnow
from app.shared.events.registry import EventContext, subscriber
from app.shared.types.actor import ActorContext


@subscriber(
    "network.offer_refresh",
    "catalog.product.published",
    "catalog.product.hidden",
    "catalog.product.archived",
    "catalog.product.updated",
    "catalog.sku.changed",
    "catalog.price.changed",
    "catalog.exchange_rate.updated",
    "commerce.stock.changed",
    schema="network",
)
async def refresh_offers(ctx: EventContext) -> None:
    shop_id = ctx.envelope.shop_id
    if shop_id is None:
        return
    network: NetworkServices = ctx.services.network
    raw = ctx.envelope.payload.get("sku_id")
    if raw:
        sku_ids = [UUID(str(raw))]
    else:
        rows = await ctx.session.execute(select(PublicOffer.sku_id).where(PublicOffer.shop_id == shop_id))
        sku_ids = list(rows.scalars())
    if sku_ids:
        await network.offers.refresh(ctx.session, ActorContext.system(shop_id), shop_id, sku_ids)


@subscriber(
    "network.shop_status",
    "platform.shop.suspended",
    "platform.shop.closed",
    "platform.shop.activated",
    schema="network",
)
async def shop_status_changed(ctx: EventContext) -> None:
    shop_id = ctx.envelope.shop_id
    if shop_id is None:
        return
    network: NetworkServices = ctx.services.network
    actor = ActorContext.system(shop_id)
    if ctx.envelope.event_type == "platform.shop.activated":
        await network.offers.revive_shop(ctx.session, actor, shop_id)
    else:
        await network.offers.suspend_shop(ctx.session, actor, shop_id)  # BL-070, TC-NET-03


@subscriber("network.pos_stock_result", "commerce.pos_stock.applied", schema="network")
async def pos_stock_applied(ctx: EventContext) -> None:
    """M22: commerce natijasi — hamkor `GET /partner/stock/reports/{id}` da ko'radi."""
    payload = ctx.envelope.payload
    report = await ctx.session.get(StockReport, UUID(str(payload["report_id"])))
    if report is None or report.status == "PROCESSED":
        return
    report.status, report.results, report.processed_at = (
        "PROCESSED",
        dict(payload.get("summary") or {}),
        utcnow(),
    )
