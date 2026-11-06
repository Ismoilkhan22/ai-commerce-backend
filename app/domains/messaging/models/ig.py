"""messaging: Instagram izohlari (db/instagram_comments.dbml, DEC-132, DEC-148).

5 jadval: postlar, post ↔ mahsulot, izohlar, kayfiyat tarixi, izohga javoblar. Hammasi shop konteksti bo'yicha
RLS (FORCE). Izoh matni va username — shaxsiy ma'lumot: event'ga va hisobotga tushmaydi, matn `DELETED` da
tozalanadi, 12 oydan keyin o'chiriladi. Narx saqlanmaydi: javob paytida katalogdan olinadi (BL-038).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

SCHEMA = "messaging"
MEDIA_TYPES = ("IMAGE", "VIDEO", "CAROUSEL_ALBUM", "REELS")
COMMENT_TRIGGERS = ("PLUS", "PRICE_QUESTION", "NONE")
COMMENT_STATUSES = ("RECEIVED", "CLASSIFIED", "CLASSIFY_SKIPPED", "DELETED")
SENTIMENTS = ("POSITIVE", "NEGATIVE", "NEUTRAL", "SPAM", "UNDETERMINED")
SENTIMENT_SOURCES = ("AI", "STAFF")
REPLY_KINDS = ("PRIVATE_AUTO", "PRIVATE_STAFF", "PUBLIC_STAFF")
REPLY_STATUSES = ("DRAFT", "QUEUED", "SENDING", "SENT", "FAILED", "SKIPPED", "DISCARDED")
SKIP_REASONS = (
    "FLAG_OFF",
    "AUTO_REPLY_OFF",
    "POST_AUTO_REPLY_OFF",
    "WINDOW_EXPIRED",
    "AUTHOR_ALREADY_REPLIED",
    "OWN_ACCOUNT",
    "CHANNEL_DISCONNECTED",
    "COMMENT_DELETED",
)
POST_PRODUCTS_MAX = 5


def _fk(columns: list[str], table: str, *, name: str | None = None, ondelete: str = "RESTRICT") -> Any:
    return ForeignKeyConstraint(
        columns,
        [f"{SCHEMA}.{table}.{c}" for c in ("shop_id", "id")],
        name=name,
        ondelete=ondelete,
    )


class IgPost(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Shop posti: birinchi izoh kelganda yaratiladi, media ma'lumoti keyin arq vazifasida olinadi."""

    __tablename__ = "ig_posts"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "channel_account_id", "external_media_id"),
        Index("ix_ig_posts_shop_id_posted_at", "shop_id", "posted_at"),
        _fk(["shop_id", "channel_account_id"], "channel_accounts"),
        CheckConstraint(f"media_type IS NULL OR media_type IN {MEDIA_TYPES}", name="media_type"),
        CheckConstraint("comment_count >= 0", name="comment_count"),
        {"schema": SCHEMA},
    )

    channel_account_id: Mapped[UUID]
    external_media_id: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(Text)
    permalink: Mapped[str | None] = mapped_column(Text)
    caption_excerpt: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    auto_reply_disabled_by: Mapped[UUID | None]  # platform.memberships.id
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class IgPostProduct(ShopScopedMixin, Base):
    """Post ↔ katalog mahsuloti (FK'siz — catalog boshqa schema). Ko'pi bilan 5 ta."""

    __tablename__ = "ig_post_products"
    __table_args__ = (
        PrimaryKeyConstraint("shop_id", "post_id", "product_id"),
        _fk(["shop_id", "post_id"], "ig_posts", ondelete="CASCADE"),
        CheckConstraint(f"position >= 0 AND position < {POST_PRODUCTS_MAX}", name="position"),
        {"schema": SCHEMA},
    )

    post_id: Mapped[UUID]
    product_id: Mapped[UUID]
    sku_id: Mapped[UUID | None]
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    linked_by: Mapped[UUID]  # platform.memberships.id — faqat xodim bog'laydi, AI rasmdan taxmin qilmaydi
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IgComment(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "ig_comments"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "channel_account_id", "external_comment_id"),
        Index("ix_ig_comments_shop_id_post_id_commented_at", "shop_id", "post_id", "commented_at"),
        Index("ix_ig_comments_shop_id_sentiment_commented_at", "shop_id", "sentiment", "commented_at"),
        Index("ix_ig_comments_shop_id_author_post", "shop_id", "author_external_id", "post_id"),
        Index("ix_ig_comments_shop_id_commented_at", "shop_id", "commented_at"),
        _fk(["shop_id", "post_id"], "ig_posts"),
        _fk(["shop_id", "channel_account_id"], "channel_accounts"),
        ForeignKeyConstraint(
            ["shop_id", "sentiment_id"],
            [f"{SCHEMA}.ig_comment_sentiments.shop_id", f"{SCHEMA}.ig_comment_sentiments.id"],
            name="fk_ig_comments_sentiment",
            use_alter=True,
        ),
        CheckConstraint(f"trigger IN {COMMENT_TRIGGERS}", name="trigger"),
        CheckConstraint(f"status IN {COMMENT_STATUSES}", name="status"),
        CheckConstraint(f"sentiment IS NULL OR sentiment IN {SENTIMENTS}", name="sentiment"),
        CheckConstraint(
            f"sentiment_source IS NULL OR sentiment_source IN {SENTIMENT_SOURCES}", name="sentiment_source"
        ),
        {"schema": SCHEMA},
    )

    channel_account_id: Mapped[UUID]
    post_id: Mapped[UUID]
    external_comment_id: Mapped[str] = mapped_column(Text)
    parent_external_comment_id: Mapped[str | None] = mapped_column(Text)
    author_external_id: Mapped[str] = mapped_column(Text)
    author_username: Mapped[str | None] = mapped_column(Text)  # PII: panelda ko'rinadi, event'ga tushmaydi
    is_own_account: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    body: Mapped[str | None] = mapped_column(Text)  # at rest, 12 oy; DELETED da tozalanadi
    commented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="RECEIVED")
    trigger: Mapped[str] = mapped_column(Text, server_default="NONE")
    sentiment: Mapped[str | None] = mapped_column(Text)
    sentiment_source: Mapped[str | None] = mapped_column(Text)
    sentiment_id: Mapped[UUID | None]
    conversation_id: Mapped[UUID | None]  # xaridor Direct'da javob yozsa (keyingi qadam)
    customer_identity_id: Mapped[UUID | None]
    provider_event_id: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pii_erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IgCommentSentiment(IdMixin, ShopScopedMixin, Base):
    """Kayfiyat tarixi (faqat qo'shiladi): AI bahosi va xodim tuzatishlari."""

    __tablename__ = "ig_comment_sentiments"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index(
            "ix_ig_comment_sentiments_shop_id_comment_id_created_at", "shop_id", "comment_id", "created_at"
        ),
        _fk(["shop_id", "comment_id"], "ig_comments", ondelete="CASCADE"),
        CheckConstraint(f"source IN {SENTIMENT_SOURCES}", name="source"),
        CheckConstraint(f"sentiment IN {SENTIMENTS}", name="sentiment"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"),
        {"schema": SCHEMA},
    )

    comment_id: Mapped[UUID]
    source: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    raw_label: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    ai_usage_id: Mapped[UUID | None]  # platform.ai_usage.id (COMMENT_CLASSIFY) — FK'siz
    staff_membership_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IgCommentReply(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Izohga javob: Direct'ga avtomatik (Private Reply), xodim javobi, ommaviy qoralama.
    `messages` ga yozilmaydi: Private Reply paytida xaridorning Direct id'si noma'lum."""

    __tablename__ = "ig_comment_replies"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "intent_key"),
        # Bir izohga bitta Direct xabar (Meta qoidasi)
        Index(
            "uq_ig_comment_replies_one_private",
            "shop_id",
            "comment_id",
            unique=True,
            postgresql_where=text(
                "kind IN ('PRIVATE_AUTO', 'PRIVATE_STAFF') "
                "AND status NOT IN ('SKIPPED', 'DISCARDED', 'FAILED')"
            ),
        ),
        Index("ix_ig_comment_replies_shop_id_provider_message_id", "shop_id", "provider_message_id"),
        Index("ix_ig_comment_replies_shop_id_status_created_at", "shop_id", "status", "created_at"),
        Index("ix_ig_comment_replies_shop_id_comment_id", "shop_id", "comment_id"),
        _fk(["shop_id", "comment_id"], "ig_comments"),
        CheckConstraint(f"kind IN {REPLY_KINDS}", name="kind"),
        CheckConstraint(f"status IN {REPLY_STATUSES}", name="status"),
        CheckConstraint(f"skip_reason IS NULL OR skip_reason IN {SKIP_REASONS}", name="skip_reason"),
        CheckConstraint("attempts >= 0", name="attempts"),
        {"schema": SCHEMA},
    )

    comment_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    template_key: Mapped[str | None] = mapped_column(Text)
    template_version: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    skip_reason: Mapped[str | None] = mapped_column(Text)
    intent_key: Mapped[str] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    ai_draft: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    author_membership_id: Mapped[UUID | None]
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
