"""Shop paneli: hisobotlar (11 §9.x, 19 §4). Faqat o'qish; ega va menejer (`reporting.view`).
Tannarx, foyda va AI xarajati (pul) — faqat ega (`reporting.margin.read`, DEC-146): `/profit` menejerga 403,
boshqa hisobotlarda tannarx maydonlari `null`/ustunsiz.

Davr `from`/`to` (shop vaqtidagi sana, ikkalasi ham kiradi); berilmasa — oxirgi 30 kun. Filial doirasi:
`branch_id` + xodimning o'z filiallari. CSV eksport: shaxsiy ma'lumotsiz, formula belgisi bilan boshlangan
matn `'` bilan himoyalangan.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.domains.reporting import permissions as perm
from app.domains.reporting.providers import ReportingServices, reporting_services
from app.domains.reporting.schemas import (
    AiUsage,
    ExportReport,
    OperatorPerformance,
    Profit,
    SalesByCategory,
    SalesDaily,
    SalesSummary,
    StockValue,
    TopProducts,
    WarrantyStats,
)
from app.domains.reporting.services import export
from app.domains.reporting.services.reports import Scope, hide_ai_cost, hide_stock_cost
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.errors.base import ForbiddenError

router = APIRouter(prefix="/reporting", tags=["reporting"])

Reporting = Annotated[ReportingServices, Depends(reporting_services)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.REPORTING_VIEW))]
CanMargin = Annotated[RequestContext, Depends(require_permission(perm.REPORTING_MARGIN_READ))]


def _sees_cost(ctx: RequestContext) -> bool:
    return perm.REPORTING_MARGIN_READ in ctx.actor.permissions


DateFrom = Annotated[date | None, Query(alias="from", description="Boshlanish sanasi (shop vaqti)")]
DateTo = Annotated[
    date | None, Query(alias="to", description="Tugash sanasi (shop vaqti), shu kun ham kiradi")
]
BranchId = Annotated[UUID | None, Query()]
Source = Annotated[
    str | None,
    Query(pattern="^(AI|STOREFRONT|STAFF|QUOTE|OFFLINE)$", description="Sotuv manbasi; OFFLINE — tez sotuv"),
]


async def _scope(
    ctx: RequestContext,
    svc: ReportingServices,
    date_from: date | None,
    date_to: date | None,
    branch_id: UUID | None = None,
    source: str | None = None,
) -> Scope:
    return await svc.reports.scope(
        ctx.db, ctx.actor, date_from=date_from, date_to=date_to, branch_id=branch_id, source=source
    )


@router.get("/sales/summary", response_model=SalesSummary)
async def sales_summary(
    ctx: CanView,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
    source: Source = None,
) -> SalesSummary:
    return await svc.reports.sales_summary(
        ctx.db, await _scope(ctx, svc, date_from, date_to, branch_id, source)
    )


@router.get("/sales/daily", response_model=SalesDaily)
async def sales_daily(
    ctx: CanView,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
    source: Source = None,
) -> SalesDaily:
    return await svc.reports.sales_daily(
        ctx.db, await _scope(ctx, svc, date_from, date_to, branch_id, source)
    )


@router.get("/sales/top-products", response_model=TopProducts)
async def top_products(
    ctx: CanView,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
    source: Source = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TopProducts:
    scope = await _scope(ctx, svc, date_from, date_to, branch_id, source)
    return await svc.reports.top_products(ctx.db, scope, limit)


@router.get("/sales/by-category", response_model=SalesByCategory)
async def sales_by_category(
    ctx: CanView,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
    source: Source = None,
) -> SalesByCategory:
    return await svc.reports.by_category(
        ctx.db, await _scope(ctx, svc, date_from, date_to, branch_id, source)
    )


@router.get("/profit", response_model=Profit)
async def profit(
    ctx: CanMargin,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
    source: Source = None,
) -> Profit:
    return await svc.reports.profit(ctx.db, await _scope(ctx, svc, date_from, date_to, branch_id, source))


@router.get("/stock-value", response_model=StockValue)
async def stock_value(
    ctx: CanView,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
) -> StockValue:
    report = await svc.reports.stock_value(ctx.db, await _scope(ctx, svc, date_from, date_to, branch_id))
    return report if _sees_cost(ctx) else hide_stock_cost(report)


@router.get("/operators", response_model=OperatorPerformance)
async def operators(
    ctx: CanView, svc: Reporting, date_from: DateFrom = None, date_to: DateTo = None
) -> OperatorPerformance:
    return await svc.reports.operators(ctx.db, await _scope(ctx, svc, date_from, date_to))


@router.get("/ai-usage", response_model=AiUsage)
async def ai_usage(
    ctx: CanView, svc: Reporting, date_from: DateFrom = None, date_to: DateTo = None
) -> AiUsage:
    report = await svc.reports.ai_usage(ctx.db, await _scope(ctx, svc, date_from, date_to))
    return report if _sees_cost(ctx) else hide_ai_cost(report)


@router.get("/warranty", response_model=WarrantyStats)
async def warranty(
    ctx: CanView,
    svc: Reporting,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
) -> WarrantyStats:
    return await svc.reports.warranty(ctx.db, await _scope(ctx, svc, date_from, date_to, branch_id))


@router.get("/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
async def export_csv(
    ctx: CanView,
    svc: Reporting,
    report: ExportReport,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    branch_id: BranchId = None,
    source: Source = None,
) -> Response:
    """Hisobotni CSV qilib yuklab olish (shaxsiy ma'lumotsiz)."""
    if report == "profit" and not _sees_cost(ctx):
        raise ForbiddenError("Permission denied", permission=perm.REPORTING_MARGIN_READ)
    scope = await _scope(ctx, svc, date_from, date_to, branch_id, source)
    reports, db = svc.reports, ctx.db
    with_cost = _sees_cost(ctx)
    table: export.Table
    if report == "sales_daily":
        table = export.sales_daily(await reports.sales_daily(db, scope))
    elif report == "top_products":
        table = export.top_products(await reports.top_products(db, scope, 100))
    elif report == "by_category":
        table = export.by_category(await reports.by_category(db, scope))
    elif report == "profit":
        table = export.profit(await reports.profit(db, scope))
    elif report == "stock_value":
        table = export.stock_value(await reports.stock_value(db, scope), with_cost=with_cost)
    elif report == "operators":
        table = export.operators(await reports.operators(db, scope))
    elif report == "ai_usage":
        table = export.ai_usage(await reports.ai_usage(db, scope), with_cost=with_cost)
    else:
        table = export.warranty(await reports.warranty(db, scope))
    body = export.to_csv(*table)
    filename = f"{report}_{scope.first.isoformat()}_{scope.last.isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
