"""sales_ai → boshqa domenlar: AI shu shopda hozir ishlaydimi (6b, ai/M06-architecture.md §1).

messaging yangi xabarni yo'naltirishda shu port'ni so'raydi: `SUGGEST`/`AUTO` va AI faol bo'lsa — suhbat
`AI_ACTIVE` da qoladi; aks holda (OFF, SHADOW, kill switch, ish vaqtidan tashqari, limit) — operatorga.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

AiMode = Literal["OFF", "SHADOW", "SUGGEST", "AUTO"]


@dataclass(frozen=True)
class AiGate:
    mode: AiMode
    active: bool  # AI hozir javob bera oladi (rejim yoqiq, kill switch yo'q, ish vaqti, limit bor)
    # "OFF" | "KILL_SWITCH" | "OUTSIDE_HOURS" | "BUDGET_EXCEEDED" | "NOT_CONFIGURED" | "SHOP_NOT_ACTIVE"
    reason: str | None = None

    @property
    def speaks(self) -> bool:
        """AI xaridorga javob yozadi (AUTO) yoki taklif qiladi (SUGGEST) — suhbat AI navbatida qoladi."""
        return self.active and self.mode in ("SUGGEST", "AUTO")


class AiGatePort(Protocol):
    async def gate(self, db: AsyncSession, shop_id: UUID) -> AiGate:
        """Shop konteksti o'rnatilgan tranzaksiyada (RLS)."""
        ...


class AiBudgetPort(Protocol):
    """messaging (Instagram izohlari kayfiyati, DEC-148): AI so'rovi hozir ruxsat etilganmi — provayder
    sozlangan va shopning kunlik/oylik AI limiti (DEC-119) tugamagan. Sotuvchi rejimidan (OFF/SHADOW)
    mustaqil: izoh kayfiyati sotuvchi o'chiq bo'lsa ham ishlaydi."""

    async def allowance(self, db: AsyncSession, shop_id: UUID) -> str | None:
        """None — ruxsat; aks holda `NOT_CONFIGURED` | `BUDGET_EXCEEDED`. Shop konteksti o'rnatilgan."""
        ...
