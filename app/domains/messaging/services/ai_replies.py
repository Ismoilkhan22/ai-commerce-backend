"""AI javobini navbatga qo'yish — fencing bilan (12 §8, TC-009). 6-modul (sales_ai) shu kirish nuqtasidan
foydalanadi (`sales_ai.reply.ready` tinglovchisi); hozir AI o'chiq, testlar soxta "AI" bilan tekshiradi.

AI javobi qaysi `speaker_version` uchun tayyorlangan bo'lsa, shu bilan keladi. Navbatga faqat suhbat hamon
AI'niki (`speaker_mode = AI`, holat `AI_ACTIVE`) va versiya o'zgarmagan bo'lsa tushadi; aks holda xabar
`DISCARDED` bo'lib yoziladi — xaridorga ketmaydi. Yuborish paytida (`channel_send`) versiya yana tekshiriladi.

AI oxirgi xabari bilan birga operatorga uzatsa (`handoff_reason`: "operator tez orada javob beradi", buyurtma
qoralamasi tayyor) — xabar va `REQUEST_HUMAN` bitta tranzaksiyada; xabar pauzadan keyingi versiya bilan
yoziladi, shuning uchun u yuboriladi, operator olsa (versiya yana +1) — yo'q.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import not_found
from app.domains.messaging.models.orm import Message
from app.domains.messaging.services.core import ConversationCore
from app.domains.messaging.services.outbound import MessageWriter
from app.shared.types.actor import ActorContext


def ai_actor(shop_id: UUID) -> ActorContext:
    return ActorContext(actor_type="AI_AGENT", actor_id=None, shop_id=shop_id, surface="worker")


class AiReplyService:
    def __init__(self, core: ConversationCore, writer: MessageWriter) -> None:
        self.core = core
        self.writer = writer

    async def queue(
        self,
        db: AsyncSession,
        shop_id: UUID,
        conversation_id: UUID,
        *,
        speaker_version: int,
        body: str,
        ai_reply_id: UUID,
        handoff_reason: str | None = None,
    ) -> Message:
        conversation = await self.core.lock(db, shop_id, conversation_id)
        if conversation is None:
            raise not_found()
        actor = ai_actor(shop_id)
        intent = f"ai:{ai_reply_id}"
        if (
            conversation.speaker_mode != "AI"
            or conversation.status != "AI_ACTIVE"
            or conversation.speaker_version != speaker_version
        ):
            return await self.writer.append_discarded_ai(
                db,
                actor,
                conversation,
                body=body,
                intent_key=intent,
                speaker_version=speaker_version,
                ai_reply_id=ai_reply_id,
                reason="SPEAKER_CHANGED",
            )
        message = await self.writer.append_outbound(
            db,
            actor,
            conversation,
            origin="AI_AUTO",
            author_type="AI",
            body=body,
            intent_key=intent,
            ai_reply_id=ai_reply_id,
            speaker_version=speaker_version + 1 if handoff_reason else speaker_version,
        )
        if handoff_reason:
            await self.core.request_human(
                db, actor, conversation, reason=handoff_reason, requested_by_type="AI"
            )  # pauza: versiya +1 = xabar versiyasi
            return message
        await self.core.transition(db, actor, conversation, "AWAIT_CUSTOMER", "WAITING_CUSTOMER")
        return message
