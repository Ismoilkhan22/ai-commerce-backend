"""Shop paneli: Instagram izohlari (settings, shablonlar, postlar, izohlar, kayfiyat hisoboti).

Hamma narsa shu shop doirasida (RLS + `shop_id` filtri). Tahrirlar `If-Match` bilan (versiya) va audit'ga
yoziladi; izoh matni va username audit'ga tushmaydi. Post ↔ mahsulot: faqat xodim bog'laydi, faqat katalogda
ko'rinadigan (saytda chiqarilgan, narxi bor) mahsulot — AI rasmdan taxmin qilmaydi (BL-038).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.instagram import COMMENTS_SCOPE
from app.domains.messaging.common import MessagingConfig
from app.domains.messaging.ig_schemas import (
    IgAutoReplyOut,
    IgCommentOut,
    IgPage,
    IgPeriod,
    IgPostOut,
    IgPostProductOut,
    IgSentimentSummaryOut,
    IgSettingsOut,
    IgTemplateItem,
    IgTemplateList,
)
from app.domains.messaging.models.ig import (
    POST_PRODUCTS_MAX,
    IgComment,
    IgCommentReply,
    IgPost,
    IgPostProduct,
)
from app.domains.messaging.models.orm import ChannelAccount
from app.domains.messaging.services.channels import ChannelService
from app.domains.messaging.services.ig_common import comment_settings
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.errors.base import NotFoundError, ValidationError
from app.shared.http import check_version
from app.shared.pagination import decode_cursor, encode_cursor
from app.shared.types.actor import ActorContext

IG_TEMPLATE_KEYS = ("customer.ig_comment_price_reply", "customer.ig_comment_generic_reply")
POST = "messaging.ig_post"
SETTINGS = "messaging.ig_settings"
FILTERS = {
    "all": "ALL",
    "plus": "PLUS",
    "price": "PRICE_QUESTION",
    "price_question": "PRICE_QUESTION",
    "negative": "NEGATIVE",
    "unclassified": "UNCLASSIFIED",
}
PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _field(name: str, code: str, **params: Any) -> dict[str, Any]:
    return {"field": name, "code": code, "params": params}


class IgPanelService:
    def __init__(
        self,
        config: MessagingConfig,
        channels: ChannelService,
        audit: AuditService,
        templates: CustomerTemplateService,
        catalog: CatalogQueryPort | None,
    ) -> None:
        self.config = config
        self.channels = channels
        self.audit = audit
        self.templates = templates
        self.catalog = catalog

    # ------------------------------------------------------------------ settings
    async def settings(self, db: AsyncSession, actor: ActorContext) -> IgSettingsOut:
        assert actor.shop_id is not None
        return self._settings_out(await self.channels.active(db, actor.shop_id, "INSTAGRAM"))

    def _settings_out(self, account: ChannelAccount | None) -> IgSettingsOut:
        values = comment_settings(account)
        return IgSettingsOut(
            feature_enabled=self.config.instagram_enabled,
            permission_granted=bool(account and COMMENTS_SCOPE in (account.scopes or [])),
            auto_reply=values["auto_reply"],
            sentiment=values["sentiment"],
            version=account.version if account is not None else 0,
        )

    async def patch_settings(
        self, db: AsyncSession, actor: ActorContext, version: int, changes: dict[str, bool]
    ) -> IgSettingsOut:
        assert actor.shop_id is not None
        account = (
            await db.execute(
                select(ChannelAccount)
                .where(
                    ChannelAccount.shop_id == actor.shop_id,
                    ChannelAccount.channel == "INSTAGRAM",
                    ChannelAccount.status.in_(("PENDING", "CONNECTED", "DEGRADED")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None:
            raise NotFoundError("Instagram channel is not connected")
        check_version(account.version, version)
        granted = COMMENTS_SCOPE in (account.scopes or [])
        enabling = [name for name, value in changes.items() if value]
        if (
            enabling and not granted
        ):  # Meta izohlar ruxsati yo'q: yoqib bo'lmaydi (instagram_comments.md §7.2)
            raise ValidationError(
                "Instagram comments permission is missing",
                fields=[_field(enabling[0], "permission_missing")],
            )
        before = comment_settings(account)
        account.settings = {**(account.settings or {}), "comments": {**before, **changes}}
        await db.flush()
        await self.audit.record(
            db,
            action="messaging.instagram.settings_changed",
            entity_type=SETTINGS,
            entity_id=account.id,
            actor=actor,
            entity_version=account.version,
            diff={name: {"old": before[name], "new": value} for name, value in changes.items()},
        )
        return self._settings_out(account)

    # ------------------------------------------------------------------ shablonlar
    async def list_templates(self, db: AsyncSession, actor: ActorContext) -> IgTemplateList:
        listed = await self.templates.list(db, actor)
        return IgTemplateList(
            items=[
                IgTemplateItem(**item.model_dump())
                for item in listed.items
                if item.template_key in IG_TEMPLATE_KEYS
            ]
        )

    @staticmethod
    def check_template_key(key: str) -> None:
        if key not in IG_TEMPLATE_KEYS:
            raise NotFoundError("Template not found")

    # ------------------------------------------------------------------ postlar
    async def list_posts(
        self, db: AsyncSession, actor: ActorContext, *, limit: int, cursor: str | None
    ) -> IgPage[IgPostOut]:
        assert actor.shop_id is not None
        sort_at = func.coalesce(IgPost.posted_at, IgPost.created_at)
        query = select(IgPost).where(IgPost.shop_id == actor.shop_id)
        if cursor:
            at, last_id = _cursor(cursor)
            query = query.where(or_(sort_at < at, and_(sort_at == at, IgPost.id < last_id)))
        rows = (
            (await db.execute(query.order_by(sort_at.desc(), IgPost.id.desc()).limit(limit + 1)))
            .scalars()
            .all()
        )
        page = list(rows[:limit])
        outs = await self._posts_out(db, actor.shop_id, page)
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]
            next_cursor = encode_cursor(
                {"t": (last.posted_at or last.created_at).isoformat(), "id": str(last.id)}
            )
        return IgPage(items=outs, has_more=len(rows) > limit, next_cursor=next_cursor)

    async def set_auto_reply(
        self, db: AsyncSession, actor: ActorContext, post_id: UUID, version: int, enabled: bool
    ) -> IgPostOut:
        post = await self._post(db, actor, post_id, lock=True)
        check_version(post.version, version)
        if post.auto_reply_enabled != enabled:
            before = post.auto_reply_enabled
            post.auto_reply_enabled = enabled
            post.auto_reply_disabled_by = None if enabled else actor.membership_id
            await db.flush()
            await self.audit.record(
                db,
                action="messaging.instagram.post_auto_reply_changed",
                entity_type=POST,
                entity_id=post.id,
                actor=actor,
                entity_version=post.version,
                diff={"auto_reply_enabled": {"old": before, "new": enabled}},
            )
        return (await self._posts_out(db, post.shop_id, [post]))[0]

    async def set_products(
        self, db: AsyncSession, actor: ActorContext, post_id: UUID, version: int, product_ids: list[UUID]
    ) -> IgPostOut:
        post = await self._post(db, actor, post_id, lock=True)
        check_version(post.version, version)
        if len(set(product_ids)) != len(product_ids) or len(product_ids) > POST_PRODUCTS_MAX:
            raise ValidationError(
                "Product list is invalid",
                fields=[_field("product_ids", "invalid_list", max=POST_PRODUCTS_MAX)],
            )
        titles = await self._titles(db, post.shop_id, product_ids)
        missing = [str(pid) for pid in product_ids if titles.get(pid) is None]
        if missing:  # katalogda yo'q yoki ko'rinmaydi (chiqarilmagan/narxsiz): narx aytib bo'lmaydi
            raise ValidationError(
                "Product is not available", fields=[_field("product_ids", "product_not_found", ids=missing)]
            )
        old = {
            link.product_id
            for link in (
                await db.execute(
                    select(IgPostProduct).where(
                        IgPostProduct.shop_id == post.shop_id, IgPostProduct.post_id == post.id
                    )
                )
            ).scalars()
        }
        await db.execute(
            delete(IgPostProduct).where(
                IgPostProduct.shop_id == post.shop_id, IgPostProduct.post_id == post.id
            )
        )
        for index, product_id in enumerate(product_ids):
            db.add(
                IgPostProduct(
                    shop_id=post.shop_id,
                    post_id=post.id,
                    product_id=product_id,
                    position=index,
                    linked_by=actor.membership_id,
                )
            )
        post.updated_at = utcnow()  # versiya oshishi uchun (If-Match)
        await db.flush()
        await self.audit.record(
            db,
            action="messaging.instagram.post_products_changed",
            entity_type=POST,
            entity_id=post.id,
            actor=actor,
            entity_version=post.version,
            diff={"product_count": {"old": len(old), "new": len(product_ids)}},
        )
        return (await self._posts_out(db, post.shop_id, [post]))[0]

    async def _post(
        self, db: AsyncSession, actor: ActorContext, post_id: UUID, *, lock: bool = False
    ) -> IgPost:
        query = select(IgPost).where(IgPost.shop_id == actor.shop_id, IgPost.id == post_id)
        post = (await db.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
        if post is None:
            raise NotFoundError("Post not found")
        return post

    async def _titles(
        self, db: AsyncSession, shop_id: UUID, product_ids: list[UUID]
    ) -> dict[UUID, str | None]:
        titles: dict[UUID, str | None] = {}
        for product_id in dict.fromkeys(product_ids):
            detail = await self.catalog.public_product(db, shop_id, product_id) if self.catalog else None
            titles[product_id] = detail.title if detail is not None else None
        return titles

    async def _posts_out(self, db: AsyncSession, shop_id: UUID, posts: list[IgPost]) -> list[IgPostOut]:
        links = (
            (
                await db.execute(
                    select(IgPostProduct)
                    .where(IgPostProduct.shop_id == shop_id, IgPostProduct.post_id.in_([p.id for p in posts]))
                    .order_by(IgPostProduct.position)
                )
            )
            .scalars()
            .all()
            if posts
            else []
        )
        titles = await self._titles(db, shop_id, [link.product_id for link in links])
        return [
            IgPostOut(
                id=post.id,
                external_media_id=post.external_media_id,
                media_type=post.media_type,
                permalink=post.permalink,
                caption_excerpt=post.caption_excerpt,
                thumbnail_url=post.thumbnail_url,
                posted_at=post.posted_at,
                auto_reply_enabled=post.auto_reply_enabled,
                comment_count=post.comment_count,
                products=[
                    IgPostProductOut(
                        product_id=link.product_id,
                        sku_id=link.sku_id,
                        position=link.position,
                        title=titles.get(link.product_id),
                    )
                    for link in links
                    if link.post_id == post.id
                ],
                version=post.version,
            )
            for post in posts
        ]

    # ------------------------------------------------------------------ izohlar
    async def list_comments(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        filter_: str,
        post_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> IgPage[IgCommentOut]:
        assert actor.shop_id is not None
        mode = FILTERS.get(filter_.strip().lower())
        if mode is None:
            raise ValidationError("Filter is invalid", fields=[_field("filter", "invalid_value")])
        query = select(IgComment).where(IgComment.shop_id == actor.shop_id)
        if post_id is not None:
            query = query.where(IgComment.post_id == post_id)
        if mode in ("PLUS", "PRICE_QUESTION"):
            query = query.where(IgComment.trigger == mode)
        elif mode == "NEGATIVE":
            query = query.where(IgComment.sentiment == "NEGATIVE")
        elif mode == "UNCLASSIFIED":  # kayfiyati yo'q yoki "aniqlanmagan"; o'chirilgan emas
            query = query.where(
                IgComment.status != "DELETED",
                or_(IgComment.sentiment.is_(None), IgComment.sentiment == "UNDETERMINED"),
            )
        if cursor:
            at, last_id = _cursor(cursor)
            query = query.where(
                or_(IgComment.commented_at < at, and_(IgComment.commented_at == at, IgComment.id < last_id))
            )
        rows = (
            (
                await db.execute(
                    query.order_by(IgComment.commented_at.desc(), IgComment.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page = list(rows[:limit])
        replies = await self._auto_replies(db, actor.shop_id, [c.id for c in page])
        next_cursor = (
            encode_cursor({"t": page[-1].commented_at.isoformat(), "id": str(page[-1].id)})
            if len(rows) > limit and page
            else None
        )
        return IgPage(
            items=[_comment_out(c, replies.get(c.id)) for c in page],
            has_more=len(rows) > limit,
            next_cursor=next_cursor,
        )

    @staticmethod
    async def _auto_replies(
        db: AsyncSession, shop_id: UUID, comment_ids: list[UUID]
    ) -> dict[UUID, IgCommentReply]:
        if not comment_ids:
            return {}
        rows = (
            (
                await db.execute(
                    select(IgCommentReply)
                    .where(
                        IgCommentReply.shop_id == shop_id,
                        IgCommentReply.comment_id.in_(comment_ids),
                        IgCommentReply.kind == "PRIVATE_AUTO",
                    )
                    .order_by(IgCommentReply.created_at)
                )
            )
            .scalars()
            .all()
        )
        return {reply.comment_id: reply for reply in rows}  # oxirgisi (eng yangisi) qoladi

    async def sentiment_summary(
        self, db: AsyncSession, actor: ActorContext, period: IgPeriod
    ) -> IgSentimentSummaryOut:
        assert actor.shop_id is not None
        since = utcnow() - timedelta(days=PERIOD_DAYS[period])
        rows = (
            await db.execute(
                select(IgComment.sentiment, func.count())
                .where(
                    IgComment.shop_id == actor.shop_id,
                    IgComment.commented_at >= since,
                    IgComment.status != "DELETED",
                    IgComment.sentiment.is_not(None),
                )
                .group_by(IgComment.sentiment)
            )
        ).all()
        counts = {str(label): int(total) for label, total in rows}
        return IgSentimentSummaryOut(
            period=period,
            positive=counts.get("POSITIVE", 0),
            neutral=counts.get("NEUTRAL", 0),
            negative=counts.get("NEGATIVE", 0),
            spam=counts.get("SPAM", 0),
            undetermined=counts.get("UNDETERMINED", 0),
        )


def _cursor(cursor: str) -> tuple[datetime, UUID]:
    values = decode_cursor(cursor)
    try:
        return datetime.fromisoformat(str(values["t"])), UUID(str(values["id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError("Cursor is invalid", fields=[_field("cursor", "invalid_format")]) from exc


def _comment_out(comment: IgComment, reply: IgCommentReply | None) -> IgCommentOut:
    return IgCommentOut(
        id=comment.id,
        post_id=comment.post_id,
        author_username=comment.author_username,
        body=comment.body,
        commented_at=comment.commented_at,
        trigger=comment.trigger,
        status=comment.status,
        sentiment=comment.sentiment,
        sentiment_source=comment.sentiment_source,
        conversation_id=comment.conversation_id,
        auto_reply=IgAutoReplyOut(
            status=reply.status,
            skip_reason=reply.skip_reason,
            last_error_code=reply.last_error_code,
            sent_at=reply.sent_at,
        )
        if reply is not None
        else None,
    )
