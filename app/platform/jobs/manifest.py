"""platform/jobs moduli: dead-letter va ish jurnali (platforma paneli), platforma tozalash ishlari (S0-06)."""

from __future__ import annotations

from app.platform.jobs.api.platform_routes import router
from app.platform.jobs.services.maintenance import idempotency_cleanup, outbox_cleanup, partition_create
from app.shared.events.registry import ScheduledJob
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="jobs",
    schema_name="platform",
    routers={"platform": router},
    scheduled_jobs=[
        ScheduledJob("idempotency_cleanup", idempotency_cleanup, every_seconds=3600),  # TD-02
        ScheduledJob("audit_partition_create", partition_create, cron="0 3 25 * *"),  # TD-01
        ScheduledJob("outbox_cleanup", outbox_cleanup, cron="0 3 * * *"),
    ],
)
