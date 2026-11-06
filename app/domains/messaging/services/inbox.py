"""Yagona inbox (S2-03, M10): ro'yxat, suhbat kartochkasi, javob, olish, biriktirish, yopish, izohlar.

Kim nimani ko'radi (10 §6.4, §6.8): ega va menejer — hamma suhbat; operator — o'ziga biriktirilgan va
biriktirilmagan navbat. Operator javob yozsa, suhbat avtomatik uniki bo'ladi (`TAKE_OVER`, speaker +1).
Yopilgan suhbatga yozish — avval qayta ochiladi (`REOPEN`), keyin oladi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import (
    ensure_scope,
    is_supervisor,
    not_found,
)
from app.domains.messaging.models.orm import Conversation, ConversationNote, CustomerIdentity, Message
from app.domains.messaging.schemas import (
    ConversationCounts,
    ConversationList,
    ConversationOrderIn,
    ConversationOut,
    MessageList,
    MessageOut,
    NoteList,
    NoteOut,
    OrderRefList,
    OrderRefOut,
)
from app.domains.messaging.services.core import ConversationCore
from app.domains.messaging.services.outbound import MessageWriter, reachability
from app.domains.messaging.services.views import (
    detail_out,
    item_out,
    last_messages,
    member_names,
    messages_out,
    unread_counts,
)
from app.platform.notifications.services.recipients import resolve_members
from app.platform.storage.services.file_service import FileService
from app.shared.clock import utcnow
from app.shared.contracts.commerce import ConversationOrdersPort
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import ForbiddenError, InvalidTransitionError, ValidationError
from app.shared.http import check_version
from app.shared.pagination import DEFAULT_LIMIT, decode_cursor, encode_cursor
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

OPEN_STATUSES = ("NEW", "AI_ACTIVE", "WAITING_CUSTOMER", "HUMAN_NEEDED", "HUMAN_ACTIVE", "REOPENED")
TAKEABLE = frozenset({"HUMAN_NEEDED", "AI_ACTIVE", "WAITING_CUSTOMER", "REOPENED"})
ASSIGNABLE_ROLES = ("OWNER", "MANAGER", "SALES")


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _field(name: str, code: str) -> dict[str, Any]:
    return {"field": name, "code": code, "params": {}}


class InboxService:
    def __init__(
        self,
        core: ConversationCore,
        writer: MessageWriter,
        files: FileService,
        orders: ConversationOrdersPort,
    ) -> None:
        self.core = core
        self.writer = writer
        self.files = files
        self.orders = orders

    # ================================================================== o'qish
    def _scoped(self, actor: ActorContext) -> Any:
        conditions: list[Any] = [Conversation.shop_id == actor.shop_id]
        if not is_supervisor(actor):
            conditions.append(
                or_(
                    Conversation.assignee_membership_id == actor.membership_id,
                    Conversation.assignee_membership_id.is_(None),
                )
            )
        return and_(*conditions)

    async def list_conversations(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        statuses: list[str],
        channel: str | None,
        assigned: str | None,
        unread: bool,
        tag: str | None,
        q: str | None,
        cursor: str | None,
        limit: int = DEFAULT_LIMIT,
    ) -> ConversationList:
        sort_at = func.coalesce(Conversation.last_message_at, Conversation.created_at)
        query = (
            select(Conversation, CustomerIdentity)
            .join(
                CustomerIdentity,
                and_(
                    CustomerIdentity.shop_id == Conversation.shop_id,
                    CustomerIdentity.id == Conversation.customer_identity_id,
                ),
            )
            .where(self._scoped(actor))
        )
        if statuses:
            query = query.where(Conversation.status.in_(statuses))
        if channel:
            query = query.where(Conversation.channel == channel)
        if assigned == "me":
            query = query.where(Conversation.assignee_membership_id == actor.membership_id)
        elif assigned == "unassigned":
            query = query.where(Conversation.assignee_membership_id.is_(None))
        elif assigned:
            try:
                query = query.where(Conversation.assignee_membership_id == UUID(assigned))
            except ValueError as exc:
                raise ValidationError(
                    "Invalid assigned filter", fields=[_field("assigned", "invalid_format")]
                ) from exc
        if unread:
            query = query.where(
                exists().where(
                    Message.shop_id == Conversation.shop_id,
                    Message.conversation_id == Conversation.id,
                    Message.direction == "IN",
                    Message.seq > Conversation.staff_last_read_seq,
                )
            )
        if tag:
            query = query.where(Conversation.tags.contains([tag]))
        if q:
            query = query.where(self._search(q))
        if cursor:
            values = decode_cursor(cursor)
            try:
                at, last_id = datetime.fromisoformat(str(values["t"])), UUID(str(values["id"]))
            except (KeyError, ValueError, TypeError) as exc:
                raise ValidationError(
                    "Cursor is invalid", fields=[_field("cursor", "invalid_format")]
                ) from exc
            query = query.where(or_(sort_at < at, and_(sort_at == at, Conversation.id < last_id)))
        rows = (
            await db.execute(query.order_by(sort_at.desc(), Conversation.id.desc()).limit(limit + 1))
        ).all()
        page = rows[:limit]
        conversations = [c for c, _ in page]
        unread_map = await unread_counts(db, conversations)
        last_map = await last_messages(db, conversations)
        next_cursor = None
        if len(rows) > limit and page:
            last_conv = page[-1][0]
            next_cursor = encode_cursor(
                {
                    "t": (last_conv.last_message_at or last_conv.created_at).isoformat(),
                    "id": str(last_conv.id),
                }
            )
        names = (
            await member_names(db, actor.shop_id, [c.assignee_membership_id for c in conversations])
            if actor.shop_id
            else {}
        )
        return ConversationList(
            items=[item_out(c, i, last_map.get(c.id), unread_map.get(c.id, 0), names) for c, i in page],
            next_cursor=next_cursor,
            has_more=len(rows) > limit,
        )

    @staticmethod
    def _search(q: str) -> Any:
        text = q.strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        conditions: list[Any] = [
            CustomerIdentity.display_name.ilike(_like(text), escape="\\"),
            CustomerIdentity.username.ilike(_like(text.lstrip("@")), escape="\\"),
        ]
        if len(digits) >= 9:
            try:
                conditions.append(CustomerIdentity.phone_hmac == search_hmac(normalize_phone(text, "q")))
            except ValidationError:
                pass
        return or_(*conditions)

    async def counts(self, db: AsyncSession, actor: ActorContext) -> ConversationCounts:
        base = (
            select(func.count())
            .select_from(Conversation)
            .where(self._scoped(actor), Conversation.status.in_(OPEN_STATUSES))
        )
        unread_exists = exists().where(
            Message.shop_id == Conversation.shop_id,
            Message.conversation_id == Conversation.id,
            Message.direction == "IN",
            Message.seq > Conversation.staff_last_read_seq,
        )

        async def count(*extra: Any) -> int:
            return int(await db.scalar(base.where(*extra)) or 0)

        return ConversationCounts(
            open=await count(),
            mine=await count(Conversation.assignee_membership_id == actor.membership_id),
            unassigned=await count(Conversation.assignee_membership_id.is_(None)),
            human_needed=await count(Conversation.status == "HUMAN_NEEDED"),
            unread=await count(unread_exists),
        )

    async def _load(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, *, lock: bool = False
    ) -> Conversation:
        assert actor.shop_id is not None
        if lock:
            conversation = await self.core.lock(db, actor.shop_id, conversation_id)
        else:
            conversation = (
                await db.execute(
                    select(Conversation).where(
                        Conversation.shop_id == actor.shop_id, Conversation.id == conversation_id
                    )
                )
            ).scalar_one_or_none()
        if conversation is None:
            raise not_found()
        ensure_scope(actor, conversation)
        return conversation

    async def detail(self, db: AsyncSession, actor: ActorContext, conversation_id: UUID) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id)
        return await self._detail(db, actor, conversation)

    async def _detail(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation
    ) -> ConversationOut:
        identity = await db.get(CustomerIdentity, conversation.customer_identity_id)
        assert identity is not None
        handoff = (
            await self.core.open_handoff_of(db, conversation)
            if conversation.status == "HUMAN_NEEDED"
            else None
        )
        unread = (await unread_counts(db, [conversation])).get(conversation.id, 0)
        reach = await reachability(db, conversation)
        names = await member_names(db, conversation.shop_id, [conversation.assignee_membership_id])
        name = names.get(conversation.assignee_membership_id) if conversation.assignee_membership_id else None
        gate = await self.core.gate(db, conversation.shop_id)
        return detail_out(
            actor, conversation, identity, handoff, unread, reach.ok, name, ai_speaks=gate.speaks
        )

    async def resume_ai(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, expected_version: int
    ) -> ConversationOut:
        """Operator suhbatni AI'ga qaytaradi (6b): faqat AI shu shopda javob bersa (SUGGEST/AUTO, faol)."""
        conversation = await self._load(db, actor, conversation_id, lock=True)
        check_version(conversation.version, expected_version)
        gate = await self.core.gate(db, conversation.shop_id)
        if not gate.speaks:
            raise InvalidTransitionError(
                "AI is not available for this shop",
                entity="messaging.conversation",
                **{"from": conversation.status},
                command="RETURN_TO_AI",
                reason=(gate.reason or "OFF").lower(),
            )
        await self.core.transition(db, actor, conversation, "RETURN_TO_AI", "AI_ACTIVE")
        await self.core.close_handoff(db, actor, conversation, status="CANCELLED")
        await self.writer.conversation_changed(db, actor, conversation, "ai_resumed")
        return await self._detail(db, actor, conversation)

    async def messages(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        *,
        before_seq: int | None,
        after_seq: int | None,
        limit: int,
    ) -> MessageList:
        conversation = await self._load(db, actor, conversation_id)
        query = select(Message).where(
            Message.shop_id == conversation.shop_id, Message.conversation_id == conversation.id
        )
        if after_seq is not None:
            rows = (
                (await db.execute(query.where(Message.seq > after_seq).order_by(Message.seq).limit(limit)))
                .scalars()
                .all()
            )
            has_more_before = after_seq > 0
        else:
            if before_seq is not None:
                query = query.where(Message.seq < before_seq)
            rows = list(
                reversed(
                    (await db.execute(query.order_by(Message.seq.desc()).limit(limit + 1))).scalars().all()
                )
            )
            has_more_before = len(rows) > limit
            rows = rows[-limit:] if has_more_before else rows
        return MessageList(items=await messages_out(db, self.files, rows), has_more_before=has_more_before)

    # ================================================================== yozish
    async def reply(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        *,
        body: str | None,
        attachment_file_id: UUID | None,
        idempotency_key: str,
    ) -> MessageOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        if conversation.status == "RESOLVED":
            await self.core.transition(db, actor, conversation, "REOPEN", "REOPENED")
        was_unassigned = conversation.assignee_membership_id is None
        await self._take_if_needed(db, actor, conversation)
        message = await self.writer.append_outbound(
            db,
            actor,
            conversation,
            origin="STAFF",
            author_type="STAFF",
            author_membership_id=actor.membership_id,
            body=body,
            attachment_file_id=attachment_file_id,
            intent_key=f"staff:{idempotency_key}",
        )
        if conversation.status == "HUMAN_ACTIVE":
            await self.core.transition(db, actor, conversation, "AWAIT_CUSTOMER", "WAITING_CUSTOMER")
        if conversation.first_staff_reply_at is None:
            conversation.first_staff_reply_at = utcnow()
        await self._mark_read(db, conversation, conversation.message_seq)
        left_queue = was_unassigned and conversation.assignee_membership_id is not None
        await self.writer.conversation_changed(
            db, actor, conversation, "updated", command="REPLY", left_queue=left_queue
        )
        return (await messages_out(db, self.files, [message]))[0]

    async def _take_if_needed(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation
    ) -> None:
        """Operator javob yozyapti: suhbat hali uniki bo'lmasa — oladi (fencing: speaker +1)."""
        if conversation.speaker_mode == "HUMAN" and conversation.status in (
            "HUMAN_ACTIVE",
            "WAITING_CUSTOMER",
        ):
            if conversation.assignee_membership_id is None:
                conversation.assignee_membership_id = actor.membership_id
            return
        if conversation.status not in TAKEABLE:
            return
        if "messaging.conversation.takeover" not in actor.permissions:
            raise ForbiddenError("Permission denied", permission="messaging.conversation.takeover")
        await self.core.transition(db, actor, conversation, "TAKE_OVER", "HUMAN_ACTIVE")
        if conversation.assignee_membership_id is None or not is_supervisor(actor):
            conversation.assignee_membership_id = actor.membership_id
        await self.core.close_handoff(db, actor, conversation, status="TAKEN", taken_by=actor.membership_id)

    async def take(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, expected_version: int
    ) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        check_version(conversation.version, expected_version)
        previous = conversation.assignee_membership_id
        if conversation.status == "RESOLVED":
            raise InvalidTransitionError(
                "Conversation is resolved",
                entity="messaging.conversation",
                **{"from": "RESOLVED"},
                command="TAKE_OVER",
            )
        if conversation.status in TAKEABLE or conversation.speaker_mode != "HUMAN":
            await self.core.transition(db, actor, conversation, "TAKE_OVER", "HUMAN_ACTIVE")
            await self.core.close_handoff(
                db, actor, conversation, status="TAKEN", taken_by=actor.membership_id
            )
        conversation.assignee_membership_id = actor.membership_id
        await self.writer.conversation_changed(
            db,
            actor,
            conversation,
            "taken",
            previous_assignee_id=previous if previous != actor.membership_id else None,
            left_queue=previous is None,  # navbatdan olindi — boshqa operatorlar ro'yxatidan ham tushadi (L2)
        )
        return await self._detail(db, actor, conversation)

    async def assign(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        expected_version: int,
        membership_id: UUID,
    ) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        check_version(conversation.version, expected_version)
        assert actor.shop_id is not None
        members = await resolve_members(db, actor.shop_id, membership_ids=[membership_id])
        if not members or members[0].role not in ASSIGNABLE_ROLES:
            raise ValidationError(
                "Member cannot take conversations", fields=[_field("membership_id", "invalid_choice")]
            )
        previous = conversation.assignee_membership_id
        if previous == membership_id:
            return await self._detail(db, actor, conversation)
        conversation.assignee_membership_id = membership_id
        if conversation.status == "HUMAN_NEEDED":
            # Navbatdagi suhbat yangi mas'ulga: HANDOFF vazifasi uning nomiga qayta ochiladi
            handoff = await self.core.open_handoff_of(db, conversation)
            await self.core.tasks.resolve(
                db,
                shop_id=conversation.shop_id,
                actor=actor,
                subject_type="messaging.conversation",
                subject_id=conversation.id,
                types=["HANDOFF"],
            )
            if handoff is not None:
                await self.core.tasks.open(
                    db,
                    shop_id=conversation.shop_id,
                    actor=actor,
                    type="HANDOFF",
                    subject_type="messaging.conversation",
                    subject_id=conversation.id,
                    dedup_key=f"handoff:{handoff.id}:{membership_id}",
                    assignee_membership_id=membership_id,
                    assignee_role="SALES",
                    priority="HIGH",
                    params={"channel": conversation.channel, "reason": handoff.reason},
                )
        await db.flush()
        await self.writer.conversation_changed(
            db, actor, conversation, "assigned", previous_assignee_id=previous, left_queue=previous is None
        )
        return await self._detail(db, actor, conversation)

    async def resolve(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, expected_version: int
    ) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        check_version(conversation.version, expected_version)
        await self.core.transition(db, actor, conversation, "RESOLVE", "RESOLVED")
        await self.core.close_handoff(db, actor, conversation, status="CANCELLED")
        conversation.resolved_at, conversation.resolved_by = utcnow(), actor.membership_id
        await self.writer.conversation_changed(db, actor, conversation, "resolved")
        return await self._detail(db, actor, conversation)

    async def reopen(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, expected_version: int
    ) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        check_version(conversation.version, expected_version)
        await self.core.transition(db, actor, conversation, "REOPEN", "REOPENED")
        conversation.resolved_at, conversation.resolved_by = None, None
        await self.writer.conversation_changed(db, actor, conversation, "reopened")
        return await self._detail(db, actor, conversation)

    async def mark_read(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, seq: int
    ) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id)
        await self._mark_read(db, conversation, seq)
        await db.refresh(conversation)
        return await self._detail(db, actor, conversation)

    @staticmethod
    async def _mark_read(db: AsyncSession, conversation: Conversation, seq: int) -> None:
        """Faqat oshadi; versiyani o'zgartirmaydi (o'qish boshqa xodimning If-Match'ini buzmasin)."""
        await db.execute(
            update(Conversation)
            .where(
                Conversation.shop_id == conversation.shop_id,
                Conversation.id == conversation.id,
                Conversation.staff_last_read_seq < func.least(seq, Conversation.message_seq),
            )
            .values(staff_last_read_seq=func.least(seq, Conversation.message_seq))
            .execution_options(synchronize_session=False)
        )

    async def set_tags(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        expected_version: int,
        tags: list[str],
    ) -> ConversationOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        check_version(conversation.version, expected_version)
        conversation.tags = list(dict.fromkeys(tags))  # takrorsiz, tartib saqlanadi
        await db.flush()
        return await self._detail(db, actor, conversation)

    async def notes(self, db: AsyncSession, actor: ActorContext, conversation_id: UUID) -> NoteList:
        conversation = await self._load(db, actor, conversation_id)
        rows = await db.execute(
            select(ConversationNote)
            .where(
                ConversationNote.shop_id == conversation.shop_id,
                ConversationNote.conversation_id == conversation.id,
            )
            .order_by(ConversationNote.created_at)
        )
        return NoteList(
            items=[
                NoteOut(
                    id=n.id, author_membership_id=n.author_membership_id, body=n.body, created_at=n.created_at
                )
                for n in rows.scalars()
            ]
        )

    async def add_note(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, body: str
    ) -> NoteOut:
        conversation = await self._load(db, actor, conversation_id)
        assert actor.membership_id is not None
        note = ConversationNote(
            shop_id=conversation.shop_id,
            conversation_id=conversation.id,
            author_membership_id=actor.membership_id,
            body=body,
        )
        db.add(note)
        await db.flush()
        await db.refresh(note)
        return NoteOut(
            id=note.id,
            author_membership_id=note.author_membership_id,
            body=note.body,
            created_at=note.created_at,
        )

    # ================================================================== buyurtma (ConversationOrdersPort)
    async def create_order(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, data: ConversationOrderIn
    ) -> OrderRefOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        identity = await db.get(CustomerIdentity, conversation.customer_identity_id)
        assert identity is not None
        phone = identity.phone_enc
        if phone is not None:
            try:
                phone = normalize_phone(phone)
            except ValidationError:
                phone = None  # chet el raqami — operator buyurtmada o'zi kiritadi
        ref = await self.orders.create_draft(
            db,
            actor,
            conversation_id=conversation.id,
            customer_ref=identity.id,
            customer_name=identity.display_name,
            customer_phone=phone,
            customer_locale=conversation.locale or identity.locale or "uz",
            branch_id=data.branch_id,
            fulfillment_method=data.fulfillment_method,
        )
        conversation.last_order_id = ref.id
        await db.flush()
        await self.writer.conversation_changed(db, actor, conversation, "order_linked", order_id=ref.id)
        return OrderRefOut(id=ref.id, number=ref.number, status=ref.status)

    async def link_order(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        order_id: UUID,
        *,
        relink: bool = False,
        expected_version: int | None = None,
    ) -> OrderRefOut:
        conversation = await self._load(db, actor, conversation_id, lock=True)
        ref = await self.orders.link(
            db,
            actor,
            order_id=order_id,
            conversation_id=conversation.id,
            customer_ref=conversation.customer_identity_id,
            relink=relink,
            expected_version=expected_version,
        )
        conversation.last_order_id = ref.id
        await db.flush()
        await self.writer.conversation_changed(db, actor, conversation, "order_linked", order_id=ref.id)
        if ref.previous_conversation_id is not None:
            await self._unlink_previous(db, actor, ref.previous_conversation_id, ref.id)
        return OrderRefOut(id=ref.id, number=ref.number, status=ref.status)

    async def _unlink_previous(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, order_id: UUID
    ) -> None:
        """Ko'chirilgan buyurtma eski suhbatda "oxirgi buyurtma" bo'lib qolmasin (QA 5b M3)."""
        previous = await self.core.lock(db, actor.shop_id, conversation_id) if actor.shop_id else None
        if previous is None or previous.last_order_id != order_id:
            return
        remaining = [
            r for r in await self.orders.for_conversation(db, actor, previous.id) if r.id != order_id
        ]
        previous.last_order_id = remaining[0].id if remaining else None
        await db.flush()
        await self.writer.conversation_changed(db, actor, previous, "order_unlinked", order_id=order_id)

    async def orders_of(self, db: AsyncSession, actor: ActorContext, conversation_id: UUID) -> OrderRefList:
        conversation = await self._load(db, actor, conversation_id)
        refs = await self.orders.for_conversation(db, actor, conversation.id)
        return OrderRefList(items=[OrderRefOut(id=r.id, number=r.number, status=r.status) for r in refs])
