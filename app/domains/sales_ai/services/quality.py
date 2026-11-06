""" "AI sifati" — production ko'rsatkichlari (6c, M06 §9, 16 §5): shop bo'yicha, kunma-kun.

Manbalar (hammasi shop RLS konteksti bilan):
- `ai_turns` — navbatlar (javob, taklif, soya, operatorga uzatish va sababi, validator kodlari, qayta yozish,
  xato, latency). Hisobga kirmaydi: `NO_REPLY` (debounce) va hali tugamagan navbatlar;
- `ai_feedback` — SUGGEST: tahrirsiz yuborildi / tahrirlandi / rad etildi / belgilandi, tahrir foizi, xato
  belgilari;
- `platform.ai_usage` — jonli xarajat (`SALES_TURN` + `CLASSIFY`; sinov oynasi va baholash kirmaydi).
Kun — shop vaqt zonasida (`shops.timezone`). Matn yo'q — faqat sonlar va kodlar.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.eval.schemas import FeedbackStats, QualityDay, QualityOut, QualityTotals
from app.domains.sales_ai.models.orm import AiFeedback, AiTurn
from app.domains.sales_ai.services.panel import AiPanelService
from app.platform.llm.models.orm import AiUsage
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.errors.base import NotFoundError

LIVE_PURPOSES = ("SALES_TURN", "CLASSIFY")
MAX_DAYS = 90


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _feedback(counts: Counter[str], edit_sum: int, edit_n: int) -> FeedbackStats:
    reviewed = counts["SENT_AS_IS"] + counts["EDITED"] + counts["REJECTED"]
    return FeedbackStats(
        sent_as_is=counts["SENT_AS_IS"],
        edited=counts["EDITED"],
        rejected=counts["REJECTED"],
        flagged=counts["FLAGGED"],
        total=sum(counts.values()),
        approval_rate=_rate(counts["SENT_AS_IS"], reviewed),
        avg_edit_pct=round(edit_sum / edit_n, 1) if edit_n else None,
    )


class AiQualityService:
    def __init__(self, panel: AiPanelService) -> None:
        self.panel = panel

    async def quality(self, db: AsyncSession, shop_id: UUID, days: int = 30) -> QualityOut:
        shop = await db.get(Shop, shop_id)
        if shop is None:
            raise NotFoundError("Shop not found")
        tz_name = shop.timezone
        tz = ZoneInfo(tz_name)
        today = utcnow().astimezone(tz).date()
        date_from = today - timedelta(days=days - 1)
        since = datetime.combine(date_from, time(0), tzinfo=tz)

        def day(column: Any) -> Any:
            return cast(func.timezone(tz_name, column), Date)

        turn_day = day(AiTurn.created_at).label("day")
        counted = AiTurn.outcome.is_not(None) & (AiTurn.outcome != "NO_REPLY")
        turn_rows = (
            await db.execute(
                select(
                    turn_day,
                    func.count(),
                    func.count(func.distinct(AiTurn.conversation_id)),
                    func.count(case((AiTurn.outcome == "REPLY_QUEUED", 1))),
                    func.count(case((AiTurn.outcome == "SUGGESTED", 1))),
                    func.count(case((AiTurn.outcome == "SHADOWED", 1))),
                    func.count(case((AiTurn.handoff_reason.is_not(None), 1))),
                    func.count(case((func.cardinality(AiTurn.validator_codes) > 0, 1))),
                    func.count(case((AiTurn.outcome == "ERROR", 1))),
                    func.coalesce(func.sum(AiTurn.rewrite_count), 0),
                )
                .where(AiTurn.shop_id == shop_id, AiTurn.created_at >= since, counted)
                .group_by(turn_day)
            )
        ).all()
        by_day: dict[date, list[int]] = {row[0]: [int(v or 0) for v in row[1:]] for row in turn_rows}

        totals_row = (
            await db.execute(
                select(
                    func.count(func.distinct(AiTurn.conversation_id)),
                    func.avg(AiTurn.latency_ms),
                ).where(AiTurn.shop_id == shop_id, AiTurn.created_at >= since, counted)
            )
        ).one()
        reasons = Counter(
            {
                str(reason): int(n)
                for reason, n in (
                    await db.execute(
                        select(AiTurn.handoff_reason, func.count())
                        .where(
                            AiTurn.shop_id == shop_id,
                            AiTurn.created_at >= since,
                            counted,
                            AiTurn.handoff_reason.is_not(None),
                        )
                        .group_by(AiTurn.handoff_reason)
                    )
                ).all()
            }
        )
        codes: Counter[str] = Counter()
        for (row_codes,) in (
            await db.execute(
                select(AiTurn.validator_codes).where(
                    AiTurn.shop_id == shop_id,
                    AiTurn.created_at >= since,
                    counted,
                    func.cardinality(AiTurn.validator_codes) > 0,
                )
            )
        ).all():
            codes.update(row_codes or [])

        fb_day = day(AiFeedback.created_at).label("day")
        feedback_rows = (
            await db.execute(
                select(fb_day, AiFeedback.verdict, AiFeedback.edit_distance_pct, AiFeedback.error_tags).where(
                    AiFeedback.shop_id == shop_id, AiFeedback.created_at >= since
                )
            )
        ).all()
        fb_by_day: dict[date, tuple[Counter[str], list[int]]] = {}
        all_verdicts: Counter[str] = Counter()
        edits: list[int] = []
        tags: Counter[str] = Counter()
        for row_day, verdict, edit_pct, error_tags in feedback_rows:
            verdicts, day_edits = fb_by_day.setdefault(row_day, (Counter(), []))
            verdicts[str(verdict)] += 1
            all_verdicts[str(verdict)] += 1
            if verdict == "EDITED" and edit_pct is not None:
                day_edits.append(int(edit_pct))
                edits.append(int(edit_pct))
            tags.update(error_tags or [])

        usage_day = day(AiUsage.occurred_at).label("day")
        cost_by_day = {
            row_day: int(cost or 0)
            for row_day, cost in (
                await db.execute(
                    select(usage_day, func.sum(AiUsage.cost_micros))
                    .where(
                        AiUsage.shop_id == shop_id,
                        AiUsage.occurred_at >= since,
                        AiUsage.purpose.in_(LIVE_PURPOSES),
                    )
                    .group_by(usage_day)
                )
            ).all()
        }

        daily: list[QualityDay] = []
        for offset in range(days):
            current = date_from + timedelta(days=offset)
            t = by_day.get(current, [0] * 9)
            verdicts, day_edits = fb_by_day.get(current, (Counter(), []))
            daily.append(
                QualityDay(
                    date=current,
                    turns=t[0],
                    conversations=t[1],
                    replies=t[2],
                    suggestions=t[3],
                    handoffs=t[5],
                    validator_hits=t[6],
                    errors=t[7],
                    cost_micros=cost_by_day.get(current, 0),
                    feedback=_feedback(verdicts, sum(day_edits), len(day_edits)),
                )
            )
        sums = [sum(v[i] for v in by_day.values()) for i in range(9)]
        conversations = int(totals_row[0] or 0)
        cost = sum(cost_by_day.values())
        settings = await self.panel.ensure_settings(db, shop_id)
        return QualityOut(
            shop_id=shop_id,
            timezone=tz_name,
            date_from=date_from,
            date_to=today,
            days=days,
            totals=QualityTotals(
                conversations=conversations,
                turns=sums[0],
                replies=sums[2],
                suggestions=sums[3],
                shadowed=sums[4],
                handoffs=sums[5],
                handoff_rate=_rate(sums[5], sums[0]),
                validator_hits=sums[6],
                validator_hit_rate=_rate(sums[6], sums[0]),
                rewrites=sums[8],
                errors=sums[7],
                cost_micros=cost,
                cost_per_conversation_micros=round(cost / conversations) if conversations else None,
                avg_latency_ms=round(float(totals_row[1])) if totals_row[1] is not None else None,
                feedback=_feedback(all_verdicts, sum(edits), len(edits)),
            ),
            daily=daily,
            handoff_reasons=dict(sorted(reasons.items())),
            validator_codes=dict(sorted(codes.items())),
            error_tags=dict(sorted(tags.items())),
            auto_readiness=await self.panel.readiness(db, settings),
        )
