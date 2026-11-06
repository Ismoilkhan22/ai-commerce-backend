"""platform/realtime moduli: WebSocket ticket (auth), xodim WebSocket'i va signal tarqatish (08 §6)."""

from __future__ import annotations

from app.platform.realtime.api.routes import ticket_router, ws_router
from app.platform.realtime.subscribers import realtime_fanout, realtime_platform_fanout
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="realtime",
    schema_name="platform",
    routers={"auth": ticket_router, "realtime": ws_router},
    event_subscribers=[realtime_fanout, realtime_platform_fanout],
)
