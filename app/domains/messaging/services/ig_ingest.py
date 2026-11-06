"""Izoh webhook'i (DEC-148, instagram_comments.md §1): bitta tranzaksiyada dedup → post → izoh → qoida →
outbox.

Shop konteksti `ChannelService.by_external` da o'rnatilgan. Qoida (`ig_rules`) shu yerda — arzon va
deterministik; javob va kayfiyat keyin outbox tinglovchilarida (bir-birini kutmaydi). Post media ma'lumoti
(rasm, havola) webhook ichida olinmaydi — arq tinglovchisi `ig_post_fetch`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.instagram import InboundComment
from app.domains.messaging.ig_rules import NONE, classify_trigger
from app.domains.messaging.models.ig import IgComment, IgPost
from app.domains.messaging.models.orm import ChannelAccount, ProviderEvent
from app.domains.messaging.services.ig_common import EV_DELETED, EV_RECEIVED, emit_comment
from app.shared.clock import utcnow


@dataclass(frozen=True)
class IngestCommentResult:
    duplicate: bool
    comment_id: UUID | None = None


class IgIngestService:
    async def ingest(
        self, db: AsyncSession, account: ChannelAccount, inbound: InboundComment
    ) -> IngestCommentResult:
        shop_id = account.shop_id
        event_id = await db.scalar(
            insert(ProviderEvent)
            .values(
                shop_id=shop_id,
                channel_account_id=account.id,
                provider_event_id=inbound.provider_event_id[:200],
                kind="COMMENT",
                status="PROCESSED",
            )
            .on_conflict_do_nothing(index_elements=["shop_id", "channel_account_id", "provider_event_id"])
            .returning(ProviderEvent.id)
        )
        if event_id is None:
            return IngestCommentResult(duplicate=True)  # Meta qayta yubordi — hech narsa qilinmaydi (TC-010)
        event = await db.get(ProviderEvent, event_id)
        assert event is not None
        await db.execute(  # Core UPDATE: kanal `version` i har webhook'da oshmasin (If-Match)
            update(ChannelAccount).where(ChannelAccount.id == account.id).values(last_webhook_at=utcnow())
        )
        existing = (
            await db.execute(
                select(IgComment).where(
                    IgComment.shop_id == shop_id,
                    IgComment.channel_account_id == account.id,
                    IgComment.external_comment_id == inbound.external_comment_id,
                )
            )
        ).scalar_one_or_none()
        if inbound.removed:
            if existing is not None:
                event.ig_comment_id = existing.id
                await self._deleted(db, existing)
            return IngestCommentResult(duplicate=False, comment_id=existing.id if existing else None)
        if existing is not None:  # boshqa event id bilan o'sha izoh: qayta yaratilmaydi
            return IngestCommentResult(duplicate=True, comment_id=existing.id)
        post = await self._post(db, account, inbound)
        own = inbound.author_external_id == account.external_account_id
        has_body = bool(inbound.body and inbound.body.strip())
        comment = IgComment(
            shop_id=shop_id,
            channel_account_id=account.id,
            post_id=post.id,
            external_comment_id=inbound.external_comment_id,
            parent_external_comment_id=inbound.parent_external_comment_id,
            author_external_id=inbound.author_external_id,
            author_username=inbound.author_username,
            is_own_account=own,
            body=inbound.body if has_body else None,
            commented_at=inbound.occurred_at,
            # Shopning o'z javobi va matnsiz izoh qayta ishlanmaydi (kayfiyat ham, avtomatik javob ham yo'q)
            status="RECEIVED" if has_body and not own else "CLASSIFY_SKIPPED",
            trigger=NONE if own else classify_trigger(inbound.body),
            provider_event_id=inbound.provider_event_id[:200],
        )
        db.add(comment)
        await db.flush()
        event.ig_comment_id = comment.id
        # Core UPDATE: `version` oshmaydi — izoh kelishi panelning `If-Match` (post tahriri) ni buzmasin
        await db.execute(
            update(IgPost)
            .where(IgPost.shop_id == shop_id, IgPost.id == post.id)
            .values(comment_count=IgPost.comment_count + 1)
        )
        await emit_comment(
            db,
            comment,
            EV_RECEIVED,
            trigger=comment.trigger,
            has_content=has_body,
            posted_at=comment.commented_at,
        )
        return IngestCommentResult(duplicate=False, comment_id=comment.id)

    @staticmethod
    async def _post(db: AsyncSession, account: ChannelAccount, inbound: InboundComment) -> IgPost:
        values = {
            "shop_id": account.shop_id,
            "channel_account_id": account.id,
            "external_media_id": inbound.external_media_id[:100],
        }
        await db.execute(
            insert(IgPost)
            .values(**values, media_type=inbound.media_type)
            .on_conflict_do_nothing(index_elements=["shop_id", "channel_account_id", "external_media_id"])
        )
        post = (
            await db.execute(
                select(IgPost)
                .where(
                    IgPost.shop_id == account.shop_id,
                    IgPost.channel_account_id == account.id,
                    IgPost.external_media_id == values["external_media_id"],
                )
                .with_for_update()
            )
        ).scalar_one()
        if post.media_type is None and inbound.media_type is not None:
            post.media_type = inbound.media_type
        return post

    @staticmethod
    async def _deleted(db: AsyncSession, comment: IgComment) -> None:
        if comment.status == "DELETED":
            return
        # Matn va username darhol tozalanadi (instagram_comments.md §4)
        comment.status, comment.body, comment.author_username = "DELETED", None, None
        comment.deleted_at = utcnow()
        await db.flush()
        await emit_comment(db, comment, EV_DELETED)
