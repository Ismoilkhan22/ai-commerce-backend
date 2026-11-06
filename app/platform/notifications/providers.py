"""platform/notifications servislari: bir marta yaratiladi (main.py) va app.state'dan olinadi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.platform.notifications.services.delivery import TelegramDelivery
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import TaskService
from app.platform.notifications.services.telegram_link import BotConfig, TelegramLinkService
from app.platform.notifications.telegram import TelegramSender


@dataclass(frozen=True)
class NotificationServices:
    notifications: NotificationService
    tasks: TaskService
    delivery: TelegramDelivery
    telegram_link: TelegramLinkService
    sender: TelegramSender
    webhook_secret: str | None
    customer_templates: CustomerTemplateService


def build_notification_services(
    sender: TelegramSender, *, bot_username: str | None, bot_configured: bool, webhook_secret: str | None
) -> NotificationServices:
    return NotificationServices(
        notifications=NotificationService(),
        tasks=TaskService(),
        delivery=TelegramDelivery(sender),
        telegram_link=TelegramLinkService(BotConfig(bot_username, bot_configured)),
        sender=sender,
        webhook_secret=webhook_secret,
        customer_templates=CustomerTemplateService(),
    )


def notification_services(request: Request) -> NotificationServices:
    return request.app.state.notifications  # type: ignore[no-any-return]


def from_state(state: Any) -> NotificationServices:
    """Fon ishlari va tinglovchilar uchun (app.state yoki worker holati)."""
    return state.notifications  # type: ignore[no-any-return]
