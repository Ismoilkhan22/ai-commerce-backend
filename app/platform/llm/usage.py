"""AI xarajati: har LLM chaqiruvi `platform.ai_usage` ga (M06 §8, A7). Kunlik va oylik yig'indi —
limitlar uchun.

Narx USD × 10⁶ (micros). Kunlar va oylar UTC bo'yicha: chegara — taxminiy himoya, aniq hisob emas.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.llm.models.orm import AiUsage
from app.platform.llm.port import LlmResponse
from app.platform.llm.pricing import CONSERVATIVE_PRICE, ModelPrice, cost_micros


async def record_usage_entry(
    db: AsyncSession,
    *,
    shop_id: UUID | None,
    response: LlmResponse,
    price: ModelPrice | None,
    purpose: str,
    ref_id: UUID | None,
) -> AiUsage:
    # noma'lum model hech qachon 0 emas — eng qimmat ma'lum narx (limit ishlashi uchun, F-16)
    cost = cost_micros(response.usage, price or CONSERVATIVE_PRICE)
    entry = AiUsage(
        price_unknown=price is None,
        shop_id=shop_id,
        provider=response.provider,
        model_id=response.model_id,
        purpose=purpose,
        ref_id=ref_id,
        tokens_in=response.usage.input_tokens,
        tokens_out=response.usage.output_tokens + response.usage.thinking_tokens,
        cache_read_tokens=response.usage.cache_read_tokens,
        cache_write_tokens=response.usage.cache_write_tokens,
        cost_micros=cost,
    )
    db.add(entry)
    await db.flush()
    return entry


async def record_usage(
    db: AsyncSession,
    *,
    shop_id: UUID | None,
    response: LlmResponse,
    price: ModelPrice | None,
    purpose: str,
    ref_id: UUID | None,
) -> int:
    entry = await record_usage_entry(
        db, shop_id=shop_id, response=response, price=price, purpose=purpose, ref_id=ref_id
    )
    return int(entry.cost_micros)


LIVE_EXCLUDE = ("SANDBOX",)  # sinov oynasi jonli AI limitini yemaydi (F-13)


async def spent_since(
    db: AsyncSession,
    shop_id: UUID,
    since: datetime,
    *,
    only: tuple[str, ...] | None = None,
    exclude: tuple[str, ...] = LIVE_EXCLUDE,
) -> tuple[int, int, int]:
    """(cost_micros, tokens, calls) — shu vaqtdan beri. Standart: jonli xarajat (sinov oynasisiz)."""
    query = select(
        func.coalesce(func.sum(AiUsage.cost_micros), 0),
        func.coalesce(func.sum(AiUsage.tokens_in + AiUsage.tokens_out), 0),
        func.count(),
    ).where(AiUsage.shop_id == shop_id, AiUsage.occurred_at >= since)
    if only is not None:
        query = query.where(AiUsage.purpose.in_(only))
    elif exclude:
        query = query.where(AiUsage.purpose.not_in(exclude))
    row = (await db.execute(query)).one()
    return int(row[0]), int(row[1]), int(row[2])


def day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now: datetime) -> datetime:
    return day_start(now).replace(day=1)
