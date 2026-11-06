"""sales_ai umumiy: AI aktori, tool ro'yxati, ish vaqti, standart sozlamalar, event yozish."""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

SCHEMA = "sales_ai"
TURN = "sales_ai.turn"
PROMPT_VERSION = "seller-2026-10-v1"

# API nomi (snake_case, Claude tool nomida nuqta yo'q) → ichki nom (K-10 "domain.verb") — M06 §4.1
TOOLS: dict[str, str] = {
    "catalog_search": "catalog.search",
    "catalog_get_sku_details": "catalog.get_sku_details",
    "commerce_get_stock": "commerce.get_stock",
    "catalog_check_compatibility": "catalog.check_compatibility",
    "commerce_capture_lead": "commerce.capture_lead",
    "commerce_prepare_quote_draft": "commerce.prepare_quote_draft",
    "commerce_create_order_draft": "commerce.create_order_draft",
    "messaging_request_handoff": "messaging.request_handoff",
}
WRITE_TOOLS = frozenset(
    {"commerce_capture_lead", "commerce_prepare_quote_draft", "commerce_create_order_draft"}
)
DEFAULT_TOOLS = sorted(TOOLS)

DEFAULT_HANDOFF_RULES: dict[str, Any] = {
    "always_handoff_on": ["COMPLAINT", "WARRANTY_OR_RETURN", "DISCOUNT_REQUEST"],
    "max_ai_turns_before_offer_human": 12,
}

MAX_TOOL_CALLS = 6  # navbatga (14 §3.1)
TURN_BUDGET_S = 20.0
MAX_REPLY_TOKENS = 4096  # Claude'da thinking ham shunga kiradi (M06 §4.1)
CONTEXT_MESSAGES = 20


def ai_actor(shop_id: UUID) -> ActorContext:
    return ActorContext(actor_type="AI_AGENT", actor_id=None, shop_id=shop_id, surface="worker")


def _clock(value: Any) -> time | None:
    if not isinstance(value, str) or not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", value):
        return None
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def within_hours(hours: dict[str, Any] | None, timezone: str, now: datetime) -> bool:
    """`{"days": [1..7], "start": "09:00", "end": "21:00"}` (inbox_hours formati). Bo'sh — doim."""
    if not hours:
        return True
    start, end = _clock(hours.get("start")), _clock(hours.get("end"))
    days = hours.get("days") or [1, 2, 3, 4, 5, 6, 7]
    if start is None or end is None or start == end:
        return True
    local = now.astimezone(ZoneInfo(timezone))
    current = local.time()
    if start < end:
        return local.isoweekday() in days and start <= current < end
    # tungi oyna (22:00–06:00): boshlanish kunining oynasi
    if current >= start:
        return local.isoweekday() in days
    yesterday = (local.isoweekday() - 2) % 7 + 1
    return yesterday in days and current < end


async def emit(
    db: AsyncSession,
    shop_id: UUID,
    event_type: str,
    *,
    turn_id: UUID,
    version: int = 1,
    **payload: Any,
) -> None:
    """sales_ai event'i (outbox) — faqat ID va kodlar, matn YO'Q (05 §3)."""
    await db.flush()
    await write_outbox(
        db,
        schema=SCHEMA,
        event_type=event_type,
        actor=ai_actor(shop_id),
        shop_id=shop_id,
        aggregate_type=TURN,
        aggregate_id=turn_id,
        aggregate_version=version,
        payload={"turn_id": turn_id, **payload},
    )
