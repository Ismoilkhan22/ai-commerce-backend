"""AI shu shopda hozir ishlaydimi (`AiGatePort`) va xarajat chegarasi (M06 §8, BL-040).

Tartib: rejim OFF → shop faol emas (SUSPENDED/CLOSED) → kill switch → provayder sozlanmagan →
limit tugagan (`paused_until`) → ish vaqtidan tashqari. Limit tugaganda `mode` o'zgarmaydi —
`paused_until` keyingi kun/oy boshigacha qo'yiladi, egaga xabarnoma ketadi;
yangi suhbatlar operatorga. 80% da — ogohlantirish (kuniga bir marta).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.common import ai_actor, within_hours
from app.domains.sales_ai.models.orm import AgentSettings
from app.platform.llm.port import ProviderStatus
from app.platform.llm.usage import day_start, month_start, spent_since
from app.platform.notifications.services.notifications import NotificationService
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.contracts.sales_ai import AiGate, AiMode

MICROS_PER_CENT = 10_000  # cap — USD sent, ai_usage — USD × 10⁶
WARN_RATIO = 0.8
SHOP_AI_BLOCKED = frozenset({"SUSPENDED", "CLOSED"})
Period = Literal["DAILY", "MONTHLY"]


def next_period(period: Period, now: datetime) -> datetime:
    if period == "DAILY":
        return day_start(now) + timedelta(days=1)
    start = month_start(now)
    return (start + timedelta(days=32)).replace(day=1)


class AiGateService:
    def __init__(
        self, status: ProviderStatus, *, allow_fake: bool, notifications: NotificationService
    ) -> None:
        self.status = status
        self.allow_fake = allow_fake
        self.notifications = notifications

    @property
    def provider_ready(self) -> bool:
        """Haqiqiy kalit bor; `fake` — faqat dev/test (prod'da ishga tushmaydi, settings)."""
        return self.status.configured or (self.status.provider == "fake" and self.allow_fake)

    async def gate(self, db: AsyncSession, shop_id: UUID) -> AiGate:
        settings = await db.get(AgentSettings, shop_id)
        return await self.gate_for(db, shop_id, settings)

    async def gate_for(self, db: AsyncSession, shop_id: UUID, settings: AgentSettings | None) -> AiGate:
        if settings is None or settings.mode == "OFF":
            return AiGate("OFF", False, "OFF")
        mode = cast(AiMode, settings.mode)
        shop = await db.get(Shop, shop_id)
        if (
            shop is not None and shop.status in SHOP_AI_BLOCKED
        ):  # UAT-M01: to'xtatilgan/yopilgan shopda AI jim
            return AiGate(mode, False, "SHOP_NOT_ACTIVE")
        if settings.kill_switch_at is not None:
            return AiGate(mode, False, "KILL_SWITCH")
        if not self.provider_ready:
            return AiGate(mode, False, "NOT_CONFIGURED")
        now = utcnow()
        if settings.paused_until is not None and settings.paused_until > now:
            return AiGate(mode, False, "BUDGET_EXCEEDED")
        if settings.active_hours:
            if not within_hours(settings.active_hours, shop.timezone if shop else "Asia/Tashkent", now):
                return AiGate(mode, False, "OUTSIDE_HOURS")
        return AiGate(mode, True)

    async def allowance(self, db: AsyncSession, shop_id: UUID) -> str | None:
        """`AiBudgetPort`: izoh kayfiyati uchun AI ruxsati. Limit tugagan yoki sotuvchi limit tufayli
        to'xtatilgan bo'lsa — `BUDGET_EXCEEDED` (limit umumiy, DEC-119); sotuvchi rejimiga qaramaydi."""
        if not self.provider_ready:
            return "NOT_CONFIGURED"
        settings = await db.get(AgentSettings, shop_id)
        if (
            settings is not None
            and settings.paused_until is not None
            and settings.paused_until > utcnow()
            and (settings.paused_reason or "").startswith("BUDGET_EXCEEDED")
        ):
            return "BUDGET_EXCEEDED"
        if await self.budget_exceeded(db, shop_id, settings) is not None:
            return "BUDGET_EXCEEDED"
        return None

    async def budget_exceeded(
        self, db: AsyncSession, shop_id: UUID, settings: AgentSettings | None
    ) -> Period | None:
        if settings is None:
            return None
        now = utcnow()
        for period, cap, since in (
            ("DAILY", settings.daily_cost_cap_minor, day_start(now)),
            ("MONTHLY", settings.monthly_cost_cap_minor, month_start(now)),
        ):
            if cap is None:
                continue
            spent, _, _ = await spent_since(db, shop_id, since)
            limit = cap * MICROS_PER_CENT
            if spent >= limit:
                return period  # type: ignore[return-value]
            if spent >= limit * WARN_RATIO:
                await self._notify(db, shop_id, "staff.ai_budget_warning", period, now)  # type: ignore[arg-type]
        return None

    async def pause_for_budget(
        self, db: AsyncSession, shop_id: UUID, settings: AgentSettings | None, period: Period
    ) -> None:
        if settings is None:
            return
        now = utcnow()
        settings.paused_until = next_period(period, now)
        settings.paused_reason = f"BUDGET_EXCEEDED_{period}"
        await db.flush()
        await self._notify(db, shop_id, "staff.ai_budget_exceeded", period, now)

    async def _notify(
        self, db: AsyncSession, shop_id: UUID, template: str, period: Period, now: datetime
    ) -> None:
        await self.notifications.notify_staff(
            db,
            shop_id=shop_id,
            actor=ai_actor(shop_id),
            template_key=template,
            aggregate_type="sales_ai.agent_settings",
            aggregate_id=shop_id,
            aggregate_version=1,
            variables={"period": period.lower()},
            roles=("OWNER",),
            dedup_scope=f"{period}:{(day_start(now) if period == 'DAILY' else month_start(now)).date()}",
        )
