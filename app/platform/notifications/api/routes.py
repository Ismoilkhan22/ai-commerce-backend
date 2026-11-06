"""Shop paneli: bildirishnomalar markazi, vazifalar, xodim sozlamasi va platforma botiga ulanish (20, S2-06).

Har xodim faqat o'z bildirishnomalarini ko'radi. Vazifalar — `staff.task.view` (hamma rol); ega va
menejer filial doirasidagi hammasini, operator va omborchi o'ziniki va o'z roliga qo'yilganini.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.platform.notifications.providers import NotificationServices, notification_services
from app.platform.notifications.schemas import (
    MessageTemplateIn,
    MessageTemplateList,
    MessageTemplateOut,
    NotificationList,
    NotificationOut,
    NotificationSettingsIn,
    NotificationSettingsOut,
    TaskAssignIn,
    TaskList,
    TaskOut,
    TaskStatus,
    TelegramLinkCodeOut,
    TelegramLinkStatus,
    TemplateLocale,
    UnreadCount,
)
from app.platform.staff.infrastructure.guard import RequestContext, ShopContext, require_permission
from app.shared.http import etag, require_if_match
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(tags=["notifications"])

Services = Annotated[NotificationServices, Depends(notification_services)]
CanSeeTasks = Annotated[RequestContext, Depends(require_permission("staff.task.view"))]
CanAssignTasks = Annotated[RequestContext, Depends(require_permission("staff.task.assign"))]
# Xaridor matnlari — shop sozlamasi (ega o'zgartiradi, menejer ko'radi; 20 §5)
CanViewTemplates = Annotated[RequestContext, Depends(require_permission("shops.settings.view"))]
CanEditTemplates = Annotated[RequestContext, Depends(require_permission("shops.settings.edit"))]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
Limit = Annotated[int, Query(ge=1, le=100)]


# ------------------------------------------------------------------------------ bildirishnomalar
@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    ctx: ShopContext,
    svc: Services,
    unread: Annotated[bool, Query(description="Faqat o'qilmaganlar")] = False,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Limit = 25,
) -> NotificationList:
    return await svc.notifications.list(ctx.db, ctx.actor, unread_only=unread, cursor=cursor, limit=limit)


@router.get("/notifications/unread-count", response_model=UnreadCount)
async def unread_count(ctx: ShopContext, svc: Services) -> UnreadCount:
    return UnreadCount(unread_count=await svc.notifications.unread_count(ctx.db, ctx.actor))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: UUID, ctx: ShopContext, svc: Services) -> NotificationOut:
    """Tabiatan idempotent (o'qilgan bo'lsa — o'zgarmaydi), shuning uchun Idempotency-Key shart emas."""
    return await svc.notifications.mark_read(ctx.db, ctx.actor, notification_id)


@router.post("/notifications/read-all", response_model=UnreadCount)
async def mark_all_read(ctx: ShopContext, svc: Services) -> UnreadCount:
    await svc.notifications.mark_all_read(ctx.db, ctx.actor)
    return UnreadCount(unread_count=0)


# --------------------------------------------------------------------------------------- vazifalar
@router.get("/tasks", response_model=TaskList)
async def list_tasks(
    ctx: CanSeeTasks,
    svc: Services,
    status: Annotated[TaskStatus | None, Query()] = "OPEN",
    type: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Z_]+$")] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Limit = 25,
    assigned: Annotated[
        str | None, Query(max_length=36, description="me | unassigned | <membership_id>")
    ] = None,
) -> TaskList:
    return await svc.tasks.list(
        ctx.db, ctx.actor, status=status, type=type, cursor=cursor, limit=limit, assigned=assigned
    )


@router.post("/tasks/{task_id}/done", response_model=TaskOut)
async def mark_task_done(
    task_id: UUID, response: Response, ctx: CanSeeTasks, svc: Services, key: IdemKey, version: IfMatch
) -> Any:
    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"platform.task.done:{task_id}",
        key,
        {"version": version},
        lambda: svc.tasks.mark_done(ctx.db, ctx.actor, task_id, version),
    )
    response.headers["ETag"] = etag(int(result["version"] if isinstance(result, dict) else result.version))
    return result


