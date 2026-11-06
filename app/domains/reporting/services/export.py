"""Hisobotni CSV'ga o'girish (19 §8): shaxsiy ma'lumotsiz va CSV-injection'dan himoyalangan.

Excel/Sheets `=`, `+`, `-`, `@`, TAB yoki CR bilan boshlangan matn katakchasini formula deb ochadi. Matn
katakchalari (mahsulot nomi, toifa va h.k.) oldiga `'` qo'yiladi (OWASP). Sonlar matn emas, shuning uchun
manfiy son (`-100`) buzilmaydi. Boshida BOM: Excel UTF-8 ni to'g'ri ochadi.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domains.reporting.schemas import (
    AiUsage,
    OperatorPerformance,
    Profit,
    SalesByCategory,
    SalesDaily,
    StockValue,
    TopProducts,
    WarrantyStats,
)

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"

Table = tuple[Sequence[str], list[Sequence[Any]]]


def safe_cell(value: Any) -> str:
    """Bitta katakcha. Matn — formula belgisi bo'lsa `'` bilan; son/sana/None — o'z ko'rinishida."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    text = str(value)
    stripped = text.lstrip(" ")
    if stripped.startswith(_FORMULA_START):
        return "'" + text
    return text


def to_csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return BOM + out.getvalue()


def sales_daily(report: SalesDaily) -> Table:
    return (
        [
            "day",
            "orders_count",
            "orders_amount_minor",
            "quick_sales_count",
            "quick_sales_amount_minor",
            "total_amount_minor",
        ],
        [
            [
                d.day,
                d.orders_count,
                d.orders_amount_minor,
                d.quick_sales_count,
                d.quick_sales_amount_minor,
                d.total_amount_minor,
            ]
            for d in report.days
        ],
    )


def top_products(report: TopProducts) -> Table:
    return (
        ["sku_id", "title", "category_code", "qty", "amount_minor"],
        [[r.sku_id, r.title, r.category_code, r.qty, r.amount_minor] for r in report.items],
    )


def by_category(report: SalesByCategory) -> Table:
    return (
        ["category_code", "category_name", "qty", "amount_minor"],
        [[r.category_code, r.category_name, r.qty, r.amount_minor] for r in report.items],
    )


def profit(report: Profit) -> Table:
    return (
        [
            "revenue_minor",
            "covered_revenue_minor",
            "cost_minor",
            "gross_profit_minor",
            "gross_margin_percent",
            "cost_coverage_percent",
            "lines_count",
            "lines_without_cost",
            "quality_flags",
            "refunds_amount_minor",
        ],
        [
            [
                report.revenue_minor,
                report.covered_revenue_minor,
                report.cost_minor,
                report.gross_profit_minor,
                report.gross_margin_percent,
                report.cost_coverage_percent,
                report.lines_count,
                report.lines_without_cost,
                " ".join(report.quality_flags),
                report.refunds_amount_minor,
            ]
        ],
    )


def stock_value(report: StockValue, *, with_cost: bool = True) -> Table:
    if not with_cost:  # tannarx ustunlari ega uchun (DEC-146)
        return (
            ["day", "units", "value_at_price_minor"],
            [[d.day, d.units, d.value_at_price_minor] for d in report.series],
        )
    return (
        ["day", "units", "value_at_price_minor", "value_at_cost_minor", "units_without_cost"],
        [
            [d.day, d.units, d.value_at_price_minor, d.value_at_cost_minor, d.units_without_cost]
            for d in report.series
        ],
    )


def operators(report: OperatorPerformance) -> Table:
    return (
        [
            "staff_id",
            "name",
            "replies_count",
            "response_p50_seconds",
            "response_p90_seconds",
            "handoffs_taken",
        ],
        [
            [
                o.staff_id,
                o.name,
                o.replies_count,
                o.response_p50_seconds,
                o.response_p90_seconds,
                o.handoffs_taken,
            ]
            for o in report.operators
        ],
    )


def ai_usage(report: AiUsage, *, with_cost: bool = True) -> Table:
    if not with_cost:
        return (
            ["day", "calls", "tokens_in", "tokens_out"],
            [[r.key, r.calls, r.tokens_in, r.tokens_out] for r in report.by_day],
        )
    return (
        ["day", "calls", "tokens_in", "tokens_out", "cost_micros"],
        [[r.key, r.calls, r.tokens_in, r.tokens_out, r.cost_micros] for r in report.by_day],
    )


def warranty(report: WarrantyStats) -> Table:
    rows: list[Sequence[Any]] = [["status", r.key, r.count] for r in report.by_status]
    rows += [["type", r.key, r.count] for r in report.by_type]
    rows += [["resolution", r.key, r.count] for r in report.by_resolution]
    rows += [["reject_reason", r.key, r.count] for r in report.reject_reasons]
    rows += [["sku", f"{s.title or s.sku_id}", s.count] for s in report.top_skus]
    return ["group", "key", "count"], rows
