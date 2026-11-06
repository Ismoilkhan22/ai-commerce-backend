"""Chiquvchi xabarni kanalga yuborish (`channel_send`, 13 §4, 06 §4.2) va xaridor rasmini yuklab olish.

Tashqi chaqiruv tranzaksiyadan TASHQARIDA: avval xabar `SENDING` (urinish +1) — COMMIT; keyin Telegram;
keyin natija — alohida tranzaksiyada:
- qabul qildi → `SENT`;
- 429 / 5xx / tarmoq → yana `QUEUED` va qayta urinish (Retry-After bilan), 5-urinishda `FAILED`;
- javob kelmadi (timeout) → `UNKNOWN`: yuborildimi noma'lum, ko'r-ko'rona qayta yuborilmaydi;
- 403 (xaridor botni bloklagan) va boshqa yakuniy xato → `FAILED` + xodimga vazifa (TC-011).
AI javobi yuborishdan oldin yana tekshiriladi: speaker o'zgargan bo'lsa → `DISCARDED` (TC-009).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.base import ChannelSendError, SendResult
from app.domains.messaging.channels.instagram import WINDOW_HOURS
from app.domains.messaging.channels.telegram import MAX_CAPTION, split_text
from app.domains.messaging.common import (
    CHANNEL,
    CONVERSATION,
    MAX_SEND_ATTEMPTS,
    MESSAGE,
    SENDABLE_CHANNEL_STATUSES,
    ChannelAdapters,
    channel_label,
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
from app.domains.messaging.state_machine import CHANNEL as CHANNEL_ENTITY
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import CHANNEL_DEGRADED, MESSAGE_FAILED, TaskService
from app.platform.storage.models.orm import StoredFile
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.db.session import Database
from app.shared.errors.base import PayloadTooLargeError, UnsupportedMediaTypeError, ValidationError
from app.shared.events.registry import RetryLater
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)
STUCK_SENDING_AFTER = timedelta(minutes=5)
DOWNLOADABLE = frozenset({"IMAGE"})  # Stage 1: faqat rasm saqlanadi; ovoz/fayl — "Telegram'da oching"


@dataclass(frozen=True)
class _Job:
    channel: str
    token: str | None
    fake: bool
    external_account_id: str | None
    chat: str
    body: str | None
    photo: tuple[bytes, str] | None
    attempts: int
    parts_sent: int = 0


def telegram_steps(body: str | None, has_photo: bool) -> list[tuple[str, str | None]]:
    """Telegram yuborish qadamlari: ("photo", izoh) va/yoki ("text", bo'lak).

    Uzun matn — 4096 belgilik bo'laklar. Rasm izohi 1024 belgigacha (Telegram chegarasi): uzunroq bo'lsa,
    izohga birinchi bo'lak, qolgani rasmdan keyin oddiy matn bo'lib ketadi (QA 5b L8 — jim kesilmaydi)."""
    text = body or ""
    if not has_photo:
        return [("text", part) for part in split_text(text)]
    if len(text) <= MAX_CAPTION:
        return [("photo", text or None)]
    caption, *_ = split_text(text, MAX_CAPTION)
    rest = text[len(caption) :].lstrip()
    return [("photo", caption), *(("text", part) for part in split_text(rest))]


def _backoff(attempt: int) -> int:
    return int(min(2**attempt * 5, 300))


class SendingService:
    def __init__(self, adapters: ChannelAdapters, files: FileService, use: UseService) -> None:
        self.adapters = adapters
        self.files = files
        self.use = use
        self.tasks = TaskService()
        self.notifications = NotificationService()

    # ------------------------------------------------------------------ yuborish
    async def send(self, database: Database, shop_id: UUID, message_id: UUID) -> str:
        """Natija: sent | discarded | failed | unknown | skipped (allaqachon yakunlangan)."""
        async with database.transaction(shop_id) as db:
            prepared = await self._prepare(db, shop_id, message_id)
        if isinstance(prepared, str):
            return prepared
        try:
            result = await self._call(prepared)
        except ChannelSendError as exc:
            async with database.transaction(shop_id) as db:
                outcome = await self._failed(
                    db, shop_id, message_id, exc, prepared.attempts, getattr(exc, "parts_sent", None)
                )
            if outcome == "retry":
                raise RetryLater(exc.retry_after or _backoff(prepared.attempts)) from exc
            return outcome
        async with database.transaction(shop_id) as db:
            await self._sent(db, shop_id, message_id, result)
        return "sent"

    async def _prepare(self, db: AsyncSession, shop_id: UUID, message_id: UUID) -> _Job | str:
        message = (
            await db.execute(
                select(Message).where(Message.shop_id == shop_id, Message.id == message_id).with_for_update()
            )
        ).scalar_one_or_none()
        if message is None or message.delivery_status != "QUEUED":
            return "skipped"  # takroriy vazifa yoki allaqachon yakunlangan
        conversation = await db.get(Conversation, message.conversation_id)
        assert conversation is not None
        actor = ActorContext.system(shop_id)
        if message.origin == "AI_AUTO" and (
            conversation.speaker_mode != "AI" or conversation.speaker_version != message.speaker_version
        ):
            message.delivery_status, message.last_error_code = "DISCARDED", "SPEAKER_CHANGED"
            await self._event(db, actor, conversation, message, "messaging.message.discarded")
            return "discarded"
        account = await db.get(ChannelAccount, conversation.channel_account_id)
        identity = await db.get(CustomerIdentity, conversation.customer_identity_id)
        if account is None or account.status not in SENDABLE_CHANNEL_STATUSES or identity is None:
            await self._final_failure(db, actor, conversation, message, "CHANNEL_DISCONNECTED")
            return "failed"
        if account.channel == "INSTAGRAM" and (
            conversation.last_inbound_at is None
            or conversation.last_inbound_at < utcnow() - timedelta(hours=WINDOW_HOURS)
        ):
            await self._final_failure(db, actor, conversation, message, "WINDOW_CLOSED")  # BL-033
            return "failed"
        photo = await self._photo(db, message)
        message.delivery_status = "SENDING"
        message.sending_started_at = utcnow()
        message.attempts += 1
        return _Job(
            channel=account.channel,
            token=account.token_enc,
            fake=bool((account.settings or {}).get("fake")),
            external_account_id=account.external_account_id,
            chat=identity.external_user_id,
            body=message.body,
            photo=photo,
            attempts=message.attempts,
            parts_sent=message.parts_sent,
        )

    async def _photo(self, db: AsyncSession, message: Message) -> tuple[bytes, str] | None:
        attachment = (
            await db.execute(
                select(Attachment).where(
                    Attachment.shop_id == message.shop_id,
                    Attachment.message_id == message.id,
                    Attachment.status == "STORED",
                )
            )
        ).scalar_one_or_none()
        if attachment is None or attachment.file_id is None:
            return None
        row = await db.get(StoredFile, attachment.file_id)
        if row is None or row.status != "ACTIVE":
            return None
        data = await self.files.read_bytes(row)
        return (data, row.mime_type) if data is not None else None

    async def _call(self, job: _Job) -> SendResult:
        if job.fake:  # dev seed'dagi soxta akkaunt: tashqariga hech narsa ketmaydi
            logger.info("messaging.fake_send", channel=job.channel, length=len(job.body or ""))
            return SendResult(provider_message_id="fake")
        if job.channel == "TELEGRAM":
            if not job.token:
                raise ChannelSendError("AUTH_REVOKED")
            try:
                chat_id = int(job.chat)
            except ValueError as exc:
                raise ChannelSendError("BAD_RECIPIENT") from exc
            return await self._telegram(job, job.token, chat_id)
        if job.channel == "INSTAGRAM":
            if not job.token or not job.external_account_id:
                raise ChannelSendError("AUTH_REVOKED")
            return await self.adapters.instagram.send_message(
                job.token, job.external_account_id, job.chat, job.body or ""
            )
        return SendResult(provider_message_id=None)  # sayt chati — tashqi yuborish yo'q

    async def _telegram(self, job: _Job, token: str, chat_id: int) -> SendResult:
        """Qadamlab yuborish: oldin ketgan bo'laklar (`parts_sent`) qayta yuborilmaydi (QA 5b L8)."""
        steps = telegram_steps(job.body, job.photo is not None)
        first: str | None = None
        for index in range(job.parts_sent, len(steps)):
            kind, value = steps[index]
            try:
                if kind == "photo" and job.photo is not None:
                    result = await self.adapters.telegram.send_photo(
                        token, chat_id, job.photo[0], job.photo[1], value
                    )
                else:
                    result = await self.adapters.telegram.send_message(token, chat_id, value or "")
            except ChannelSendError as exc:
                exc.parts_sent = index  # type: ignore[attr-defined]
                raise
            first = first or result.provider_message_id
        return SendResult(provider_message_id=first, parts=len(steps))

    async def _sent(self, db: AsyncSession, shop_id: UUID, message_id: UUID, result: SendResult) -> None:
        message = await self._locked(db, shop_id, message_id)
        if message is None:
            return
        stuck = message.delivery_status == "UNKNOWN" and message.last_error_code == "STUCK"
        if message.delivery_status != "SENDING" and not stuck:
            return  # rejali ish "osilib qoldi" degan bo'lsa ham — kanal qabul qildi: SENT (QA 5b M5)
        message.delivery_status, message.sent_at = "SENT", utcnow()
        message.provider_message_id, message.parts = result.provider_message_id, result.parts
        message.parts_sent = result.parts
        message.last_error_code = None
        conversation = await db.get(Conversation, message.conversation_id)
        assert conversation is not None
        await self._event(db, ActorContext.system(shop_id), conversation, message, "messaging.message.sent")

    async def _failed(
        self,
        db: AsyncSession,
        shop_id: UUID,
        message_id: UUID,
        exc: ChannelSendError,
        attempts: int,
        parts_sent: int | None = None,
    ) -> str:
        message = await self._locked(db, shop_id, message_id)
        if message is None or message.delivery_status != "SENDING":
            return "skipped"
        if parts_sent is not None:
            message.parts_sent = parts_sent
        conversation = await db.get(Conversation, message.conversation_id)
        assert conversation is not None
        actor = ActorContext.system(shop_id)
        message.last_error_code = exc.code
        if exc.unknown:
            message.delivery_status = "UNKNOWN"
            await self._event(db, actor, conversation, message, "messaging.message.failed")
            return "unknown"
        if exc.retryable and attempts < MAX_SEND_ATTEMPTS:
            message.delivery_status = "QUEUED"
            return "retry"
        if exc.code == "BLOCKED":
            identity = await db.get(CustomerIdentity, conversation.customer_identity_id)
            if identity is not None:
                identity.blocked_at = utcnow()
        if exc.code == "AUTH_REVOKED":
            await self._mark_degraded(db, conversation.channel_account_id)
        await self._final_failure(db, actor, conversation, message, exc.code)
        return "failed"

    async def _final_failure(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation, message: Message, code: str
    ) -> None:
        message.delivery_status, message.failed_at, message.last_error_code = "FAILED", utcnow(), code
        await db.flush()
        await self._event(db, actor, conversation, message, "messaging.message.failed")
        if message.origin == "AI_AUTO":
            return
        await self.tasks.open(
            db,
            shop_id=conversation.shop_id,
            actor=actor,
            type=MESSAGE_FAILED,
            subject_type=CONVERSATION,
            subject_id=conversation.id,
            dedup_key=f"message_failed:{message.id}",
            assignee_membership_id=conversation.assignee_membership_id,
            assignee_role="SALES",
            params={"channel": conversation.channel, "error_code": code},
        )
        await self.notifications.notify_staff(
            db,
            shop_id=conversation.shop_id,
            actor=actor,
            template_key="staff.message_failed",
            aggregate_type=CONVERSATION,
            aggregate_id=conversation.id,
            aggregate_version=conversation.version,
            variables={"channel": channel_label(conversation.channel), "error_code": code},
            membership_ids=[conversation.assignee_membership_id],
            roles=("OWNER", "MANAGER"),
            dedup_scope=f"failed:{message.id}",
        )

    async def _mark_degraded(self, db: AsyncSession, account_id: UUID) -> None:
        """Token bekor qilingan (401) — kanal "muammoli" (FSM-03), egaga vazifa (CHANNEL_DEGRADED)."""
        account = (
            await db.execute(select(ChannelAccount).where(ChannelAccount.id == account_id).with_for_update())
        ).scalar_one_or_none()
        if account is None or account.status != "CONNECTED":
            return
        actor = ActorContext.system(account.shop_id)
        rule = self.use.validate_transition(CHANNEL_ENTITY, "CONNECTED", "DEGRADED", "MARK_DEGRADED", actor)
        account.status, account.last_error_code = "DEGRADED", "AUTH_REVOKED"
        await db.flush()
        await self.use.log_transition(db, entity_id=account.id, rule=rule, actor=actor, reason="AUTH_REVOKED")
        await self.tasks.open(
            db,
            shop_id=account.shop_id,
            actor=actor,
            type=CHANNEL_DEGRADED,
            subject_type=CHANNEL,
            subject_id=account.id,
            dedup_key=f"channel_degraded:{account.id}:{account.version}",
            assignee_role="OWNER",
            priority="HIGH",
            params={"channel": account.channel, "error_code": "AUTH_REVOKED"},
        )

    async def _event(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation, message: Message, event: str
    ) -> None:
        await emit(
            db,
            actor,
            event_type=event,
            shop_id=conversation.shop_id,
            aggregate_type=MESSAGE,
            aggregate_id=message.id,
            aggregate_version=message.attempts + 1,
            payload=conversation_payload(
                conversation,
                seq=message.seq,
                delivery_status=message.delivery_status,
                error_code=message.last_error_code,
            ),
        )

    @staticmethod
    async def _locked(db: AsyncSession, shop_id: UUID, message_id: UUID) -> Message | None:
        return (
            await db.execute(
                select(Message).where(Message.shop_id == shop_id, Message.id == message_id).with_for_update()
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------------ xaridor rasmi (webhook'dan keyin)
    async def fetch_attachments(self, database: Database, shop_id: UUID, message_id: UUID) -> int:
        """PENDING biriktirmalar: Telegram'dan yuklab olinadi va yopiq omborga (`CHAT_ATTACHMENT`). Rasm
        bo'lmagani — FAILED (`UNSUPPORTED_TYPE`): operator Telegram'da ochadi. Tarmoq xatosi — qayta
        urinish."""
        async with database.transaction(shop_id) as db:
            rows = (
                (
                    await db.execute(
                        select(Attachment).where(
                            Attachment.shop_id == shop_id,
                            Attachment.message_id == message_id,
                            Attachment.status == "PENDING",
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return 0
            message = await db.get(Message, message_id)
            conversation = await db.get(Conversation, message.conversation_id) if message else None
            account = await db.get(ChannelAccount, conversation.channel_account_id) if conversation else None
            token = account.token_enc if account is not None and account.channel == "TELEGRAM" else None
            fake = bool((account.settings or {}).get("fake")) if account is not None else False
            jobs = [(r.id, r.kind, r.provider_file_ref) for r in rows]
        stored = 0
        for attachment_id, kind, ref in jobs:
            if kind not in DOWNLOADABLE or not ref or not token or fake:
                await self._attachment_result(database, shop_id, attachment_id, None, "UNSUPPORTED_TYPE")
                continue
            try:
                data, _ = await self.adapters.telegram.download_file(token, ref)
            except ChannelSendError as exc:
                if exc.retryable:
                    raise RetryLater(_backoff(1)) from exc
                await self._attachment_result(database, shop_id, attachment_id, None, exc.code)
                continue
            if await self._attachment_result(database, shop_id, attachment_id, data, None):
                stored += 1
        return stored

    async def _attachment_result(
        self, database: Database, shop_id: UUID, attachment_id: UUID, data: bytes | None, error: str | None
    ) -> bool:
        async with database.transaction(shop_id) as db:
            row = (
                await db.execute(
                    select(Attachment)
                    .where(Attachment.shop_id == shop_id, Attachment.id == attachment_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None or row.status != "PENDING":
                return False
            if data is not None:
                try:
                    stored = await self.files.store_system(db, shop_id, "CHAT_ATTACHMENT", data, None)
                except (PayloadTooLargeError, UnsupportedMediaTypeError, ValidationError) as exc:
                    row.status, row.error_code = "FAILED", exc.code
                    return False
                row.status, row.file_id, row.mime, row.size_bytes = (
                    "STORED",
                    stored.id,
                    stored.mime_type,
                    stored.size_bytes,
                )
                row.provider_file_ref = None  # saqlangandan keyin kerak emas (db/messaging.md §6)
                return True
            row.status, row.error_code = "FAILED", error
            return False

    # ------------------------------------------------------------------ rejali ish
    async def mark_stuck_unknown(self, db: AsyncSession, shop_id: UUID) -> int:
        """5 daqiqadan beri SENDING (jarayon o'lgan) — yuborildimi noma'lum: UNKNOWN (06 §6)."""
        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(
                        Message.shop_id == shop_id,
                        Message.delivery_status == "SENDING",
                        func.coalesce(Message.sending_started_at, Message.created_at)
                        < utcnow() - STUCK_SENDING_AFTER,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for message in rows:
            message.delivery_status, message.last_error_code = "UNKNOWN", "STUCK"
            conversation = await db.get(Conversation, message.conversation_id)
            if conversation is not None:
                await self._event(
                    db, ActorContext.system(shop_id), conversation, message, "messaging.message.failed"
                )
        return len(rows)
