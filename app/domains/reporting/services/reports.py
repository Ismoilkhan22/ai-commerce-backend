"""Hisobot so'rovlari (19 §4, §7): faqat `reporting` schemasidan, boshqa schemaga JOIN yo'q.

Hamma raqam kunlik (`*_day`, shop vaqti) ustunlari bo'yicha filtrlanadi, shuning uchun "kecha" Toshkent
kuni bo'ladi. Filial doirasi ikki qatlamda: so'ralgan filial + xodimning o'z doirasi (`actor.branch_ids`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, distinct, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reporting.common import data_as_of, day_of, days_between, shop_zone
from app.domains.reporting.models.orm import (
    AiUsageDaily,
    ConversationFact,
    HandoffFact,
    MessageFact,
    OrderFact,
    OrderLineFact,
    ProductDim,
    QuickSaleFact,
    StockValueDaily,
    SupportCaseFact,
)
from app.domains.reporting.projections import (
    P_CASES,
    P_HANDOFFS,
    P_MESSAGES,
    P_ORDERS,
    P_QUICK_SALES,
    P_STOCK,
)
from app.domains.reporting.schemas import (
    AiUsage,
    AiUsageRow,
    BranchRow,
    CategoryRow,
    CountRow,
    OperatorPerformance,
    OperatorRow,
    Period,
    ProductRow,
    Profit,
    QualityFlag,
    SalesByCategory,
    SalesDaily,
    SalesDay,
    SalesSummary,
    SourceRow,
    StockValue,
    StockValueBranch,
    StockValueDay,
    TopProducts,
    WarrantySku,
    WarrantyStats,
)
from app.platform.staff.models.orm import Principal
from app.shared.errors.base import ForbiddenError, ValidationError
from app.shared.types.actor import ActorContext

MAX_DAYS = 366
OFFLINE = "OFFLINE"  # tez sotuv manbasi (DEC-123)


def _field(name: str, code: str) -> dict[str, Any]:
    return {"field": name, "code": code, "params": {}}


@dataclass(frozen=True)
class Scope:
    shop_id: UUID
    first: date
    last: date
    zone: ZoneInfo
    branches: list[UUID] | None  # None — hamma filial
    source: str | None = None

    @property
    def period(self) -> Period:
        return Period(date_from=self.first, date_to=self.last, timezone=self.zone.key)

    def branch_clause(self, column: Any) -> list[ColumnElement[bool]]:
        return [] if self.branches is None else [column.in_(self.branches)]


def hide_stock_cost(report: StockValue) -> StockValue:
    """Tannarxni ko'rish huquqi yo'q (menejer, DEC-146): tannarx qiymatlari None, qolgani saqlanadi."""
    return report.model_copy(
        update={
            "value_at_cost_minor": None,
            "branches": [b.model_copy(update={"value_at_cost_minor": None}) for b in report.branches],
            "series": [d.model_copy(update={"value_at_cost_minor": None}) for d in report.series],
        }
    )


def hide_ai_cost(report: AiUsage) -> AiUsage:
    """AI xarajati (pul) — faqat ega; chaqiruv va token sonlari saqlanadi."""
    return report.model_copy(
        update={
            "cost_micros": None,
            "by_day": [r.model_copy(update={"cost_micros": None}) for r in report.by_day],
            "by_purpose": [r.model_copy(update={"cost_micros": None}) for r in report.by_purpose],
        }
    )


def _percent(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _seconds(value: Any) -> int | None:
    return None if value is None else round(float(value))


class ReportService:
    # ------------------------------------------------------------------ doira
    async def scope(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        date_from: date | None,
        date_to: date | None,
        branch_id: UUID | None = None,
        source: str | None = None,
    ) -> Scope:
        assert actor.shop_id is not None
        zone = await shop_zone(db, actor.shop_id)
        today = day_of(datetime.now(zone), zone)
        last = date_to or today
        first = date_from or (last - timedelta(days=29))
        if first > last:
            raise ValidationError("Period is reversed", fields=[_field("from", "invalid_range")])
        if (last - first).days + 1 > MAX_DAYS:
            raise ValidationError("Period is too long", fields=[_field("from", "max_range")])
        branches: list[UUID] | None = None if actor.branch_ids is None else sorted(actor.branch_ids)
        if branch_id is not None:
            if actor.branch_ids is not None and branch_id not in actor.branch_ids:
                raise ForbiddenError("Branch is outside your scope", branch_id=branch_id)
            branches = [branch_id]
        return Scope(actor.shop_id, first, last, zone, branches, source)

    async def _as_of(self, db: AsyncSession, scope: Scope, *projections: str) -> datetime | None:
        return await data_as_of(db, scope.shop_id, projections)

    # ------------------------------------------------------------------ sotuv
    def _orders(self, scope: Scope) -> list[ColumnElement[bool]]:
        return [
            OrderFact.shop_id == scope.shop_id,
            OrderFact.status == "COMPLETED",
            OrderFact.completed_day.between(scope.first, scope.last),
            *scope.branch_clause(OrderFact.branch_id),
            *([OrderFact.source == scope.source] if scope.source else []),
        ]

    def _quick(self, scope: Scope) -> list[ColumnElement[bool]]:
        return [
            QuickSaleFact.shop_id == scope.shop_id,
            QuickSaleFact.recorded_day.between(scope.first, scope.last),
            *scope.branch_clause(QuickSaleFact.branch_id),
        ]

    def _with_quick(self, scope: Scope) -> bool:
        return scope.source in (None, OFFLINE)

    def _with_orders(self, scope: Scope) -> bool:
        return scope.source != OFFLINE

    async def sales_summary(self, db: AsyncSession, scope: Scope) -> SalesSummary:
        by_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        if self._with_orders(scope):
            for source, count, amount in await db.execute(
                select(OrderFact.source, func.count(), func.coalesce(func.sum(OrderFact.total_minor), 0))
                .where(*self._orders(scope))
                .group_by(OrderFact.source)
            ):
                by_source[source] = [int(count), int(amount)]
        by_branch: dict[UUID | None, list[int]] = defaultdict(lambda: [0, 0])
        if self._with_orders(scope):
            for branch, count, amount in await db.execute(
                select(OrderFact.branch_id, func.count(), func.coalesce(func.sum(OrderFact.total_minor), 0))
                .where(*self._orders(scope))
                .group_by(OrderFact.branch_id)
            ):
                by_branch[branch] = [int(count), int(amount)]
        orders_count = sum(v[0] for v in by_source.values())
        orders_amount = sum(v[1] for v in by_source.values())
        quick_count = quick_amount = 0
        if self._with_quick(scope):
            row = (
                await db.execute(
                    select(
                        func.count(distinct(QuickSaleFact.sale_id)),
                        func.coalesce(func.sum(QuickSaleFact.line_total_minor), 0),
                    ).where(*self._quick(scope))
                )
            ).one()
            quick_count, quick_amount = int(row[0]), int(row[1])
            if quick_count:
                by_source[OFFLINE] = [quick_count, quick_amount]
            for branch, count, amount in await db.execute(
                select(
                    QuickSaleFact.branch_id,
                    func.count(distinct(QuickSaleFact.sale_id)),
                    func.coalesce(func.sum(QuickSaleFact.line_total_minor), 0),
                )
                .where(*self._quick(scope))
                .group_by(QuickSaleFact.branch_id)
            ):
                by_branch[branch][0] += int(count)
                by_branch[branch][1] += int(amount)
        units = 0
        if self._with_orders(scope):
            units += int(
                await db.scalar(
                    select(func.coalesce(func.sum(OrderLineFact.qty), 0)).where(
                        OrderLineFact.shop_id == scope.shop_id,
                        OrderLineFact.completed_day.between(scope.first, scope.last),
                        *scope.branch_clause(OrderLineFact.branch_id),
                        *([OrderLineFact.source == scope.source] if scope.source else []),
                    )
                )
                or 0
            )
        if self._with_quick(scope):
            units += int(
                await db.scalar(
                    select(func.coalesce(func.sum(QuickSaleFact.qty), 0)).where(*self._quick(scope))
                )
                or 0
            )
        cancelled = 0
        if self._with_orders(scope):
            cancelled = int(
                await db.scalar(
                    select(func.count()).where(
                        OrderFact.shop_id == scope.shop_id,
                        OrderFact.status == "CANCELLED",
                        OrderFact.cancelled_day.between(scope.first, scope.last),
                        *scope.branch_clause(OrderFact.branch_id),
                        *([OrderFact.source == scope.source] if scope.source else []),
                    )
                )
                or 0
            )
        total_count, total_amount = orders_count + quick_count, orders_amount + quick_amount
        return SalesSummary(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_ORDERS, P_QUICK_SALES),
            orders_count=orders_count,
            orders_amount_minor=orders_amount,
            quick_sales_count=quick_count,
            quick_sales_amount_minor=quick_amount,
            total_count=total_count,
            total_amount_minor=total_amount,
            units_sold=units,
            average_ticket_minor=total_amount // total_count if total_count else None,
            cancelled_orders_count=cancelled,
            by_branch=[
                BranchRow(branch_id=branch, count=v[0], amount_minor=v[1])
                for branch, v in sorted(by_branch.items(), key=lambda kv: (-kv[1][1], str(kv[0])))
            ],
            by_source=[
                SourceRow(source=source, count=v[0], amount_minor=v[1])
                for source, v in sorted(by_source.items())
            ],
        )

    async def sales_daily(self, db: AsyncSession, scope: Scope) -> SalesDaily:
        days = {
            d: [0, 0, 0, 0] for d in days_between(scope.first, scope.last)
        }  # o.soni, o.summa, t.soni, t.summa
        if self._with_orders(scope):
            for day, count, amount in await db.execute(
                select(
                    OrderFact.completed_day, func.count(), func.coalesce(func.sum(OrderFact.total_minor), 0)
                )
                .where(*self._orders(scope))
                .group_by(OrderFact.completed_day)
            ):
                if day in days:
                    days[day][0], days[day][1] = int(count), int(amount)
        if self._with_quick(scope):
            for day, count, amount in await db.execute(
                select(
                    QuickSaleFact.recorded_day,
                    func.count(distinct(QuickSaleFact.sale_id)),
                    func.coalesce(func.sum(QuickSaleFact.line_total_minor), 0),
                )
                .where(*self._quick(scope))
                .group_by(QuickSaleFact.recorded_day)
            ):
                days[day][2], days[day][3] = int(count), int(amount)
        return SalesDaily(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_ORDERS, P_QUICK_SALES),
            days=[
                SalesDay(
                    day=day,
                    orders_count=v[0],
                    orders_amount_minor=v[1],
                    quick_sales_count=v[2],
                    quick_sales_amount_minor=v[3],
                    total_amount_minor=v[1] + v[3],
                )
                for day, v in days.items()
            ],
        )

    def _lines(self, scope: Scope) -> Select[Any]:
        """Buyurtma va tez sotuv qatorlari bitta shaklda: sku, toifa, soni, summa, tannarx."""
        parts: list[Any] = []
        if self._with_orders(scope):
            parts.append(
                select(
                    OrderLineFact.sku_id.label("sku_id"),
                    OrderLineFact.category_code.label("category_code"),
                    OrderLineFact.qty.label("qty"),
                    OrderLineFact.line_total_minor.label("amount"),
                    OrderLineFact.cost_total_minor.label("cost"),
                ).where(
                    OrderLineFact.shop_id == scope.shop_id,
                    OrderLineFact.completed_day.between(scope.first, scope.last),
                    *scope.branch_clause(OrderLineFact.branch_id),
                    *([OrderLineFact.source == scope.source] if scope.source else []),
                )
            )
        if self._with_quick(scope):
            parts.append(
                select(
                    QuickSaleFact.sku_id.label("sku_id"),
                    QuickSaleFact.category_code.label("category_code"),
                    QuickSaleFact.qty.label("qty"),
                    QuickSaleFact.line_total_minor.label("amount"),
                    QuickSaleFact.cost_total_minor.label("cost"),
                ).where(*self._quick(scope))
            )
        if not parts:
            parts.append(
                select(
                    literal(None).label("sku_id"),
                    literal(None).label("category_code"),
                    literal(0).label("qty"),
                    literal(0).label("amount"),
                    literal(None).label("cost"),
                ).where(literal(False))
            )
        return parts[0] if len(parts) == 1 else union_all(*parts)  # type: ignore[return-value]

    async def top_products(self, db: AsyncSession, scope: Scope, limit: int) -> TopProducts:
        lines = self._lines(scope).subquery()
        rows = (
            await db.execute(
                select(
                    lines.c.sku_id,
                    func.max(lines.c.category_code),
                    func.sum(lines.c.qty),
                    func.sum(lines.c.amount),
                )
                .group_by(lines.c.sku_id)
                .order_by(func.sum(lines.c.amount).desc(), lines.c.sku_id)
                .limit(limit)
            )
        ).all()
        titles = await self._titles(db, scope.shop_id, [r[0] for r in rows])
        return TopProducts(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_ORDERS, P_QUICK_SALES),
            items=[
                ProductRow(
                    sku_id=sku_id,
                    title=titles.get(sku_id),
                    category_code=category,
                    qty=int(qty),
                    amount_minor=int(amount),
                )
                for sku_id, category, qty, amount in rows
            ],
        )

    async def by_category(self, db: AsyncSession, scope: Scope) -> SalesByCategory:
        lines = self._lines(scope).subquery()
        rows = (
            await db.execute(
                select(lines.c.category_code, func.sum(lines.c.qty), func.sum(lines.c.amount))
                .group_by(lines.c.category_code)
                .order_by(func.sum(lines.c.amount).desc())
            )
        ).all()
        names = dict(
            (
                await db.execute(
                    select(ProductDim.category_code, func.max(ProductDim.category_name))
                    .where(ProductDim.shop_id == scope.shop_id, ProductDim.category_code.is_not(None))
                    .group_by(ProductDim.category_code)
                )
            ).all()
        )
        return SalesByCategory(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_ORDERS, P_QUICK_SALES),
            items=[
                CategoryRow(
                    category_code=code, category_name=names.get(code), qty=int(qty), amount_minor=int(amount)
                )
                for code, qty, amount in rows
            ],
        )

    async def _titles(self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]) -> dict[UUID, str]:
        if not sku_ids:
            return {}
        rows = await db.execute(
            select(ProductDim.sku_id, ProductDim.title).where(
                ProductDim.shop_id == shop_id, ProductDim.sku_id.in_(list(sku_ids))
            )
        )
        return {sku_id: title for sku_id, title in rows}

    # ------------------------------------------------------------------ foyda (DEC-146)
    async def profit(self, db: AsyncSession, scope: Scope) -> Profit:
        lines = self._lines(scope).subquery()
        has_cost = lines.c.cost.is_not(None)
        row = (
            await db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(lines.c.amount), 0),
                    func.count().filter(has_cost),
                    func.coalesce(func.sum(lines.c.amount).filter(has_cost), 0),
                    func.coalesce(func.sum(lines.c.cost), 0),
                )
            )
        ).one()
        total_lines, revenue, costed_lines, covered, cost = (int(v) for v in row)
        flags: list[QualityFlag] = []
        if total_lines and costed_lines == 0:
            flags.append("NO_COST_DATA")
        elif costed_lines < total_lines:
            flags.append("PARTIAL_COST_DATA")
        # Tannarx umuman yo'q: foyda raqami aytilmaydi (0 emas, null)
        gross = covered - cost if costed_lines else None
        refunds = await db.scalar(
            select(func.coalesce(func.sum(SupportCaseFact.refund_amount_minor), 0)).where(
                SupportCaseFact.shop_id == scope.shop_id,
                SupportCaseFact.outcome == "RETURNED",
                SupportCaseFact.resolved_day.between(scope.first, scope.last),
                *scope.branch_clause(SupportCaseFact.branch_id),
            )
        )
        return Profit(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_ORDERS, P_QUICK_SALES),
            revenue_minor=revenue,
            covered_revenue_minor=covered,
            cost_minor=cost if costed_lines else None,
            gross_profit_minor=gross,
            gross_margin_percent=_percent(gross, covered) if gross is not None else None,
            cost_coverage_percent=_percent(covered, revenue),
            lines_count=total_lines,
            lines_without_cost=total_lines - costed_lines,
            quality_flags=flags,
            refunds_amount_minor=int(refunds or 0),
        )

    # ------------------------------------------------------------------ ombor qiymati
    async def stock_value(self, db: AsyncSession, scope: Scope) -> StockValue:
        base = [StockValueDaily.shop_id == scope.shop_id, *scope.branch_clause(StockValueDaily.branch_id)]
        latest = await db.scalar(select(func.max(StockValueDaily.day)).where(*base))
        branches: list[StockValueBranch] = []
        computed_at: datetime | None = None
        if latest is not None:
            result = await db.execute(select(StockValueDaily).where(*base, StockValueDaily.day == latest))
            for r in result.scalars():
                computed_at = max(filter(None, (computed_at, r.computed_at)))
                branches.append(
                    StockValueBranch(
                        branch_id=r.branch_id,
                        units=r.units,
                        quarantine_units=r.quarantine_units,
                        value_at_price_minor=r.value_at_price_minor,
                        value_at_cost_minor=r.value_at_cost_minor,
                        units_without_cost=r.units_without_cost,
                        units_without_price=r.units_without_price,
                    )
                )
        costed = [b.value_at_cost_minor for b in branches if b.value_at_cost_minor is not None]
        units_without_cost = sum(b.units_without_cost for b in branches)
        units_without_price = sum(b.units_without_price for b in branches)
        flags: list[QualityFlag] = []
        if branches and not costed:
            flags.append("NO_COST_DATA")
        elif units_without_cost:
            flags.append("PARTIAL_COST_DATA")
        if units_without_price:
            flags.append("PARTIAL_PRICE_DATA")
        series_rows = await db.execute(
            select(
                StockValueDaily.day,
                func.sum(StockValueDaily.units),
                func.sum(StockValueDaily.value_at_price_minor),
                func.sum(StockValueDaily.value_at_cost_minor),
                func.sum(StockValueDaily.units_without_cost),
            )
            .where(*base, StockValueDaily.day.between(scope.first, scope.last))
            .group_by(StockValueDaily.day)
            .order_by(StockValueDaily.day)
        )
        return StockValue(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_STOCK),
            as_of_day=latest,
            computed_at=computed_at,
            units=sum(b.units for b in branches),
            quarantine_units=sum(b.quarantine_units for b in branches),
            value_at_price_minor=sum(b.value_at_price_minor for b in branches),
            value_at_cost_minor=sum(costed) if costed else None,
            units_without_cost=units_without_cost,
            units_without_price=units_without_price,
            quality_flags=flags,
            branches=sorted(branches, key=lambda b: str(b.branch_id)),
            series=[
                StockValueDay(
                    day=day,
                    units=int(units),
                    value_at_price_minor=int(price),
                    value_at_cost_minor=int(cost) if cost is not None else None,
                    units_without_cost=int(no_cost),
                )
                for day, units, price, cost, no_cost in series_rows
            ],
        )

    # ------------------------------------------------------------------ operatorlar
    async def operators(self, db: AsyncSession, scope: Scope) -> OperatorPerformance:
        """Suhbat statistikasi butun shop bo'yicha: xabarlarda filial yo'q."""
        m = [MessageFact.shop_id == scope.shop_id, MessageFact.day.between(scope.first, scope.last)]
        replied = and_(MessageFact.author.in_(("AI", "STAFF")), MessageFact.response_seconds.is_not(None))
        totals = (
            await db.execute(
                select(
                    func.count().filter(MessageFact.direction == "IN"),
                    func.count().filter(MessageFact.author == "AI"),
                    func.count().filter(MessageFact.author == "STAFF"),
                    func.percentile_cont(0.5).within_group(MessageFact.response_seconds).filter(replied),
                    func.percentile_cont(0.9).within_group(MessageFact.response_seconds).filter(replied),
                ).where(*m)
            )
        ).one()
        inbound, ai, staff = int(totals[0]), int(totals[1]), int(totals[2])
        per_staff = (
            await db.execute(
                select(
                    MessageFact.staff_id,
                    func.count(),
                    func.percentile_cont(0.5).within_group(MessageFact.response_seconds),
                    func.percentile_cont(0.9).within_group(MessageFact.response_seconds),
                )
                .where(*m, MessageFact.author == "STAFF", MessageFact.staff_id.is_not(None))
                .group_by(MessageFact.staff_id)
                .order_by(func.count().desc(), MessageFact.staff_id)
            )
        ).all()
        h = [HandoffFact.shop_id == scope.shop_id, HandoffFact.opened_day.between(scope.first, scope.last)]
        handoffs_opened = int(await db.scalar(select(func.count()).where(*h)) or 0)
        wait = func.extract("epoch", HandoffFact.taken_at - HandoffFact.opened_at)
        handoff_row = (
            await db.execute(
                select(func.count(), func.percentile_cont(0.5).within_group(wait)).where(
                    *h, HandoffFact.status == "TAKEN", HandoffFact.taken_at.is_not(None)
                )
            )
        ).one()
        taken_by = dict(
            (
                await db.execute(
                    select(HandoffFact.taken_by_staff_id, func.count())
                    .where(*h, HandoffFact.taken_by_staff_id.is_not(None))
                    .group_by(HandoffFact.taken_by_staff_id)
                )
            ).all()
        )
        conversations = int(
            await db.scalar(
                select(func.count()).where(
                    ConversationFact.shop_id == scope.shop_id,
                    ConversationFact.started_day.between(scope.first, scope.last),
                )
            )
            or 0
        )
        staff_ids: set[UUID] = {r[0] for r in per_staff} | {s for s in taken_by if s is not None}
        names: dict[UUID, str] = {}
        if staff_ids:
            names = dict(
                (
                    await db.execute(
                        select(Principal.id, Principal.full_name).where(Principal.id.in_(staff_ids))
                    )
                ).all()
            )
        by_id = {r[0]: r for r in per_staff}
        operators = [
            OperatorRow(
                staff_id=staff_id,
                name=names.get(staff_id),
                replies_count=int(by_id[staff_id][1]) if staff_id in by_id else 0,
                response_p50_seconds=_seconds(by_id[staff_id][2]) if staff_id in by_id else None,
                response_p90_seconds=_seconds(by_id[staff_id][3]) if staff_id in by_id else None,
                handoffs_taken=int(taken_by.get(staff_id, 0)),
            )
            for staff_id in sorted(
                staff_ids, key=lambda s: (-(int(by_id[s][1]) if s in by_id else 0), str(s))
            )
        ]
        return OperatorPerformance(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_MESSAGES, P_HANDOFFS),
            inbound_messages=inbound,
            ai_replies=ai,
            staff_replies=staff,
            ai_reply_share_percent=_percent(ai, ai + staff),
            conversations_started=conversations,
            handoffs_opened=handoffs_opened,
            handoffs_taken=int(handoff_row[0]),
            handoff_wait_p50_seconds=_seconds(handoff_row[1]),
            response_p50_seconds=_seconds(totals[3]),
            response_p90_seconds=_seconds(totals[4]),
            operators=operators,
        )

    # ------------------------------------------------------------------ AI xarajati
    async def ai_usage(self, db: AsyncSession, scope: Scope) -> AiUsage:
        where = [AiUsageDaily.shop_id == scope.shop_id, AiUsageDaily.day.between(scope.first, scope.last)]

        async def grouped(column: Any) -> list[AiUsageRow]:
            rows = await db.execute(
                select(
                    column,
                    func.sum(AiUsageDaily.calls),
                    func.sum(AiUsageDaily.tokens_in),
                    func.sum(AiUsageDaily.tokens_out),
                    func.sum(AiUsageDaily.cost_micros),
                )
                .where(*where)
                .group_by(column)
                .order_by(column)
            )
            return [
                AiUsageRow(
                    key=str(key), calls=int(c), tokens_in=int(i), tokens_out=int(o), cost_micros=int(cost)
                )
                for key, c, i, o, cost in rows
            ]

        by_day = await grouped(AiUsageDaily.day)
        by_purpose = await grouped(AiUsageDaily.purpose)
        return AiUsage(
            period=scope.period,
            # AI xarajati event'siz, soatlik ish bilan yig'iladi: eng yangi hisoblangan vaqt
            data_as_of=await db.scalar(
                select(func.max(AiUsageDaily.computed_at)).where(AiUsageDaily.shop_id == scope.shop_id)
            ),
            calls=sum(r.calls for r in by_day),
            tokens_in=sum(r.tokens_in for r in by_day),
            tokens_out=sum(r.tokens_out for r in by_day),
            cost_micros=sum(r.cost_micros for r in by_day),
            by_day=by_day,
            by_purpose=by_purpose,
        )

    # ------------------------------------------------------------------ kafolat
    async def warranty(self, db: AsyncSession, scope: Scope) -> WarrantyStats:
        c = SupportCaseFact
        where = [
            c.shop_id == scope.shop_id,
            c.opened_day.between(scope.first, scope.last),
            *scope.branch_clause(c.branch_id),
        ]
        head = (
            await db.execute(
                select(
                    func.count(),
                    func.count().filter(c.resolved_at.is_not(None)),
                    func.count().filter(c.within_warranty.is_(True)),
                    func.coalesce(func.sum(c.refund_amount_minor).filter(c.outcome == "RETURNED"), 0),
                    func.avg(func.extract("epoch", c.resolved_at - c.opened_at)).filter(
                        c.resolved_at.is_not(None)
                    ),
                ).where(*where)
            )
        ).one()

        async def counts(column: Any) -> list[CountRow]:
            rows = await db.execute(
                select(column, func.count())
                .where(*where, column.is_not(None))
                .group_by(column)
                .order_by(column)
            )
            return [CountRow(key=str(key), count=int(n)) for key, n in rows]

        top = (
            await db.execute(
                select(c.sku_id, func.count())
                .where(*where, c.sku_id.is_not(None))
                .group_by(c.sku_id)
                .order_by(func.count().desc(), c.sku_id)
                .limit(5)
            )
        ).all()
        titles = await self._titles(db, scope.shop_id, [r[0] for r in top if r[0] is not None])
        return WarrantyStats(
            period=scope.period,
            data_as_of=await self._as_of(db, scope, P_CASES),
            opened_count=int(head[0]),
            resolved_count=int(head[1]),
            within_warranty_count=int(head[2]),
            refund_amount_minor=int(head[3]),
            average_resolution_days=round(float(head[4]) / 86400, 1) if head[4] is not None else None,
            by_status=await counts(c.status),
            by_type=await counts(c.type),
            by_resolution=await counts(c.resolution),
            reject_reasons=await counts(c.reject_reason),
            top_skus=[
                WarrantySku(sku_id=sku_id, title=titles.get(sku_id), count=int(n))
                for sku_id, n in top
                if sku_id is not None
            ],
        )
