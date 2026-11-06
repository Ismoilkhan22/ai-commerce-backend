"""Hisobot javoblari (11 §9.x). Hamma summa — so'mda, tiyinda (`*_minor`). Shaxsiy ma'lumot yo'q."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

QualityFlag = Literal["NO_COST_DATA", "PARTIAL_COST_DATA", "PARTIAL_PRICE_DATA"]


class Period(BaseModel):
    date_from: date
    date_to: date
    timezone: str


class Report(BaseModel):
    period: Period
    data_as_of: datetime | None  # proyeksiyalarning eng eskisi (BL-066); hali ma'lumot yo'q — None


class SourceRow(BaseModel):
    source: str  # AI | STOREFRONT | STAFF | QUOTE | OFFLINE
    count: int
    amount_minor: int


class BranchRow(BaseModel):
    branch_id: UUID | None  # filiali yo'q buyurtmalar — None
    count: int
    amount_minor: int


class SalesSummary(Report):
    orders_count: int
    orders_amount_minor: int
    quick_sales_count: int
    quick_sales_amount_minor: int
    total_count: int
    total_amount_minor: int
    units_sold: int
    average_ticket_minor: int | None
    cancelled_orders_count: int
    by_source: list[SourceRow]
    by_branch: list[BranchRow]


class SalesDay(BaseModel):
    day: date
    orders_count: int
    orders_amount_minor: int
    quick_sales_count: int
    quick_sales_amount_minor: int
    total_amount_minor: int


class SalesDaily(Report):
    days: list[SalesDay]


class ProductRow(BaseModel):
    sku_id: UUID
    title: str | None
    category_code: str | None
    qty: int
    amount_minor: int


class TopProducts(Report):
    items: list[ProductRow]


class CategoryRow(BaseModel):
    category_code: str | None
    category_name: str | None
    qty: int
    amount_minor: int


class SalesByCategory(Report):
    items: list[CategoryRow]


class Profit(Report):
    revenue_minor: int  # barcha sotuv qatorlari
    covered_revenue_minor: int  # tannarxi ma'lum qatorlar summasi
    cost_minor: int | None  # tannarx umuman yo'q bo'lsa None (0 emas)
    gross_profit_minor: int | None  # tannarx umuman yo'q bo'lsa None: raqam aytilmaydi
    gross_margin_percent: float | None
    cost_coverage_percent: float | None  # tannarxi ma'lum sotuv ulushi (daromad bo'yicha)
    lines_count: int
    lines_without_cost: int
    quality_flags: list[QualityFlag]
    refunds_amount_minor: int  # ma'lumot uchun; foydadan ayirilmaydi


class StockValueBranch(BaseModel):
    branch_id: UUID
    units: int
    quarantine_units: int
    value_at_price_minor: int
    value_at_cost_minor: int | None  # `reporting.margin.read` bo'lmasa None
    units_without_cost: int
    units_without_price: int


class StockValueDay(BaseModel):
    day: date
    units: int
    value_at_price_minor: int
    value_at_cost_minor: int | None  # `reporting.margin.read` bo'lmasa None
    units_without_cost: int


class StockValue(Report):
    as_of_day: date | None  # joriy qiymat qaysi kunniki (oxirgi yozilgan)
    computed_at: datetime | None
    units: int
    quarantine_units: int
    value_at_price_minor: int
    value_at_cost_minor: int | None  # `reporting.margin.read` bo'lmasa None
    units_without_cost: int
    units_without_price: int
    quality_flags: list[QualityFlag]
    branches: list[StockValueBranch]
    series: list[StockValueDay]


class OperatorRow(BaseModel):
    staff_id: UUID
    name: str | None
    replies_count: int
    response_p50_seconds: int | None
    response_p90_seconds: int | None
    handoffs_taken: int


class OperatorPerformance(Report):
    inbound_messages: int
    ai_replies: int
    staff_replies: int
    ai_reply_share_percent: float | None
    conversations_started: int
    handoffs_opened: int
    handoffs_taken: int
    handoff_wait_p50_seconds: int | None
    response_p50_seconds: int | None  # AI + odam javoblari
    response_p90_seconds: int | None
    operators: list[OperatorRow]


class AiUsageRow(BaseModel):
    key: str  # sana yoki maqsad
    calls: int
    tokens_in: int
    tokens_out: int
    cost_micros: int | None  # `reporting.margin.read` bo'lmasa None


class AiUsage(Report):
    calls: int
    tokens_in: int
    tokens_out: int
    cost_micros: (
        int | None
    )  # USD × 10^6 (platform.ai_usage bilan bir xil); `reporting.margin.read` bo'lmasa None
    by_day: list[AiUsageRow]
    by_purpose: list[AiUsageRow]


class CountRow(BaseModel):
    key: str
    count: int


class WarrantySku(BaseModel):
    sku_id: UUID
    title: str | None
    count: int


class WarrantyStats(Report):
    opened_count: int
    resolved_count: int
    within_warranty_count: int
    refund_amount_minor: int
    average_resolution_days: float | None
    by_status: list[CountRow]
    by_type: list[CountRow]
    by_resolution: list[CountRow]
    reject_reasons: list[CountRow]
    top_skus: list[WarrantySku]


ExportReport = Literal[
    "sales_daily", "top_products", "by_category", "profit", "stock_value", "operators", "ai_usage", "warranty"
]
