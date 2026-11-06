"""Inbox ko'rinishlari: suhbat ro'yxati, kartochka, xabarlar lentasi (biriktirmalar — imzoli havola bilan)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging import permissions as perm
from app.domains.messaging.common import is_supervisor, mask_phone
from app.domains.messaging.models.orm import Attachment, Conversation, CustomerIdentity, Handoff, Message
from app.domains.messaging.schemas import (
    AttachmentOut,
    ConversationAction,
    ConversationItem,
    ConversationOut,
    CustomerOut,
    HandoffOut,
    LastMessage,
    MessageOut,
)
from app.platform.staff.models.orm import Membership, Principal
from app.platform.storage.services.file_service import FileService
from app.shared.types.actor import ActorContext

PREVIEW = 120
RESOLVABLE = frozenset({"HUMAN_ACTIVE", "WAITING_CUSTOMER", "HUMAN_NEEDED", "REOPENED"})


def _preview(body: str | None) -> str | None:
    if not body:
        return None
    text = " ".join(body.split())
    return text if len(text) <= PREVIEW else text[: PREVIEW - 1] + "…"


async def unread_counts(db: AsyncSession, conversations: Sequence[Conversation]) -> dict[UUID, int]:
    """Kiruvchi xabarlar `staff_last_read_seq` dan keyin (8-qaror)."""
    if not conversations:
        return {}
    counts: dict[UUID, int] = {c.id: 0 for c in conversations}
    shop_id = conversations[0].shop_id
    rows = await db.execute(
        select(Message.conversation_id, func.count())
        .join(
            Conversation,
            (Conversation.id == Message.conversation_id) & (Conversation.shop_id == Message.shop_id),
        )
        .where(
            Message.shop_id == shop_id,
            Message.conversation_id.in_([c.id for c in conversations]),
            Message.direction == "IN",
            Message.seq > Conversation.staff_last_read_seq,
        )
        .group_by(Message.conversation_id)
    )
    for conversation_id, count in rows:
        counts[conversation_id] = int(count)
    return counts


async def last_messages(db: AsyncSession, conversations: Sequence[Conversation]) -> dict[UUID, Message]:
    keys = [(c.id, c.message_seq) for c in conversations if c.message_seq > 0]
    if not keys:
        return {}
    rows = await db.execute(
        select(Message).where(
            Message.shop_id == conversations[0].shop_id,
            tuple_(Message.conversation_id, Message.seq).in_(keys),
        )
    )
    return {m.conversation_id: m for m in rows.scalars()}


async def member_names(db: AsyncSession, shop_id: UUID, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    """Mas'ul xodim ismi — ro'yxat va kartochkada. Operator `/shop/members` ni chaqirmaydi (QA 5b L6)."""
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(
        select(Membership.id, Principal.full_name)
        .join(Principal, Principal.id == Membership.principal_id)
        .where(Membership.shop_id == shop_id, Membership.id.in_(wanted))
    )
    return {membership_id: name for membership_id, name in rows}


def item_out(
    conversation: Conversation,
    identity: CustomerIdentity | None,
    last: Message | None,
    unread: int,
    names: dict[UUID, str] | None = None,
) -> ConversationItem:
    return ConversationItem(
        id=conversation.id,
        channel=conversation.channel,
        status=conversation.status,
        speaker_mode=conversation.speaker_mode,
        assignee_membership_id=conversation.assignee_membership_id,
        assignee_name=(names or {}).get(conversation.assignee_membership_id)
        if conversation.assignee_membership_id
        else None,
        customer_name=identity.display_name if identity else None,
        customer_username=identity.username if identity else None,
        last_message=LastMessage(
            direction=last.direction,
            author_type=last.author_type,
            kind=last.kind,
            preview=_preview(last.body),
            at=last.occurred_at,
        )
        if last
        else None,
        last_message_at=conversation.last_message_at,
        unread_count=unread,
        tags=list(conversation.tags or []),
        waiting_since=conversation.waiting_since,
        last_order_id=conversation.last_order_id,
        version=conversation.version,
    )


def customer_out(identity: CustomerIdentity) -> CustomerOut:
    phone = identity.phone_enc
    return CustomerOut(
        id=identity.id,
        channel=identity.channel,
        display_name=identity.display_name,
        username=identity.username,
        locale=identity.locale,
        phone=phone,
        phone_masked=mask_phone(phone),
        blocked=identity.blocked_at is not None,
        contact_consent_at=identity.contact_consent_at,
    )


def allowed_actions(actor: ActorContext, conversation: Conversation) -> list[ConversationAction]:
    p = actor.permissions
    in_scope = is_supervisor(actor) or conversation.assignee_membership_id in (None, actor.membership_id)
    actions: list[ConversationAction] = []
    if not in_scope:
        return ["ASSIGN"] if perm.CONVERSATION_ASSIGN in p else []
    mine_human = (
        conversation.speaker_mode == "HUMAN" and conversation.assignee_membership_id == actor.membership_id
    )
    if perm.CONVERSATION_TAKEOVER in p and conversation.status != "RESOLVED" and not mine_human:
        actions.append("TAKE")
    if perm.CONVERSATION_REPLY in p:
        actions.append("REPLY")
    if perm.CONVERSATION_ASSIGN in p:
        actions.append("ASSIGN")
    if perm.CONVERSATION_RESOLVE in p and conversation.status in RESOLVABLE:
        actions.append("RESOLVE")
    if perm.CONVERSATION_RESOLVE in p and conversation.status == "RESOLVED":
        actions.append("REOPEN")
    if "commerce.order.create_draft" in p:
        actions.append("CREATE_ORDER")
    if perm.CONVERSATION_VIEW in p:
        actions.append("NOTE")
    return actions


def detail_out(
    actor: ActorContext,
    conversation: Conversation,
    identity: CustomerIdentity,
    handoff: Handoff | None,
    unread: int,
    available: bool,
    assignee_name: str | None = None,
) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        channel=conversation.channel,
        channel_account_id=conversation.channel_account_id,
        channel_available=available,
        status=conversation.status,
        speaker_mode=conversation.speaker_mode,
        speaker_version=conversation.speaker_version,
        assignee_membership_id=conversation.assignee_membership_id,
        assignee_name=assignee_name,
        locale=conversation.locale,
        tags=list(conversation.tags or []),
        customer=customer_out(identity),
        message_seq=conversation.message_seq,
        staff_last_read_seq=conversation.staff_last_read_seq,
        unread_count=unread,
        last_message_at=conversation.last_message_at,
        waiting_since=conversation.waiting_since,
        first_staff_reply_at=conversation.first_staff_reply_at,
        resolved_at=conversation.resolved_at,
        last_order_id=conversation.last_order_id,
        open_handoff=HandoffOut(
            id=handoff.id,
            reason=handoff.reason,
            requested_by_type=handoff.requested_by_type,
            created_at=handoff.created_at,
        )
        if handoff
        else None,
        allowed_actions=allowed_actions(actor, conversation),
        version=conversation.version,
    )


async def messages_out(db: AsyncSession, files: FileService, messages: Sequence[Message]) -> list[MessageOut]:
    if not messages:
        return []
    shop_id = messages[0].shop_id
    attachments = (
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.shop_id == shop_id, Attachment.message_id.in_([m.id for m in messages]))
                .order_by(Attachment.created_at)
            )
        )
        .scalars()
        .all()
    )
    stored = await files.by_ids(db, shop_id, [a.file_id for a in attachments if a.file_id is not None])
    by_message: dict[UUID, list[AttachmentOut]] = {}
    for a in attachments:
        url, expires = (None, None)
        row = stored.get(a.file_id) if a.file_id else None
        if row is not None and a.status == "STORED":
            url, expires = files.url_for(row)
        by_message.setdefault(a.message_id, []).append(
            AttachmentOut(
                id=a.id,
                kind=a.kind,
                status=a.status,
                mime=a.mime,
                size_bytes=a.size_bytes,
                url=url,
                url_expires_at=expires,
                error_code=a.error_code,
            )
        )
    return [
        MessageOut(
            id=m.id,
            seq=m.seq,
            direction=m.direction,
            author_type=m.author_type,
            author_membership_id=m.author_membership_id,
            origin=m.origin,
            kind=m.kind,
            body=m.body,
            intent_hint=m.intent_hint,
            delivery_status=m.delivery_status,
            last_error_code=m.last_error_code,
            attempts=m.attempts,
            occurred_at=m.occurred_at,
            sent_at=m.sent_at,
            edited_at=m.edited_at,
            attachments=by_message.get(m.id, []),
        )
        for m in messages
    ]
