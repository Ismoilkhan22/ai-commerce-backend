"""platform/billing moduli: M26 tariflar va hisob-fakturalar (Stage 2)."""

from __future__ import annotations

from app.platform.billing.api.routes import platform_router, shop_router
from app.platform.billing.jobs import BILLING_JOBS
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="billing",
    schema_name="platform",
    routers={"shop": shop_router, "platform": platform_router},
    permissions=["billing.view", "billing.manage"],
    role_grants={"OWNER": frozenset({"billing.view", "billing.manage"})},  # tarif — ega qarori
    scheduled_jobs=list(BILLING_JOBS),
)
