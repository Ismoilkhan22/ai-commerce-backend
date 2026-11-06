"""messaging kontraktlari: boshqa domenlar suhbat/kanal holatini shu orqali biladi (02 §2, ADR-032)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.types.actor import ActorContext


class ChatAvailabilityPort(Protocol):
    """Sayt (4-modul) chat tugmasini ko'rsatish uchun: shopda sayt chati yoqilganmi (5b, QA 5b frontend a)."""

    async def webchat_enabled(self, db: AsyncSession, shop_id: UUID) -> bool: ...


class ConversationLookupPort(Protocol):
    """Lead va taklif yaratishda: suhbat shu shopnikimi (6a, QA 6a F11)."""

    async def conversation_exists(self, db: AsyncSession, shop_id: UUID, conversation_id: UUID) -> bool: ...


# ------------------------------------------------------------------ AI sotuvchi (6b)
@dataclass(frozen=True)
class ContextMessage:
    seq: int
    direction: str  # IN | OUT
    author_type: str  # CUSTOMER | AI | STAFF | SYSTEM
    kind: str
    body: str | None  # xom matn — sales_ai LLM'ga yuborishdan oldin redact qiladi
    delivery_status: str
    pending_media: bool = False  # ovozli xabar hali matnga o'girilmoqda (DEC-149)


@dataclass(frozen=True)
class AiConversationContext:
    conversation_id: UUID
    channel: str
    status: str
    speaker_mode: str
    speaker_version: int
    locale: str | None
    customer_identity_id: UUID
    latest_inbound_seq: int
    messages: tuple[ContextMessage, ...]  # eskisidan yangisiga


QueueOutcome = Literal["QUEUED", "DISCARDED"]


class AiConversationPort(Protocol):
    """sales_ai (6b) suhbat kontekstini shu orqali o'qiydi va javobni fencing bilan topshiradi (12 §8).
    Hamma chaqiruv shop konteksti o'rnatilgan tranzaksiyada."""

    async def context(
        self, db: AsyncSession, shop_id: UUID, conversation_id: UUID, *, limit: int = 20
    ) -> AiConversationContext | None: ...

    async def message_seq(self, db: AsyncSession, shop_id: UUID, message_id: UUID) -> tuple[int, str] | None:
        """Kiruvchi xabar (seq, kind) — navbat qaysi xabarga."""
        ...

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
        """`handoff_reason` berilsa — xabar va operatorga uzatish birga (xabar baribir xaridorga yetadi)."""
        ...

    async def request_handoff(
        self,
        db: AsyncSession,
        shop_id: UUID,
        conversation_id: UUID,
        *,
        reason: str,
        speaker_version: int | None,
    ) -> bool:
        """AI navbatidagi suhbatni operatorga (sabab — sales_ai handoff kodi). `speaker_version` berilsa va
        o'zgargan bo'lsa — hech narsa qilinmaydi (operator allaqachon olgan)."""
        ...

    async def ai_signal(
        self, db: AsyncSession, shop_id: UUID, conversation_id: UUID, event: str, **extra: Any
    ) -> None:
        """Panel uchun signal (`messaging.conversation.<event>`, faqat ID'lar)."""
        ...

    async def ensure_visible(self, db: AsyncSession, actor: ActorContext, conversation_id: UUID) -> int:
        """Xodim shu suhbatni ko'ra oladimi (operator — o'ziniki va biriktirilmagan). Yo'q bo'lsa 404, boshqa
        operatorniki bo'lsa 403. Natija — joriy `speaker_version` (AI taklifi eskirganmi)."""
        ...

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
        """SUGGEST: operator AI taklifini (tahrirlab yoki o'zgartirmay) yuboradi → xabar ID."""
        ...
