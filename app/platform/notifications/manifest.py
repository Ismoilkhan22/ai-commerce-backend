"""platform/notifications moduli: bildirishnomalar markazi, xodim vazifalari, platforma boti (S2-06, 20)."""

from __future__ import annotations

from app.platform.notifications.api.routes import router
from app.platform.notifications.api.webhook_routes import router as webhook_router
from app.platform.notifications.subscribers import deliver_to_platform_bot, notifications_cleanup
from app.shared.events.registry import ScheduledJob
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="notifications",
    schema_name="platform",
    routers={"shop": router, "webhooks": webhook_router},
    event_subscribers=[deliver_to_platform_bot],
    scheduled_jobs=[ScheduledJob("notifications_cleanup", notifications_cleanup, cron="15 3 * * *")],
)
