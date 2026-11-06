"""messaging Query Port implementatsiyalari (`app/shared/contracts/messaging.py`)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import SENDABLE_CHANNEL_STATUSES, ensure_scope, not_found
from app.domains.messaging.models.orm import Attachment, ChannelAccount, Conversation, Message
from app.domains.messaging.services.ai_replies import AiReplyService, ai_actor
from app.domains.messaging.services.core import ConversationCore
from app.domains.messaging.services.outbound import MessageWriter
from app.shared.contracts.messaging import AiConversationContext, ContextMessage, QueueOutcome
from app.shared.errors.base import InvalidTransitionError
from app.shared.types.actor import ActorContext


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

    async def conversation_exists(self, db: AsyncSession, shop_id: UUID, conversation_id: UUID) -> bool:
        found = await db.scalar(
            select(Conversation.id).where(Conversation.shop_id == shop_id, Conversation.id == conversation_id)
        )
        return found is not None


# sales_ai handoff kodi → messaging.handoffs.reason (HANDOFF_REASONS)
_HANDOFF_REASON = {
    "CUSTOMER_REQUEST": "CUSTOMER_REQUEST",
    "PURCHASE_INTENT": "PURCHASE_INTENT",
    "COMPLAINT": "COMPLAINT",
    "DISCOUNT_REQUEST": "DISCOUNT",
    "PAYMENT_QUESTION": "PAYMENT",
    "WARRANTY_OR_RETURN": "WARRANTY",
    "VALIDATION_FAILED": "VALIDATION_FAILED",
    "PRICE_UNKNOWN": "AI_LOW_CONFIDENCE",
    "COMPATIBILITY_REVIEW": "AI_LOW_CONFIDENCE",
    "UNSUPPORTED_REQUEST": "AI_LOW_CONFIDENCE",
    "SECURITY": "AI_LOW_CONFIDENCE",
    "TOOL_ERROR": "AI_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE": "AI_UNAVAILABLE",
    "BUDGET_EXCEEDED": "AI_UNAVAILABLE",
    "REFUSAL": "AI_UNAVAILABLE",
}


class AiConversationPortImpl:
    """AiConversationPort (6b): sales_ai suhbat kontekstini o'qiydi va javobni fencing bilan topshiradi."""

    def __init__(self, core: ConversationCore, writer: MessageWriter, ai: AiReplyService) -> None:
        self.core = core
        self.writer = writer
        self.ai = ai

    async def context(
        self, db: AsyncSession, shop_id: UUID, conversation_id: UUID, *, limit: int = 20
    ) -> AiConversationContext | None:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None or conversation.shop_id != shop_id:
            return None
        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(
                        Message.shop_id == shop_id,
                        Message.conversation_id == conversation_id,
                        Message.delivery_status != "DISCARDED",
                    )
                    .order_by(Message.seq.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        latest_in = await db.scalar(
            select(func.max(Message.seq)).where(
                Message.shop_id == shop_id,
                Message.conversation_id == conversation_id,
                Message.direction == "IN",
            )
        )
        voice_ids = [m.id for m in rows if m.kind == "VOICE" and m.direction == "IN"]
        pending = (
            set(
                (
                    await db.execute(
                        select(Attachment.message_id).where(
                            Attachment.shop_id == shop_id,
                            Attachment.message_id.in_(voice_ids),
                            Attachment.status == "PENDING",
                        )
                    )
                ).scalars()
            )
            if voice_ids
            else set()
        )
        return AiConversationContext(
            conversation_id=conversation.id,
            channel=conversation.channel,
            status=conversation.status,
            speaker_mode=conversation.speaker_mode,
            speaker_version=conversation.speaker_version,
            locale=conversation.locale,
            customer_identity_id=conversation.customer_identity_id,
            latest_inbound_seq=int(latest_in or 0),
            messages=tuple(
                ContextMessage(
                    m.seq, m.direction, m.author_type, m.kind, m.body, m.delivery_status, m.id in pending
                )
                for m in reversed(rows)
            ),
        )

    async def message_seq(self, db: AsyncSession, shop_id: UUID, message_id: UUID) -> tuple[int, str] | None:
        row = (
            await db.execute(
                select(Message.seq, Message.kind).where(Message.shop_id == shop_id, Message.id == message_id)
            )
        ).one_or_none()
        return (int(row.seq), str(row.kind)) if row is not None else None

    async def queue_ai_reply(
        self,
        db: AsyncSession,
        shop_id: UUID,
        conversation_id: UUID,
        *,
        speaker_version: int,
        body: str,
        ai_reply_id: UUID,
        handoff_reason: str | None = None,
    ) -> QueueOutcome:
        message = await self.ai.queue(
            db,
            shop_id,
            conversation_id,
            speaker_version=speaker_version,
            body=body,
            ai_reply_id=ai_reply_id,
            handoff_reason=_HANDOFF_REASON.get(handoff_reason, "OTHER") if handoff_reason else None,
        )
        return "DISCARDED" if message.delivery_status == "DISCARDED" else "QUEUED"

    async def request_handoff(
        self,
        db: AsyncSession,
        shop_id: UUID,
        conversation_id: UUID,
        *,
        reason: str,
        speaker_version: int | None,
    ) -> bool:
        conversation = await self.core.lock(db, shop_id, conversation_id)
        if conversation is None:
            return False
        if speaker_version is not None and conversation.speaker_version != speaker_version:
            return False  # operator allaqachon olgan (fencing)
        if conversation.status not in ("AI_ACTIVE", "REOPENED"):
            return False
        await self.core.request_human(
            db,
            ai_actor(shop_id),
            conversation,
            reason=_HANDOFF_REASON.get(reason, "OTHER"),
            requested_by_type="AI",
        )
        return True

    async def ai_signal(
        self, db: AsyncSession, shop_id: UUID, conversation_id: UUID, event: str, **extra: Any
    ) -> None:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None or conversation.shop_id != shop_id:
            return
        await self.writer.conversation_changed(db, ai_actor(shop_id), conversation, event, **extra)

    async def ensure_visible(self, db: AsyncSession, actor: ActorContext, conversation_id: UUID) -> int:
        assert actor.shop_id is not None
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None or conversation.shop_id != actor.shop_id:
            raise not_found()
        ensure_scope(actor, conversation)
        return conversation.speaker_version

    async def send_suggestion(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        *,
        body: str,
        ai_reply_id: UUID,
        speaker_version: int,
    ) -> UUID:
        assert actor.shop_id is not None
        conversation = await self.core.lock(db, actor.shop_id, conversation_id)
        if conversation is None:
            raise not_found()
        ensure_scope(actor, conversation)
        if conversation.status != "AI_ACTIVE" or conversation.speaker_version != speaker_version:
            raise InvalidTransitionError(
                "AI suggestion is stale",
                entity="messaging.conversation",
                **{"from": conversation.status},
                command="SEND_AI_SUGGESTION",
                reason="speaker_changed",
            )
        message = await self.writer.append_outbound(
            db,
            actor,
            conversation,
            origin="AI_APPROVED",
            author_type="STAFF",
            author_membership_id=actor.membership_id,
            body=body,
            intent_key=f"ai_suggestion:{ai_reply_id}",
            ai_reply_id=ai_reply_id,
            speaker_version=speaker_version,
        )
        await self.core.transition(
            db, ai_actor(actor.shop_id), conversation, "AWAIT_CUSTOMER", "WAITING_CUSTOMER"
        )
        return message.id
