"""messaging domeni: shop paneli (inbox, kanallar), webhook'lar va sayt chati (5b, DEC-137)."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.messaging.api.channel_routes import router as channel_router
from app.domains.messaging.api.ig_routes import router as instagram_router
from app.domains.messaging.api.public_routes import router as chat_router
from app.domains.messaging.api.routes import router as inbox_router
from app.domains.messaging.api.webhook_routes import router as webhook_router
from app.domains.messaging.jobs import MESSAGING_JOBS
from app.domains.messaging.permissions import MESSAGING_PERMISSIONS, MESSAGING_ROLE_GRANTS
from app.domains.messaging.state_machine import CHANNEL_RULES, CONVERSATION_RULES
from app.domains.messaging.subscribers import (
    attachment_fetch,
    channel_send,
    ig_comment_classify,
    ig_comment_reply,
    ig_post_fetch,
    ig_reply_send,
    order_status_notify,
    support_case_notify,
)
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(inbox_router)
shop_router.include_router(channel_router)
shop_router.include_router(instagram_router)

DOMAIN_MANIFEST = DomainManifest(
    name="messaging",
    schema_name="messaging",
    routers={"shop": shop_router, "webhooks": webhook_router, "storefront": chat_router},
    state_machine_rules=[*CONVERSATION_RULES, *CHANNEL_RULES],
    permissions=MESSAGING_PERMISSIONS,
    role_grants=MESSAGING_ROLE_GRANTS,
    event_subscribers=[
        channel_send,
        attachment_fetch,
        order_status_notify,
        support_case_notify,
        ig_comment_reply,
        ig_reply_send,
        ig_comment_classify,
        ig_post_fetch,
    ],
    scheduled_jobs=MESSAGING_JOBS,
)
