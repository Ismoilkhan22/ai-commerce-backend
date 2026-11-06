"""messaging Query Port implementatsiyalari (`app/shared/contracts/messaging.py`)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import SENDABLE_CHANNEL_STATUSES
from app.domains.messaging.models.orm import ChannelAccount


class ChatAvailabilityPortImpl:
    async def webchat_enabled(self, db: AsyncSession, shop_id: UUID) -> bool:
        found = await db.scalar(
            select(ChannelAccount.id).where(
                ChannelAccount.shop_id == shop_id,
                ChannelAccount.channel == "WEB_CHAT",
                ChannelAccount.status.in_(SENDABLE_CHANNEL_STATUSES),
            )
        )
        return found is not None
