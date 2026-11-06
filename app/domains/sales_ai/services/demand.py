""" "So'rashdi, lekin bizda yo'q" hisoboti (DEC-149, 4-qism).

Manba — AI sotuvchining `catalog.search` chaqiruvlari (`ai_tool_executions`): natija bo'sh bo'lsa —
`NOT_FOUND` (katalogda yo'q), natija bor, lekin hammasi tugagan bo'lsa — `OUT_OF_STOCK`. So'rov matni
yozilishdan oldin PII'dan tozalangan (`args_redacted`); bir xil so'rovlar kichik harf va bo'shliq bo'yicha
birlashtiriladi. Har dushanba 09:00 da ega va menejerga raqamli xabarnoma (matnsiz, faqat soni).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.models.orm import AiToolExecution, AiTurn
from app.shared.clock import utcnow

GapKind = Literal["NOT_FOUND", "OUT_OF_STOCK"]
MAX_ROWS = 50


class DemandGap(BaseModel):
    query: str
    kind: GapKind
    times: int
    conversations: int
    last_at: datetime


class DemandGapList(BaseModel):
    days: int
    items: list[DemandGap]


async def demand_gaps(db: AsyncSession, shop_id: UUID, days: int) -> DemandGapList:
    since = utcnow() - timedelta(days=days)
    query = func.lower(
        func.btrim(func.regexp_replace(AiToolExecution.args_redacted["query"].astext, r"\s+", " ", "g"))
    )
    found = func.coalesce(func.jsonb_array_length(AiToolExecution.result_summary["sku_ids"]), 0)
    available = func.coalesce(AiToolExecution.result_summary["available"].astext.cast(Integer), -1)
    kind = case((found == 0, "NOT_FOUND"), else_="OUT_OF_STOCK")
    rows = await db.execute(
        select(
            query.label("q"),
            kind.label("kind"),
            func.count().label("times"),
            func.count(func.distinct(AiTurn.conversation_id)).label("conversations"),
            func.max(AiToolExecution.created_at).label("last_at"),
        )
        .join(AiTurn, (AiTurn.shop_id == AiToolExecution.shop_id) & (AiTurn.id == AiToolExecution.turn_id))
        .where(
            AiToolExecution.shop_id == shop_id,
            AiToolExecution.tool == "catalog.search",
            AiToolExecution.error_code.is_(None),
            AiToolExecution.created_at >= since,
            AiToolExecution.result_summary.is_not(None),
            (found == 0) | (available == 0),
            func.length(query) >= 2,
        )
        .group_by(query, kind)
        .order_by(func.count().desc(), func.max(AiToolExecution.created_at).desc())
        .limit(MAX_ROWS)
    )
    return DemandGapList(
        days=days,
        items=[
            DemandGap(
                query=r.q[:200],
                kind=r.kind,
                times=r.times,
                conversations=r.conversations,
                last_at=r.last_at,
            )
            for r in rows
        ],
    )
