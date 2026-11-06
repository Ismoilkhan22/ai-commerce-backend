"""Instagram izohlari uchun umumiy: event nomlari, kanal sozlamasi (`settings.comments`), event yozish.

Event payload'ida izoh matni, username va narx YO'Q (instagram_comments.md §6). Kalit nomlari `forbidden_keys`
dan o'tishi kerak (`comment`, `text`, `name` so'zlari taqiqlangan) — shuning uchun izoh id'si `item_id`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import emit
from app.domains.messaging.models.ig import IgComment, IgCommentReply
from app.domains.messaging.models.orm import ChannelAccount
from app.shared.types.actor import ActorContext

IG_COMMENT = "messaging.ig_comment"
IG_REPLY = "messaging.ig_comment_reply"
EV_RECEIVED = "messaging.ig_comment.received"
EV_CLASSIFIED = "messaging.ig_comment.classified"
EV_REPLY_QUEUED = "messaging.ig_comment.reply_queued"
EV_REPLY_FINISHED = "messaging.ig_comment.reply_finished"
EV_DELETED = "messaging.ig_comment.deleted"
DEFAULT_COMMENT_SETTINGS: dict[str, bool] = {"auto_reply": True, "sentiment": True}


def comment_settings(account: ChannelAccount | None) -> dict[str, bool]:
    """`channel_accounts.settings.comments` — standart ikkalasi yoqiq (PII yo'q)."""
    raw = ((account.settings or {}).get("comments") if account is not None else None) or {}
    return {key: bool(raw.get(key, default)) for key, default in DEFAULT_COMMENT_SETTINGS.items()}


async def emit_comment(db: AsyncSession, comment: IgComment, event_type: str, **payload: Any) -> None:
    await emit(
        db,
        ActorContext.system(comment.shop_id),
        event_type=event_type,
        shop_id=comment.shop_id,
        aggregate_type=IG_COMMENT,
        aggregate_id=comment.id,
        aggregate_version=comment.version,
        payload={"item_id": comment.id, "post_id": comment.post_id, **payload},
    )


async def emit_reply(db: AsyncSession, reply: IgCommentReply, event_type: str, **payload: Any) -> None:
    await emit(
        db,
        ActorContext.system(reply.shop_id),
        event_type=event_type,
        shop_id=reply.shop_id,
        aggregate_type=IG_REPLY,
        aggregate_id=reply.id,
        aggregate_version=reply.version,
        payload={"item_id": reply.comment_id, "reply_id": reply.id, "kind": reply.kind, **payload},
    )


def as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None
