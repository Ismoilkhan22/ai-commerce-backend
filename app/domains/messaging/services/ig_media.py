"""Post media ma'lumoti (rasm, havola, sarlavha): birinchi izoh kelganda arq vazifasida (webhook ichida emas).

Tashqi chaqiruv tranzaksiyadan tashqarida. Meta javob bermasa `fetched_at` bo'sh qoladi — keyingi izohda yana
uriniladi. Rasm saqlanmaydi: Meta havolasi eskiradi, faqat ko'rsatiladi (instagram_comments.md §2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, update

from app.domains.messaging.common import ChannelAdapters
from app.domains.messaging.models.ig import IgPost
from app.domains.messaging.models.orm import ChannelAccount
from app.shared.clock import utcnow
from app.shared.db.session import Database

CAPTION_EXCERPT = 200


class IgMediaService:
    def __init__(self, adapters: ChannelAdapters) -> None:
        self.adapters = adapters

    async def fetch(self, database: Database, shop_id: UUID, post_id: UUID) -> str:
        async with database.transaction(shop_id) as db:
            post = await db.get(IgPost, post_id)
            if post is None or post.fetched_at is not None:
                return "skipped"
            account = await db.get(ChannelAccount, post.channel_account_id)
            if account is None or not account.token_enc or (account.settings or {}).get("fake"):
                return "skipped"
            token, media_id = account.token_enc, post.external_media_id
        info = await self.adapters.instagram.fetch_media(token, media_id)
        if info is None:
            return "unavailable"
        async with database.transaction(shop_id) as db:
            # Core UPDATE: `version` oshmaydi (media ma'lumoti xodim tahriri bilan to'qnashmasin)
            await db.execute(
                update(IgPost)
                .where(IgPost.shop_id == shop_id, IgPost.id == post_id)
                .values(
                    media_type=func.coalesce(info.media_type, IgPost.media_type),
                    permalink=info.permalink,
                    thumbnail_url=info.thumbnail_url,
                    posted_at=info.posted_at,
                    caption_excerpt=info.caption[:CAPTION_EXCERPT] if info.caption else None,
                    fetched_at=utcnow(),
                )
            )
        return "fetched"