@router.post("/tasks/{task_id}/assign", response_model=TaskOut)
async def assign_task(
    task_id: UUID,
    body: TaskAssignIn,
    response: Response,
    ctx: CanAssignTasks,
    svc: Services,
    key: IdemKey,
    version: IfMatch,
) -> Any:
    result = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"platform.task.assign:{task_id}",
        key,
        {"version": version, **body.model_dump(mode="json")},
        lambda: svc.tasks.assign(ctx.db, ctx.actor, task_id, version, body.membership_id),
    )
    response.headers["ETag"] = etag(int(result["version"] if isinstance(result, dict) else result.version))
    return result


# --------------------------------------------------------------------------------- o'z sozlamasi
@router.get("/me/notification-settings", response_model=NotificationSettingsOut)
async def get_settings(response: Response, ctx: ShopContext, svc: Services) -> NotificationSettingsOut:
    out = await svc.notifications.settings(ctx.db, ctx.actor)
    response.headers["ETag"] = etag(out.version)
    return out


@router.put("/me/notification-settings", response_model=NotificationSettingsOut)
async def save_settings(
    body: NotificationSettingsIn, response: Response, ctx: ShopContext, svc: Services, version: IfMatch
) -> NotificationSettingsOut:
    """Birinchi saqlash — `If-Match: "v0"`."""
    out = await svc.notifications.save_settings(ctx.db, ctx.actor, body, version)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("/me/telegram-link", response_model=TelegramLinkStatus)
async def telegram_link_status(ctx: ShopContext, svc: Services) -> TelegramLinkStatus:
    return await svc.telegram_link.status(ctx.db, ctx.actor)


@router.post("/me/telegram-link", response_model=TelegramLinkCodeOut, status_code=status.HTTP_201_CREATED)
async def create_telegram_link_code(
    request: Request, response: Response, ctx: ShopContext, svc: Services
) -> TelegramLinkCodeOut:
    """Bir martalik kod (10 daqiqa) — faqat shu javobda; har bosishda yangisi (eskisi o'z muddati bilan)."""
    out = await svc.telegram_link.create_code(ctx.db, ctx.actor)
    response.headers["Location"] = request.url_for("telegram_link_status").path
    response.headers["Cache-Control"] = "no-store"
    return out


@router.delete("/me/telegram-link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_telegram(ctx: ShopContext, svc: Services) -> None:
    await svc.telegram_link.unlink(ctx.db, ctx.actor)


# ------------------------------------------------------------------------------ xaridor matnlari (5b)
@router.get("/message-templates", response_model=MessageTemplateList)
async def list_message_templates(ctx: CanViewTemplates, svc: Services) -> MessageTemplateList:
    """Xaridorga yuboriladigan matnlar (buyurtma holati, ish vaqtidan tashqari): standart va shop matni."""
    return await svc.customer_templates.list(ctx.db, ctx.actor)


@router.put("/message-templates/{template_key}/{locale}", response_model=MessageTemplateOut)
async def save_message_template(
    template_key: str, locale: TemplateLocale, body: MessageTemplateIn, ctx: CanEditTemplates, svc: Services
) -> MessageTemplateOut:
    """Shop matni — yangi versiya. Majburiy o'zgaruvchi (`{order_number}`) qolishi shart, noma'lumi — rad."""
    return await svc.customer_templates.save(ctx.db, ctx.actor, template_key, locale, body.body)


@router.delete("/message-templates/{template_key}/{locale}", response_model=MessageTemplateOut)
async def reset_message_template(
    template_key: str, locale: TemplateLocale, ctx: CanEditTemplates, svc: Services
) -> MessageTemplateOut:
    """Standart matnga qaytarish."""
    return await svc.customer_templates.reset(ctx.db, ctx.actor, template_key, locale)
