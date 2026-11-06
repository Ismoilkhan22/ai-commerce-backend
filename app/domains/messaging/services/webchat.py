"""Sayt chati (S2-01, 13 §8): anonim mehmon, login yo'q.

Sessiya tokeni — tasodifiy, bazada faqat SHA-256 xeshi; sayt ilovasi uni o'z domenidagi httpOnly cookie'da
saqlab, API'ga `X-Chat-Session` sarlavhasi bilan uzatadi (4-qaror). Token shop konteksti ichida qidiriladi:
boshqa shop slug'i bilan — topilmaydi (404, TC-CH-06). 30 kun, har faollikda suriladi.

Javoblar — qisqa so'rov (polling) `?after_seq=` bilan: anonim mehmon uchun WS/SSE kerak emas, sayt serveri
orqali uzatish sodda va ishonchli (5b qarori).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.base import InboundMessage
from app.domains.messaging.common import sha256
from app.domains.messaging.models.orm import (
    Attachment,
    ChannelAccount,
    Conversation,
    CustomerIdentity,
    Message,
    ProviderEvent,
    WebchatSession,
)
from app.domains.messaging.schemas import (
    ChatMessageOut,
    ChatMessagesOut,
    ChatSendOut,
    ChatSessionOut,
    ChatState,
)
from app.domains.messaging.services.inbound import InboundService
from app.shared.clock import utcnow
from app.shared.consent import STOREFRONT_CONSENT_VERSION
from app.shared.contracts.storefront import SiteAccess
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import ChannelUnavailableError, NotFoundError
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

SESSION_TTL = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=1)  # muddat har so'rovda emas, daqiqada bir suriladi (har 4 s yozuv yo'q)
POLL_INTERVAL_SECONDS = 4
LOCALES = frozenset({"uz", "ru", "en"})
_NO_IMAGE: tuple[str | None, datetime | None] = (None, None)
PAGE = 100
_AUTHORS = {"CUSTOMER": "customer", "STAFF": "operator", "AI": "operator", "SYSTEM": "system"}


def chat_state(conversation: Conversation | None) -> ChatState:
    if conversation is None:
        return "WAITING_OPERATOR"
    if conversation.status == "RESOLVED":
        return "CLOSED"
    if conversation.speaker_mode == "HUMAN" and conversation.status in ("HUMAN_ACTIVE", "WAITING_CUSTOMER"):
        return "OPERATOR"
    return "WAITING_OPERATOR"


class WebchatService:
    def __init__(self, inbound: InboundService) -> None:
        self.inbound = inbound

    async def _account(self, db: AsyncSession, access: SiteAccess) -> ChannelAccount:
        account = (
            await db.execute(
                select(ChannelAccount).where(
                    ChannelAccount.shop_id == access.shop_id,
                    ChannelAccount.channel == "WEB_CHAT",
                    ChannelAccount.status.in_(("CONNECTED", "DEGRADED")),
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise ChannelUnavailableError("Web chat is not enabled", reason="webchat_disabled")
        return account

    async def create_session(self, db: AsyncSession, access: SiteAccess) -> ChatSessionOut:
        account = await self._account(db, access)
        identity = CustomerIdentity(
            shop_id=access.shop_id,
            channel="WEB_CHAT",
            external_user_id=f"v_{secrets.token_urlsafe(16)}",  # tasodifiy mehmon ID'si
        )
        db.add(identity)
        await db.flush()
        token = secrets.token_urlsafe(32)
        now = utcnow()
        db.add(
            WebchatSession(
                shop_id=access.shop_id,
                channel_account_id=account.id,
                customer_identity_id=identity.id,
                token_hash=sha256(token),
                expires_at=now + SESSION_TTL,
            )
        )
        await db.flush()
        return ChatSessionOut(
            token=token, expires_at=now + SESSION_TTL, poll_interval_seconds=POLL_INTERVAL_SECONDS
        )

    async def _session(
        self, db: AsyncSession, access: SiteAccess, token: str | None, *, lock: bool = True
    ) -> WebchatSession:
        if not token or len(token) > 100:
            raise NotFoundError("Chat session not found")
        query = select(WebchatSession).where(
            WebchatSession.shop_id == access.shop_id, WebchatSession.token_hash == sha256(token)
        )
        session = (await db.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
        now = utcnow()
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise NotFoundError("Chat session not found")  # mehmon yangi sessiya oladi
        if session.last_seen_at is None or session.last_seen_at < now - TOUCH_EVERY:
            session.last_seen_at, session.expires_at = now, now + SESSION_TTL
        return session

    async def _conversation(self, db: AsyncSession, session: WebchatSession) -> Conversation | None:
        return (
            await db.execute(
                select(Conversation).where(
                    Conversation.shop_id == session.shop_id,
                    Conversation.customer_identity_id == session.customer_identity_id,
                )
            )
        ).scalar_one_or_none()

    async def messages(
        self, db: AsyncSession, access: SiteAccess, token: str | None, after_seq: int
    ) -> ChatMessagesOut:
        session = await self._session(db, access, token, lock=False)  # polling: qulf yo'q (QA 5b kuzatuv)
        conversation = await self._conversation(db, session)
        items: list[ChatMessageOut] = []
        if conversation is not None:
            rows = await db.execute(
                select(Message)
                .where(
                    Message.shop_id == conversation.shop_id,
                    Message.conversation_id == conversation.id,
                    Message.seq > after_seq,
                    Message.delivery_status.not_in(("DISCARDED", "FAILED")),
                )
                .order_by(Message.seq)
                .limit(PAGE)
            )
            messages = list(rows.scalars())
            images = await self._image_urls(db, conversation.shop_id, messages)
            items = [
                ChatMessageOut(
                    seq=m.seq,
                    direction=m.direction,
                    author=_AUTHORS.get(m.author_type, "system"),
                    kind=m.kind,
                    body=m.body,
                    image_url=images.get(m.id, _NO_IMAGE)[0],
                    image_url_expires_at=images.get(m.id, _NO_IMAGE)[1],
                    occurred_at=m.occurred_at,
                )
                for m in messages
            ]
        return ChatMessagesOut(
            items=items,
            state=chat_state(conversation),
            last_seq=items[-1].seq if items else after_seq,
            poll_interval_seconds=POLL_INTERVAL_SECONDS,
        )

    async def _image_urls(
        self, db: AsyncSession, shop_id: UUID, messages: list[Message]
    ) -> dict[UUID, tuple[str | None, datetime | None]]:
        """Rasmli xabarlar uchun qisqa muddatli imzoli havola (QA 5b M2): mehmon operator yuborgan rasmni
        ko'radi. Fayl yopiq (`CHAT_ATTACHMENT`) — havola 5 daqiqa, keyingi so'rovda yangisi."""
        image_ids = [m.id for m in messages if m.kind == "IMAGE"]
        if not image_ids:
            return {}
        attachments = (
            (
                await db.execute(
                    select(Attachment).where(
                        Attachment.shop_id == shop_id,
                        Attachment.message_id.in_(image_ids),
                        Attachment.status == "STORED",
                    )
                )
            )
            .scalars()
            .all()
        )
        files = self.inbound.core.writer.files
        stored = await files.by_ids(db, shop_id, [a.file_id for a in attachments if a.file_id])
        out: dict[UUID, tuple[str | None, datetime | None]] = {}
        for a in attachments:
            row = stored.get(a.file_id) if a.file_id else None
            if row is not None and a.message_id not in out:
                out[a.message_id] = files.url_for(row)
        return out

    async def send(
        self,
        db: AsyncSession,
        access: SiteAccess,
        token: str | None,
        client_message_id: str,
        body: str,
        locale: str | None = None,
    ) -> ChatSendOut:
        session = await self._session(db, access, token)
        account = await self._account(db, access)
        identity = await db.get(CustomerIdentity, session.customer_identity_id)
        assert identity is not None
        result = await self.inbound.ingest(
            db,
            account,
            InboundMessage(
                provider_event_id=f"{session.id}:{client_message_id}",
                event_kind="MESSAGE",
                external_user_id=identity.external_user_id,
                occurred_at=utcnow(),
                kind="TEXT",
                body=body,
                language_code=locale if locale in LOCALES else None,  # sayt tili (QA 5b M1)
            ),
        )
        if result.duplicate:
            seq = await db.scalar(
                select(Message.seq)
                .join(
                    ProviderEvent,
                    (ProviderEvent.shop_id == Message.shop_id) & (ProviderEvent.message_id == Message.id),
                )
                .where(
                    ProviderEvent.shop_id == access.shop_id,
                    ProviderEvent.channel_account_id == account.id,
                    ProviderEvent.provider_event_id == f"{session.id}:{client_message_id}",
                )
            )
            return ChatSendOut(seq=int(seq or 0), duplicate=True)
        return ChatSendOut(seq=result.seq or 0, duplicate=False)

    async def contact(
        self, db: AsyncSession, access: SiteAccess, token: str | None, name: str | None, phone: str | None
    ) -> None:
        session = await self._session(db, access, token)
        identity = (
            await db.execute(
                select(CustomerIdentity)
                .where(CustomerIdentity.id == session.customer_identity_id)
                .with_for_update()
            )
        ).scalar_one()
        if name:
            identity.display_name = name
        if phone:
            normalized = normalize_phone(phone, "phone")
            identity.phone_enc, identity.phone_hmac = normalized, search_hmac(normalized)
        identity.contact_consent_at = utcnow()  # BL-036: mehmon o'zi rozilik berdi
        identity.notice_version = STOREFRONT_CONSENT_VERSION  # qaysi matnga rozi bo'lgani (26 §8, QA 5b L5)
        identity.erased_at = None
        await db.flush()
        conversation = await self._conversation(db, session)
        if conversation is not None:  # operator ekranida ism/telefon darhol (QA 5b frontend b)
            await self.inbound.core.writer.conversation_changed(
                db, ActorContext.system(access.shop_id), conversation, "contact_updated"
            )
