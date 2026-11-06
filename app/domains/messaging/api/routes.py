"""Shop paneli: yagona inbox — `/api/v1/shop/conversations/*` (S2-03, M10, 10 §6.4).

Operator (SALES) — o'ziga biriktirilgan va biriktirilmagan navbat; ega va menejer — hammasi. Javob
idempotent (`Idempotency-Key`); holatni o'zgartiradigan amallar — `If-Match` bilan.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BeforeValidator

from app.domains.messaging import permissions as perm
from app.domains.messaging.providers import MessagingServices, messaging_services
from app.domains.messaging.schemas import (
    Channel,
    ConversationAssignIn,
    ConversationCounts,
    ConversationList,
    ConversationOrderIn,
    ConversationOut,
    ConversationStatus,
    LinkOrderIn,
    MessageList,
    MessageOut,
    NoteIn,
    NoteList,
    NoteOut,
    OrderRefList,
    OrderRefOut,
    ReadIn,
    ReplyIn,
    TagsIn,
)
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.errors.base import ForbiddenError
from app.shared.http import etag, require_if_match, set_location, split_commas
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(prefix="/conversations", tags=["messaging"])

Messaging = Annotated[MessagingServices, Depends(messaging_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.CONVERSATION_VIEW))]
CanReply = Annotated[RequestContext, Depends(require_permission(perm.CONVERSATION_REPLY))]
CanTake = Annotated[RequestContext, Depends(require_permission(perm.CONVERSATION_TAKEOVER))]
CanAssign = Annotated[RequestContext, Depends(require_permission(perm.CONVERSATION_ASSIGN))]
CanResolve = Annotated[RequestContext, Depends(require_permission(perm.CONVERSATION_RESOLVE))]
ORDER_CREATE = "commerce.order.create_draft"


def _etag(response: Response, out: ConversationOut) -> ConversationOut:
    response.headers["ETag"] = etag(out.version)
    return out


# ------------------------------------------------------------------ o'qish
@router.get("", response_model=ConversationList)
async def list_conversations(
    ctx: CanView,
    svc: Messaging,
    status_: Annotated[
        list[ConversationStatus] | None, BeforeValidator(split_commas), Query(alias="status")
    ] = None,
    channel: Channel | None = None,
    assigned: Annotated[
        str | None, Query(max_length=40, description='"me", "unassigned" yoki xodim ID')
    ] = None,
    unread: Annotated[bool, Query(description="Faqat o'qilmagan kiruvchi xabari borlar")] = False,
    tag: Annotated[str | None, Query(max_length=32)] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Xaridor ismi, @username yoki telefon")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> ConversationList:
    """Inbox: oxirgi xabar bo'yicha (yangisi tepada). Operator — o'ziniki va biriktirilmagan navbat."""
    return await svc.inbox.list_conversations(
        ctx.db,
        ctx.actor,
        statuses=list(status_ or []),
        channel=channel,
        assigned=assigned,
        unread=unread,
        tag=tag,
        q=q,
        cursor=cursor,
        limit=limit,
    )


@router.get("/counts", response_model=ConversationCounts)
async def conversation_counts(ctx: CanView, svc: Messaging) -> ConversationCounts:
    return await svc.inbox.counts(ctx.db, ctx.actor)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: UUID, response: Response, ctx: CanView, svc: Messaging
) -> ConversationOut:
    """Suhbat kartochkasi: xaridor (telefon to'liq), ochiq uzatish, qaysi tugmalar ko'rinadi."""
    return _etag(response, await svc.inbox.detail(ctx.db, ctx.actor, conversation_id))


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: UUID,
    ctx: CanView,
    svc: Messaging,
    before_seq: Annotated[int | None, Query(ge=1, description="Eskiroqlar (yuqoriga aylantirish)")] = None,
    after_seq: Annotated[int | None, Query(ge=0, description="Yangilari (realtime signalidan keyin)")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MessageList:
    """Lenta — `seq` bo'yicha o'sish tartibida. Biriktirma — 5 daqiqalik imzoli havola."""
    return await svc.inbox.messages(
        ctx.db, ctx.actor, conversation_id, before_seq=before_seq, after_seq=after_seq, limit=limit
    )


# ------------------------------------------------------------------ javob va holat
@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def reply(
    conversation_id: UUID,
    body: ReplyIn,
    request: Request,
    response: Response,
    ctx: CanReply,
    svc: Messaging,
    key: IdemKey,
) -> Any:
    """Operator javobi: suhbat hali uniki bo'lmasa — oladi (AI javobi endi yuborilmaydi). Xabar navbatga
    (`QUEUED`), fon vazifasi kanalga yuboradi; yuborilmasa — `FAILED`, xodimga vazifa."""

    async def replay(saved: Any) -> MessageOut:
        items = await svc.inbox.messages(
            ctx.db, ctx.actor, conversation_id, before_seq=None, after_seq=int(saved["seq"]) - 1, limit=1
        )
        return items.items[0]

    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "messaging.reply",
        key,
        {"conversation_id": str(conversation_id), **body.model_dump(mode="json")},
        lambda: svc.inbox.reply(
            ctx.db,
            ctx.actor,
            conversation_id,
            body=body.body,
            attachment_file_id=body.attachment_file_id,
            idempotency_key=key,
        ),
        stored=lambda created: {"id": str(created.id), "seq": created.seq},
        on_replay=replay,
        status=status.HTTP_201_CREATED,
    )
    set_location(request, response, "list_messages", conversation_id=conversation_id)
    return out


@router.post("/{conversation_id}/take", response_model=ConversationOut)
async def take_conversation(
    conversation_id: UUID, response: Response, ctx: CanTake, svc: Messaging, version: IfMatch
) -> ConversationOut:
    """ "Suhbatni olish": operator javob beradi, AI yoza olmaydi (speaker +1, TC-009)."""
    return _etag(response, await svc.inbox.take(ctx.db, ctx.actor, conversation_id, version))


@router.post("/{conversation_id}/resume-ai", response_model=ConversationOut)
async def resume_ai(
    conversation_id: UUID, response: Response, ctx: CanTake, svc: Messaging, version: IfMatch
) -> ConversationOut:
    """ "AI'ga qaytarish" (6b): suhbat yana AI navbatida (speaker AI, versiya +1). AI shu shopda javob
    bermasa — 409 INVALID_STATE_TRANSITION (`reason`)."""
    return _etag(response, await svc.inbox.resume_ai(ctx.db, ctx.actor, conversation_id, version))


@router.post("/{conversation_id}/assign", response_model=ConversationOut)
async def assign_conversation(
    conversation_id: UUID,
    body: ConversationAssignIn,
    response: Response,
    ctx: CanAssign,
    svc: Messaging,
    version: IfMatch,
) -> ConversationOut:
    """Ega yoki menejer suhbatni operatorga beradi (yoki boshqasiga o'tkazadi)."""
    return _etag(
        response, await svc.inbox.assign(ctx.db, ctx.actor, conversation_id, version, body.membership_id)
    )


@router.post("/{conversation_id}/resolve", response_model=ConversationOut)
async def resolve_conversation(
    conversation_id: UUID, response: Response, ctx: CanResolve, svc: Messaging, version: IfMatch
) -> ConversationOut:
    return _etag(response, await svc.inbox.resolve(ctx.db, ctx.actor, conversation_id, version))


@router.post("/{conversation_id}/reopen", response_model=ConversationOut)
async def reopen_conversation(
    conversation_id: UUID, response: Response, ctx: CanResolve, svc: Messaging, version: IfMatch
) -> ConversationOut:
    return _etag(response, await svc.inbox.reopen(ctx.db, ctx.actor, conversation_id, version))


@router.post("/{conversation_id}/read", response_model=ConversationOut)
async def mark_conversation_read(
    conversation_id: UUID, body: ReadIn, response: Response, ctx: CanView, svc: Messaging
) -> ConversationOut:
    """O'qildi — shu `seq` gacha (faqat oshadi). Takrorlash xavfsiz."""
    return _etag(response, await svc.inbox.mark_read(ctx.db, ctx.actor, conversation_id, body.seq))


@router.put("/{conversation_id}/tags", response_model=ConversationOut)
async def set_conversation_tags(
    conversation_id: UUID, body: TagsIn, response: Response, ctx: CanReply, svc: Messaging, version: IfMatch
) -> ConversationOut:
    return _etag(response, await svc.inbox.set_tags(ctx.db, ctx.actor, conversation_id, version, body.tags))


# ------------------------------------------------------------------ izohlar
@router.get("/{conversation_id}/notes", response_model=NoteList)
async def list_conversation_notes(conversation_id: UUID, ctx: CanView, svc: Messaging) -> NoteList:
    return await svc.inbox.notes(ctx.db, ctx.actor, conversation_id)


@router.post("/{conversation_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def add_conversation_note(
    conversation_id: UUID, body: NoteIn, request: Request, response: Response, ctx: CanView, svc: Messaging
) -> NoteOut:
    """Ichki izoh — xaridorga ko'rinmaydi."""
    note = await svc.inbox.add_note(ctx.db, ctx.actor, conversation_id, body.body)
    set_location(request, response, "list_conversation_notes", conversation_id=conversation_id)
    return note


# ------------------------------------------------------------------ buyurtma
@router.get("/{conversation_id}/orders", response_model=OrderRefList)
async def list_conversation_orders(conversation_id: UUID, ctx: CanView, svc: Messaging) -> OrderRefList:
    return await svc.inbox.orders_of(ctx.db, ctx.actor, conversation_id)


@router.post("/{conversation_id}/orders", response_model=OrderRefOut, status_code=status.HTTP_201_CREATED)
async def create_conversation_order(
    conversation_id: UUID,
    body: ConversationOrderIn,
    request: Request,
    response: Response,
    ctx: CanView,
    svc: Messaging,
    key: IdemKey,
) -> Any:
    """Suhbatdan buyurtma qoralamasi (xaridor ismi, telefoni, tili — suhbatdan). Holat xabarlari xaridorga
    shu kanal orqali ketadi (S4-06). Ruxsat: `commerce.order.create_draft`."""
    if ORDER_CREATE not in ctx.actor.permissions:
        raise ForbiddenError("Permission denied", permission=ORDER_CREATE)
    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "messaging.conversation_order",
        key,
        {"conversation_id": str(conversation_id), **body.model_dump(mode="json")},
        lambda: svc.inbox.create_order(ctx.db, ctx.actor, conversation_id, body),
        status=status.HTTP_201_CREATED,
    )
    order_id = out.id if isinstance(out, OrderRefOut) else out["id"]
    set_location(request, response, "get_order", order_id=order_id)
    return out


@router.post("/{conversation_id}/orders/link", response_model=OrderRefOut)
async def link_conversation_order(
    conversation_id: UUID, body: LinkOrderIn, ctx: CanView, svc: Messaging, key: IdemKey
) -> Any:
    """Mavjud buyurtmani suhbatga bog'lash — keyingi holat xabarlari shu kanal orqali. Boshqa suhbatga
    bog'langan buyurtma — 409 `ORDER_LINKED_ELSEWHERE`; ko'chirish `relink` + `expected_version` bilan."""
    if ORDER_CREATE not in ctx.actor.permissions:
        raise ForbiddenError("Permission denied", permission=ORDER_CREATE)
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "messaging.conversation_order_link",
        key,
        {"conversation_id": str(conversation_id), **body.model_dump(mode="json")},
        lambda: svc.inbox.link_order(
            ctx.db,
            ctx.actor,
            conversation_id,
            body.order_id,
            relink=body.relink,
            expected_version=body.expected_version,
        ),
    )
