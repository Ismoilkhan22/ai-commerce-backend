"""Hamkor API (M30, BL-089) — `/api/v1/partner/*`, `Authorization: Bearer cos_<prefix>_<sir>`.

Kassa / ERP / agentlik: mahsulotlar va narx (`catalog.read`), mavjudlik (`stock.read`), narx yozish
(`prices.write` — oddiy narx versiyasi va audit, sabab "Hamkor API: <kalit nomi>"). Qoldiq yozish — keyingi
bo'lak (M22, ustuvorlik va nizo qoidasi BR-X12 bilan). Tezlik: kalitga 120/daqiqa.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import ApiKey, StockReport
from app.domains.network.services.api_keys import PartnerAuth
from app.shared.db.session import Database
from app.shared.errors.base import ForbiddenError, NotFoundError
from app.shared.events.outbox import write_outbox
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(tags=["partner"])


@dataclass(frozen=True)
class PartnerContext:
    db: AsyncSession
    auth: PartnerAuth

    def need(self, scope: str) -> None:
        if scope not in self.auth.scopes:
            raise ForbiddenError("API key scope missing", permission=scope)


async def partner_context(
    request: Request, authorization: Annotated[str | None, Header(max_length=300)] = None
) -> AsyncIterator[PartnerContext]:
    database: Database = request.app.state.db
    async with database.transaction() as db:
        auth = await request.app.state.network.api_keys.authenticate(db, authorization)
        limiter: RateLimiter = request.app.state.rate_limiter
        await enforce(limiter, f"partner:{auth.key_id}", limit=120)
        yield PartnerContext(db=db, auth=auth)


Partner = Annotated[PartnerContext, Depends(partner_context, scope="function")]


class PartnerSku(BaseModel):
    sku_id: UUID
    sku_code: str
    title: str
    sellable: bool
    price_amount_minor: int | None
    price_currency: str | None
    price_uzs_minor: int | None
    availability: str | None  # `stock.read` bo'lsa


class PartnerSkuList(BaseModel):
    items: list[PartnerSku]


class PartnerPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_minor: int = Field(ge=1, le=10**15)
    currency: Literal["UZS", "USD"]


class PartnerPriceOut(BaseModel):
    sku_id: UUID
    changed: bool


@router.get("/skus", response_model=PartnerSkuList)
async def partner_skus(
    request: Request,
    ctx: Partner,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> PartnerSkuList:
    ctx.need("catalog.read")
    offers = request.app.state.network.offers
    catalog, stock = offers.catalog, offers.stock
    shop_id = ctx.auth.shop_id
    ids = await catalog.pick_sku_ids(ctx.db, shop_id, q, limit)
    snaps = await catalog.get_skus(ctx.db, shop_id, ids)
    avail = await stock.availability(ctx.db, shop_id, ids) if "stock.read" in ctx.auth.scopes else {}
    return PartnerSkuList(
        items=[
            PartnerSku(
                sku_id=s.sku_id,
                sku_code=s.sku_code,
                title=s.title,
                sellable=s.sellable,
                price_amount_minor=s.amount_minor,
                price_currency=s.currency,
                price_uzs_minor=s.uzs_amount_minor,
                availability=avail[s.sku_id].status if s.sku_id in avail else None,
            )
            for s in (snaps[i] for i in ids if i in snaps)
        ]
    )


@router.put("/skus/{sku_id}/price", response_model=PartnerPriceOut)
async def partner_set_price(
    sku_id: UUID, body: PartnerPriceIn, request: Request, ctx: Partner
) -> PartnerPriceOut:
    """Narx versiyasi va audit (`actor_id` = kalit). O'zgarmagan narx — `changed: false`."""
    ctx.need("prices.write")
    key = await ctx.db.get(ApiKey, ctx.auth.key_id)
    name = key.name if key else "API"
    port = request.app.state.catalog_price
    changed = await port.set_price(
        ctx.db, ctx.auth.actor, sku_id, body.amount_minor, body.currency, f"Hamkor API: {name}"[:300]
    )
    return PartnerPriceOut(sku_id=sku_id, changed=changed)


# ------------------------------------------------------------------ M22: qoldiq yuborish (BR-X12)
class StockItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_id: UUID
    branch_id: UUID
    on_hand: int = Field(ge=0, le=1_000_000)
    observed_at: datetime  # kassada qachon sanalgan — eskisi yangi o'zgarish ustidan yozmaydi


class StockReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[StockItemIn] = Field(min_length=1, max_length=200)


class StockReportOut(BaseModel):
    report_id: UUID
    status: str
    results: dict[str, Any] | None


@router.put("/stock", response_model=StockReportOut, status_code=202)
async def partner_stock(body: StockReportIn, ctx: Partner) -> StockReportOut:
    """Qoldiq paketi qabul qilinadi va fonda qo'llanadi: farq — tuzatish (kalit sozlamasiga ko'ra darhol yoki
    tasdiqqa); eski ma'lumot (`observed_at` oxirgi o'zgarishdan oldin) yoki band qilinganidan kam — nizo."""
    ctx.need("stock.write")
    report = StockReport(shop_id=ctx.auth.shop_id, key_id=ctx.auth.key_id, items_count=len(body.items))
    ctx.db.add(report)
    await ctx.db.flush()
    await write_outbox(
        ctx.db,
        schema="network",
        event_type="network.pos_stock.received",
        actor=ctx.auth.actor,
        shop_id=ctx.auth.shop_id,
        aggregate_type="network.stock_report",
        aggregate_id=report.id,
        aggregate_version=1,
        payload={
            "report_id": report.id,
            "auto_apply": ctx.auth.stock_auto_apply,
            "requested_by": ctx.auth.created_by,
            "items": [
                {
                    "sku_id": i.sku_id,
                    "branch_id": i.branch_id,
                    "on_hand": i.on_hand,
                    "observed_at": i.observed_at.isoformat(),
                }
                for i in body.items
            ],
        },
    )
    return StockReportOut(report_id=report.id, status=report.status, results=None)


@router.get("/stock/reports/{report_id}", response_model=StockReportOut)
async def partner_stock_report(report_id: UUID, ctx: Partner) -> StockReportOut:
    ctx.need("stock.write")
    report = await ctx.db.get(StockReport, report_id)
    if report is None or report.shop_id != ctx.auth.shop_id:
        raise NotFoundError("Report not found")
    return StockReportOut(report_id=report.id, status=report.status, results=report.results)
