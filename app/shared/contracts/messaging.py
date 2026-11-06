"""messaging kontraktlari: boshqa domenlar suhbat/kanal holatini shu orqali biladi (02 §2, ADR-032)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class ChatAvailabilityPort(Protocol):
    """Sayt (4-modul) chat tugmasini ko'rsatish uchun: shopda sayt chati yoqilganmi (5b, QA 5b frontend a)."""

    async def webchat_enabled(self, db: AsyncSession, shop_id: UUID) -> bool: ...
