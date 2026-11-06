"""Shop paneli: Instagram izohlari — `/api/v1/shop/instagram/*` (DEC-148, frontend `ig-comments.ts`).

Hammasi Instagram feature flag ostida (`FEATURE_CHANNEL_INSTAGRAM_DM`): flag o'chiq bo'lsa — 404, tokensiz ham
(endpoint "yo'qdek"). Ko'rish — `messaging.instagram.view` (ega, menejer, operator); sozlama, shablon va
post ↔ mahsulot — `messaging.instagram.manage` (ega, menejer).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.domains.messaging import permissions as perm
from app.domains.messaging.ig_schemas import (
    IgCommentOut,
    IgPage,
    IgPeriod,
    IgPostOut,
    IgPostPatch,
    IgPostProductsIn,
    IgSentimentSummaryOut,
    IgSettingsOut,
    IgSettingsPatch,
    IgTemplateItem,
    IgTemplateList,
)
from app.domains.messaging.providers import MessagingServices, messaging_services
from app.platform.notifications.schemas import MessageTemplateIn, TemplateLocale
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.errors.base import NotFoundError
from app.shared.http import etag, require_if_match

Messaging = Annotated[MessagingServices, Depends(messaging_services)]


def require_instagram_flag(svc: Messaging) -> None:
    if not svc.config.instagram_enabled:
        raise NotFoundError("Not found")


router = APIRouter(
    prefix="/instagram", tags=["instagram_comments"], dependencies=[Depends(require_instagram_flag)]
)

IfMatch = Annotated[int, Depends(require_if_match)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.INSTAGRAM_VIEW))]
CanManage = Annotated[RequestContext, Depends(require_permission(perm.INSTAGRAM_MANAGE))]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=512)]


@router.get("/settings", response_model=IgSettingsOut)
async def get_settings(response: Response, ctx: CanView, svc: Messaging) -> IgSettingsOut:
    out = await svc.ig.panel.settings(ctx.db, ctx.actor)
    response.headers["ETag"] = etag(out.version)
    return out


@router.patch("/settings", response_model=IgSettingsOut)
async def patch_settings(
    body: IgSettingsPatch, response: Response, ctx: CanManage, svc: Messaging, version: IfMatch
) -> IgSettingsOut:
    """Avtomatik javob va kayfiyat tahlilini yoqish/o'chirish (kanal akkaunti sozlamasi)."""
    out = await svc.ig.panel.patch_settings(ctx.db, ctx.actor, version, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("/templates", response_model=IgTemplateList)
async def list_templates(ctx: CanView, svc: Messaging) -> IgTemplateList:
    return await svc.ig.panel.list_templates(ctx.db, ctx.actor)


@router.put("/templates/{template_key}/{locale}", response_model=IgTemplateItem)
async def save_template(
    template_key: str, locale: TemplateLocale, body: MessageTemplateIn, ctx: CanManage, svc: Messaging
) -> IgTemplateItem:
    svc.ig.panel.check_template_key(template_key)
    saved = await svc.ig.panel.templates.save(ctx.db, ctx.actor, template_key, locale, body.body)
    return IgTemplateItem(**saved.model_dump())


@router.delete("/templates/{template_key}/{locale}", response_model=IgTemplateItem)
async def reset_template(
    template_key: str, locale: TemplateLocale, ctx: CanManage, svc: Messaging
) -> IgTemplateItem:
    """Standartga qaytarish."""
    svc.ig.panel.check_template_key(template_key)
    reset = await svc.ig.panel.templates.reset(ctx.db, ctx.actor, template_key, locale)
    return IgTemplateItem(**reset.model_dump())


@router.get("/posts", response_model=IgPage[IgPostOut])
async def list_posts(
    ctx: CanView, svc: Messaging, limit: Limit = 20, cursor: Cursor = None
) -> IgPage[IgPostOut]:
    return await svc.ig.panel.list_posts(ctx.db, ctx.actor, limit=limit, cursor=cursor)


@router.patch("/posts/{post_id}", response_model=IgPostOut)
async def patch_post(
    post_id: UUID, body: IgPostPatch, response: Response, ctx: CanManage, svc: Messaging, version: IfMatch
) -> IgPostOut:
    """Postda avtomatik javobni yoqish/o'chirish (konkurs postida o'chiriladi)."""
    out = await svc.ig.panel.set_auto_reply(ctx.db, ctx.actor, post_id, version, body.auto_reply_enabled)
    response.headers["ETag"] = etag(out.version)
    return out


@router.put("/posts/{post_id}/products", response_model=IgPostOut)
async def put_post_products(
    post_id: UUID,
    body: IgPostProductsIn,
    response: Response,
    ctx: CanManage,
    svc: Messaging,
    version: IfMatch,
) -> IgPostOut:
    """Post ↔ katalog mahsuloti (ko'pi bilan 5 ta). Narx faqat shu bog'lanishdan aytiladi (BL-038)."""
    out = await svc.ig.panel.set_products(ctx.db, ctx.actor, post_id, version, body.product_ids)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("/comments", response_model=IgPage[IgCommentOut])
async def list_comments(
    ctx: CanView,
    svc: Messaging,
    filter_: Annotated[str, Query(alias="filter", max_length=32)] = "all",
    post_id: UUID | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
) -> IgPage[IgCommentOut]:
    """`filter`: all | plus | price | negative | unclassified (katta-kichik harf farqsiz)."""
    return await svc.ig.panel.list_comments(
        ctx.db, ctx.actor, filter_=filter_, post_id=post_id, limit=limit, cursor=cursor
    )


@router.get("/sentiment-summary", response_model=IgSentimentSummaryOut)
async def sentiment_summary(ctx: CanView, svc: Messaging, period: IgPeriod = "7d") -> IgSentimentSummaryOut:
    return await svc.ig.panel.sentiment_summary(ctx.db, ctx.actor, period)
