"""Xodimning platforma botiga ulanishi (db/notifications.md §5).

    Panel: "Telegram'ga ulash" → bir martalik kod (10 daqiqa) → xodim botga `/start <kod>`
      → kod xeshi topildi, ishlatilmagan → staff_telegram_links → kod "ishlatildi"

Kodning o'zi bazada saqlanmaydi — faqat SHA-256 xeshi. Bitta Telegram akkaunt — bitta odam.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.notifications.models.orm import StaffTelegramLink, TelegramLinkCode
from app.platform.notifications.schemas import TelegramLinkCodeOut, TelegramLinkStatus
from app.shared.clock import utcnow
from app.shared.types.actor import ActorContext

CODE_TTL = timedelta(minutes=10)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # chalkashadigan 0/O, 1/I yo'q
CODE_LENGTH = 10


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


@dataclass(frozen=True)
class BotConfig:
    username: str | None
    configured: bool


class TelegramLinkService:
    def __init__(self, bot: BotConfig) -> None:
        self.bot = bot

    async def status(self, db: AsyncSession, actor: ActorContext) -> TelegramLinkStatus:
        link = await db.get(StaffTelegramLink, actor.actor_id)
        active = link is not None and link.unlinked_at is None
        return TelegramLinkStatus(
            linked=active,
            linked_at=link.linked_at if active and link else None,
            bot_username=self.bot.username,
            bot_configured=self.bot.configured,
        )

    async def create_code(self, db: AsyncSession, actor: ActorContext) -> TelegramLinkCodeOut:
        assert actor.actor_id is not None
        code = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
        expires_at = utcnow() + CODE_TTL
        db.add(
            TelegramLinkCode(principal_id=actor.actor_id, code_hash=hash_code(code), expires_at=expires_at)
        )
        await db.flush()
        deep_link = f"https://t.me/{self.bot.username}?start={code}" if self.bot.username else None
        return TelegramLinkCodeOut(
            code=code, expires_at=expires_at, bot_username=self.bot.username, deep_link=deep_link
        )

    async def unlink(self, db: AsyncSession, actor: ActorContext) -> None:
        await db.execute(
            update(StaffTelegramLink)
            .where(StaffTelegramLink.principal_id == actor.actor_id, StaffTelegramLink.unlinked_at.is_(None))
            .values(unlinked_at=utcnow())
        )

    async def redeem(self, db: AsyncSession, code: str, telegram_user_id: int, chat_id: int) -> UUID | None:
        """Bot `/start <kod>` oldi. Muvaffaqiyatda — ulangan odam ID'si; noto'g'ri/eskirgan kod — None."""
        row = (
            await db.execute(
                select(TelegramLinkCode)
                .where(TelegramLinkCode.code_hash == hash_code(code))
                .with_for_update()
            )
        ).scalar_one_or_none()
        now = utcnow()
        if row is None or row.used_at is not None or row.expires_at <= now:
            return None
        row.used_at = now
        # Shu Telegram akkaunt boshqa odamga ulangan bo'lsa — o'sha ulanish uziladi
        await db.execute(
            update(StaffTelegramLink)
            .where(
                StaffTelegramLink.telegram_user_id == telegram_user_id,
                StaffTelegramLink.principal_id != row.principal_id,
                StaffTelegramLink.unlinked_at.is_(None),
            )
            .values(unlinked_at=now)
        )
        link = await db.get(StaffTelegramLink, row.principal_id, with_for_update=True)
        if link is None:
            db.add(
                StaffTelegramLink(
                    principal_id=row.principal_id, telegram_user_id=telegram_user_id, telegram_chat_id=chat_id
                )
            )
        else:
            link.telegram_user_id, link.telegram_chat_id = telegram_user_id, chat_id
            link.linked_at, link.unlinked_at, link.last_error_code = now, None, None
        await db.flush()
        return row.principal_id
