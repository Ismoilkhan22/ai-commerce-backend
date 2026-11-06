"""Instagram izohlari API kontraktlari (`/api/v1/shop/instagram/*`, frontend `ig-comments.ts` bilan mos)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.messaging.models.ig import POST_PRODUCTS_MAX

IgTrigger = Literal["PLUS", "PRICE_QUESTION", "NONE"]
IgCommentStatus = Literal["RECEIVED", "CLASSIFIED", "CLASSIFY_SKIPPED", "DELETED"]
IgSentiment = Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "SPAM", "UNDETERMINED"]
IgSentimentSource = Literal["AI", "STAFF"]
IgReplyStatus = Literal["DRAFT", "QUEUED", "SENDING", "SENT", "FAILED", "SKIPPED", "DISCARDED"]
IgPeriod = Literal["7d", "30d", "90d"]
MediaType = Literal["IMAGE", "VIDEO", "CAROUSEL_ALBUM", "REELS"]


class IgSettingsOut(BaseModel):
    feature_enabled: bool  # flag yoqiq (o'chiq bo'lsa endpoint'lar 404)
    permission_granted: bool  # Meta izohlar ruxsati (scopes) bor
    auto_reply: bool
    sentiment: bool
    version: int  # kanal akkaunti versiyasi; Instagram ulanmagan bo'lsa 0


class IgSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_reply: bool | None = None
    sentiment: bool | None = None


class IgTemplateItem(BaseModel):
    template_key: str
    locale: Literal["uz", "ru", "en"]
    body: str
    default_body: str
    overridden: bool
    version: int | None
    required_variables: list[str]
    allowed_variables: list[str]


class IgTemplateList(BaseModel):
    items: list[IgTemplateItem]


class IgPostProductOut(BaseModel):
    product_id: UUID
    sku_id: UUID | None
    position: int
    title: str | None  # katalogda ko'rinmasa (yashirilgan, narxsiz) — None


class IgPostOut(BaseModel):
    id: UUID
    external_media_id: str
    media_type: MediaType | None
    permalink: str | None
    caption_excerpt: str | None
    thumbnail_url: str | None
    posted_at: datetime | None
    auto_reply_enabled: bool
    comment_count: int
    products: list[IgPostProductOut]
    version: int


class IgPostPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_reply_enabled: bool


class IgPostProductsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID] = Field(max_length=POST_PRODUCTS_MAX)


class IgAutoReplyOut(BaseModel):
    status: IgReplyStatus
    skip_reason: str | None
    last_error_code: str | None
    sent_at: datetime | None


class IgCommentOut(BaseModel):
    id: UUID
    post_id: UUID
    author_username: str | None
    body: str | None
    commented_at: datetime
    trigger: IgTrigger
    status: IgCommentStatus
    sentiment: IgSentiment | None
    sentiment_source: IgSentimentSource | None
    conversation_id: UUID | None
    auto_reply: IgAutoReplyOut | None


class IgPage[T](BaseModel):
    items: list[T]
    has_more: bool
    next_cursor: str | None


class IgSentimentSummaryOut(BaseModel):
    period: IgPeriod
    positive: int
    neutral: int
    negative: int
    spam: int
    undetermined: int
