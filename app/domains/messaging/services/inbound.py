"""Kiruvchi xabar (13 §3, BL-032): webhook avval saqlaydi, keyin o'ylaydi.

Bitta tranzaksiyada (shop konteksti o'rnatilgan): takror tekshiruvi (`provider_events`, TC-010) → xaridor
(kanal ID'si bo'yicha, shop ichida) → suhbat (bir xaridor — bitta, qulf bilan: tartib raqami shu yerda) →
xabar → FSM-04 → outbox (`messaging.message.received`). Rasm webhook ichida yuklab olinmaydi —
`PENDING` biriktirma, fon vazifasi oladi. Telefon matnga yozilmaydi: shifrlangan holda xaridor yozuviga.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.base import InboundMessage
from app.domains.messaging.common import MESSAGE, conversation_payload, customer_phone, emit
from app.domains.messaging.models.orm import (
    Attachment,
    ChannelAccount,
    Conversation,
    CustomerIdentity,
    Message,
    ProviderEvent,
)
from app.domains.messaging.services.core import ConversationCore
from app.shared.clock import utcnow
from app.shared.db.encryption import search_hmac
from app.shared.types.actor import ActorContext


@dataclass(frozen=True)
class IngestResult:
    duplicate: bool
    ignored: bool = False
    message_id: UUID | None = None
    conversation_id: UUID | None = None
    seq: int | None = None


class InboundService:
    def __init__(self, core: ConversationCore) -> None:
        self.core = core

    async def ingest(
        self, db: AsyncSession, account: ChannelAccount, inbound: InboundMessage
    ) -> IngestResult:
        shop_id = account.shop_id
        actor = ActorContext.system(shop_id)
        event_id = await db.scalar(
            insert(ProviderEvent)
            .values(
                shop_id=shop_id,
                channel_account_id=account.id,
                provider_event_id=inbound.provider_event_id[:200],
                kind=inbound.event_kind
                if inbound.event_kind in ("MESSAGE", "EDITED", "CALLBACK")
                else "OTHER",
                status="PROCESSED",
            )
            .on_conflict_do_nothing(index_elements=["shop_id", "channel_account_id", "provider_event_id"])
            .returning(ProviderEvent.id)
        )
        if event_id is None:
            return IngestResult(duplicate=True)  # Telegram qayta yubordi — hech narsa qilinmaydi
        event = await db.get(ProviderEvent, event_id)
        assert event is not None
        await db.execute(  # Core UPDATE: kanal `version` i har webhook'da oshmasin (If-Match)
            update(ChannelAccount).where(ChannelAccount.id == account.id).values(last_webhook_at=utcnow())
        )
        if inbound.ignore_reason is not None:
            event.status, event.error_code = "IGNORED", inbound.ignore_reason
            return IngestResult(duplicate=False, ignored=True)
        if inbound.event_kind == "ECHO":
            return await self._echo(db, account, inbound, event)
        identity = await self._identity(db, account, inbound)
        conversation = await self._conversation(db, account, identity)
        if inbound.event_kind == "EDITED":
            return await self._edit(db, conversation, inbound, event)
        now = utcnow()
        conversation.message_seq += 1
        message = Message(
            shop_id=shop_id,
            conversation_id=conversation.id,
            seq=conversation.message_seq,
            direction="IN",
            author_type="CUSTOMER",
            origin="CUSTOMER",
            kind=inbound.kind,
            body=inbound.body,
            intent_hint=inbound.intent_hint,
            provider_message_id=inbound.provider_message_id,
            occurred_at=inbound.occurred_at,
            delivery_status="RECEIVED",
        )
        db.add(message)
        conversation.last_message_at = now
        conversation.last_inbound_at = now
        if inbound.language_code and (conversation.locale is None or conversation.channel == "WEB_CHAT"):
            conversation.locale = inbound.language_code  # sayt chatida — mehmon tanlagan joriy til
        await db.flush()
        for item in inbound.attachments:
            db.add(
                Attachment(
                    shop_id=shop_id,
                    message_id=message.id,
                    kind=item.kind,
                    status="PENDING" if item.provider_file_ref else "FAILED",
                    provider_file_ref=item.provider_file_ref,
                    mime=item.mime,
                    size_bytes=item.size_bytes,
                    duration_seconds=item.duration_seconds,
                    error_code=None if item.provider_file_ref else "NO_FILE",
                )
            )
        event.message_id = message.id
        await self.core.route_new_customer_message(
            db, actor, conversation, operator_requested=inbound.intent_hint == "OPERATOR_REQUEST"
        )
        await emit(
            db,
            actor,
            event_type="messaging.message.received",
            shop_id=shop_id,
            aggregate_type=MESSAGE,
            aggregate_id=message.id,
            aggregate_version=1,
            payload=conversation_payload(
                conversation, seq=message.seq, kind=message.kind, attachments=len(inbound.attachments)
            ),
        )
        return IngestResult(
            duplicate=False, message_id=message.id, conversation_id=conversation.id, seq=message.seq
        )

    async def _echo(
        self, db: AsyncSession, account: ChannelAccount, inbound: InboundMessage, event: ProviderEvent
    ) -> IngestResult:
        """Akkauntning o'zi yuborgan xabar. Bizdan ketgani (AI/xodim) allaqachon bor — tashlanadi; Instagram
        ilovasidan qo'lda yozilgani suhbatga xodim xabari (`STAFF`, yuborilgan) bo'lib yoziladi."""
        ours = await db.scalar(
            select(Message.id).where(
                Message.shop_id == account.shop_id,
                Message.provider_message_id == inbound.provider_message_id,
            )
        )
        identity = await db.scalar(
            select(CustomerIdentity).where(
                CustomerIdentity.shop_id == account.shop_id,
                CustomerIdentity.channel == account.channel,
                CustomerIdentity.external_user_id == inbound.external_user_id,
            )
        )
        conversation = (
            await db.scalar(
                select(Conversation)
                .where(
                    Conversation.shop_id == account.shop_id, Conversation.customer_identity_id == identity.id
                )
                .with_for_update()
            )
            if identity is not None
            else None
        )
        if ours is not None or conversation is None:
            event.status = "IGNORED"  # o'zimizniki yoki suhbat yo'q (xaridor hali yozmagan)
            return IngestResult(duplicate=False, ignored=True)
        recent_send = await db.scalar(  # yuborish javobi (mid) hali yozilmagan bo'lishi mumkin: matn bo'yicha
            select(Message.id).where(
                Message.shop_id == account.shop_id,
                Message.conversation_id == conversation.id,
                Message.direction == "OUT",
                Message.body == inbound.body,
                Message.created_at > utcnow() - timedelta(minutes=2),
            )
        )
        if recent_send is not None:
            event.status = "IGNORED"
            return IngestResult(duplicate=False, ignored=True)
        now = utcnow()
        conversation.message_seq += 1
        message = Message(
            shop_id=account.shop_id,
            conversation_id=conversation.id,
            seq=conversation.message_seq,
            direction="OUT",
            author_type="STAFF",
            origin="STAFF",
            kind=inbound.kind,
            body=inbound.body,
            provider_message_id=inbound.provider_message_id,
            occurred_at=inbound.occurred_at,
            delivery_status="SENT",
            sent_at=now,
        )
        db.add(message)
        conversation.last_message_at = now
        await db.flush()
        event.message_id = message.id
        await emit(
            db,
            ActorContext.system(account.shop_id),
            event_type="messaging.message.sent",
            shop_id=account.shop_id,
            aggregate_type=MESSAGE,
            aggregate_id=message.id,
            aggregate_version=1,
            payload=conversation_payload(conversation, seq=message.seq, delivery_status="SENT"),
        )
        return IngestResult(
            duplicate=False, message_id=message.id, conversation_id=conversation.id, seq=message.seq
        )

    async def _identity(
        self, db: AsyncSession, account: ChannelAccount, inbound: InboundMessage
    ) -> CustomerIdentity:
        await db.execute(
            insert(CustomerIdentity)
            .values(
                shop_id=account.shop_id,
                channel=account.channel,
                external_user_id=inbound.external_user_id,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["shop_id", "channel", "external_user_id"])
        )
        identity = (
            await db.execute(
                select(CustomerIdentity)
                .where(
                    CustomerIdentity.shop_id == account.shop_id,
                    CustomerIdentity.channel == account.channel,
                    CustomerIdentity.external_user_id == inbound.external_user_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        if identity.erased_at is None:
            if inbound.display_name and identity.display_name != inbound.display_name:
                identity.display_name = inbound.display_name
            if inbound.username and identity.username != inbound.username:
                identity.username = inbound.username[:64]
        if inbound.language_code and (identity.locale is None or identity.channel == "WEB_CHAT"):
            identity.locale = inbound.language_code
        phone = customer_phone(inbound.contact_phone)
        if phone is not None:
            identity.phone_enc = phone
            identity.phone_hmac = search_hmac(phone)
            identity.contact_consent_at = utcnow()  # "Raqamni yuborish" — o'zi bosdi (BL-036)
            identity.erased_at = None
        identity.last_seen_at = utcnow()
        identity.blocked_at = None  # yozdi — demak bloklamagan
        return identity

    async def _conversation(
        self, db: AsyncSession, account: ChannelAccount, identity: CustomerIdentity
    ) -> Conversation:
        await db.execute(
            insert(Conversation)
            .values(
                shop_id=account.shop_id,
                customer_identity_id=identity.id,
                channel_account_id=account.id,
                channel=account.channel,
                locale=identity.locale,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["shop_id", "customer_identity_id"])
        )
        conversation = (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.shop_id == account.shop_id,
                    Conversation.customer_identity_id == identity.id,
                )
                .with_for_update()
            )
        ).scalar_one()
        if conversation.channel_account_id != account.id:
            conversation.channel_account_id = account.id  # bot qayta ulangan — yangi akkauntga (13 §5)
        return conversation

    async def _edit(
        self, db: AsyncSession, conversation: Conversation, inbound: InboundMessage, event: ProviderEvent
    ) -> IngestResult:
        target = None
        if inbound.provider_message_id:
            target = (
                await db.execute(
                    select(Message).where(
                        Message.shop_id == conversation.shop_id,
                        Message.conversation_id == conversation.id,
                        Message.direction == "IN",
                        Message.provider_message_id == inbound.provider_message_id,
                    )
                )
            ).scalar_one_or_none()
        if target is None:
            event.status, event.error_code = "IGNORED", "EDIT_TARGET_MISSING"
            return IngestResult(duplicate=False, ignored=True)
        target.body = inbound.body
        target.edited_at = utcnow()
        event.message_id = target.id
        return IngestResult(
            duplicate=False, message_id=target.id, conversation_id=conversation.id, seq=target.seq
        )
