"""Chiquvchi xabar yozuvi (13 §4, 12 §8): avval bazaga `QUEUED` + outbox → `channel_send` vazifasi.

Kim yozsa ham (operator, xabarnoma, AI) xabar shu yerda yoziladi: tartib raqami, takror himoyasi
(`intent_key` — bir niyat bir marta), kanal holati. Sayt chati tashqi yuborishsiz — darhol `SENT`
(mehmon `?after=` bilan o'zi oladi).

Fencing (12 §8, TC-009): AI javobi faqat `speaker_mode = AI` va suhbatdagi `speaker_version` o'zgarmagan
bo'lsa navbatga tushadi; aks holda `DISCARDED` bo'lib yoziladi — xaridorga ketmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import (
    CONVERSATION,
    MESSAGE,
    SENDABLE_CHANNEL_STATUSES,
    conversation_payload,
    emit,
)
from app.domains.messaging.models.orm import (
    Attachment,
    ChannelAccount,
    Conversation,
    CustomerIdentity,
    Message,
)
from app.platform.storage.services.file_service import FileService
from app.shared.clock import utcnow
from app.shared.errors.base import ChannelUnavailableError
from app.shared.types.actor import ActorContext

CHAT_ATTACHMENT = "CHAT_ATTACHMENT"


@dataclass(frozen=True)
class Reachability:
    ok: bool
    reason: str | None  # channel_disconnected | customer_blocked | ...


async def reachability(db: AsyncSession, conversation: Conversation) -> Reachability:
    account = await db.get(ChannelAccount, conversation.channel_account_id)
    if account is None or account.status not in SENDABLE_CHANNEL_STATUSES:
        return Reachability(False, "channel_disconnected")
    identity = await db.get(CustomerIdentity, conversation.customer_identity_id)
    if identity is not None and identity.blocked_at is not None:
        return Reachability(False, "customer_blocked")
    if identity is not None and identity.erased_at is not None:
        return Reachability(False, "customer_erased")
    return Reachability(True, None)


class MessageWriter:
    def __init__(self, files: FileService) -> None:
        self.files = files

    async def by_intent(self, db: AsyncSession, shop_id: UUID, intent_key: str) -> Message | None:
        return (
            await db.execute(
                select(Message).where(Message.shop_id == shop_id, Message.intent_key == intent_key)
            )
        ).scalar_one_or_none()

    async def append_outbound(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation: Conversation,
        *,
        origin: str,
        author_type: str,
        body: str | None,
        intent_key: str,
        author_membership_id: UUID | None = None,
        attachment_file_id: UUID | None = None,
        notification_id: UUID | None = None,
        ai_reply_id: UUID | None = None,
        speaker_version: int | None = None,
        require_reachable: bool = True,
    ) -> Message:
        """Suhbat qatori chaqiruvchida qulflangan (FOR UPDATE) bo'lishi kerak — tartib raqami shu yerda.
        Shu `intent_key` bilan xabar allaqachon bo'lsa — o'sha qaytadi (ikkinchi marta yozilmaydi)."""
        existing = await self.by_intent(db, conversation.shop_id, intent_key)
        if existing is not None:
            return existing
        if require_reachable:
            reach = await reachability(db, conversation)
            if not reach.ok:
                raise ChannelUnavailableError("Channel is not available", reason=reach.reason)
        file_row = None
        if attachment_file_id is not None:
            file_row = await self.files.usable(db, conversation.shop_id, attachment_file_id, CHAT_ATTACHMENT)
        now = utcnow()
        conversation.message_seq += 1
        webchat = conversation.channel == "WEB_CHAT"
        message = Message(
            shop_id=conversation.shop_id,
            conversation_id=conversation.id,
            seq=conversation.message_seq,
            direction="OUT",
            author_type=author_type,
            author_membership_id=author_membership_id,
            origin=origin,
            kind="IMAGE" if file_row is not None else "TEXT",
            body=body,
            occurred_at=now,
            speaker_version=speaker_version,
            intent_key=intent_key,
            notification_id=notification_id,
            ai_reply_id=ai_reply_id,
            delivery_status="SENT" if webchat else "QUEUED",
            sent_at=now if webchat else None,
        )
        db.add(message)
        conversation.last_message_at = now
        conversation.last_outbound_at = now
        await db.flush()
        if file_row is not None:
            db.add(
                Attachment(
                    shop_id=conversation.shop_id,
                    message_id=message.id,
                    file_id=file_row.id,
                    kind="IMAGE",
                    status="STORED",
                    mime=file_row.mime_type,
                    size_bytes=file_row.size_bytes,
                )
            )
            await db.flush()
        await emit(
            db,
            actor,
            event_type="messaging.message.sent" if webchat else "messaging.message.queued",
            shop_id=conversation.shop_id,
            aggregate_type=MESSAGE,
            aggregate_id=message.id,
            aggregate_version=1,
            payload=conversation_payload(conversation, origin=origin, seq=message.seq),
        )
        return message

    async def append_discarded_ai(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation: Conversation,
        *,
        body: str | None,
        intent_key: str,
        speaker_version: int,
        ai_reply_id: UUID | None,
        reason: str,
    ) -> Message:
        """AI javobi kech qoldi (speaker o'zgargan): yoziladi, lekin `DISCARDED` — xaridorga ketmaydi."""
        existing = await self.by_intent(db, conversation.shop_id, intent_key)
        if existing is not None:
            return existing
        now = utcnow()
        conversation.message_seq += 1
        message = Message(
            shop_id=conversation.shop_id,
            conversation_id=conversation.id,
            seq=conversation.message_seq,
            direction="OUT",
            author_type="AI",
            origin="AI_AUTO",
            kind="TEXT",
            body=body,
            occurred_at=now,
            speaker_version=speaker_version,
            intent_key=intent_key,
            ai_reply_id=ai_reply_id,
            delivery_status="DISCARDED",
            last_error_code=reason,
        )
        db.add(message)
        await db.flush()
        await emit(
            db,
            actor,
            event_type="messaging.message.discarded",
            shop_id=conversation.shop_id,
            aggregate_type=MESSAGE,
            aggregate_id=message.id,
            aggregate_version=1,
            payload=conversation_payload(conversation, reason_code=reason),
        )
        return message

    async def conversation_changed(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation, event: str, **extra: object
    ) -> None:
        await emit(
            db,
            actor,
            event_type=f"messaging.conversation.{event}",
            shop_id=conversation.shop_id,
            aggregate_type=CONVERSATION,
            aggregate_id=conversation.id,
            aggregate_version=conversation.version,
            payload=conversation_payload(conversation, **extra),
        )
