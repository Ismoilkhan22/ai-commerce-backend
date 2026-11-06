"""support domeni: kafolat va qaytarish murojaatlari (7b-modul, FSM-11, DEC-145)."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.support.api.routes import router as cases_router
from app.domains.support.jobs import SUPPORT_JOBS
from app.domains.support.permissions import SUPPORT_PERMISSIONS, SUPPORT_ROLE_GRANTS
from app.domains.support.services.privacy import erase_customer_handler
from app.domains.support.state_machine import CASE_RULES, NON_FORCEABLE
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(cases_router)

DOMAIN_MANIFEST = DomainManifest(
    name="support",
    schema_name="support",
    routers={"shop": shop_router},
    state_machine_rules=CASE_RULES,
    permissions=SUPPORT_PERMISSIONS,
    role_grants=SUPPORT_ROLE_GRANTS,
    privacy_handlers=[erase_customer_handler],
    non_forceable_states=NON_FORCEABLE,
    scheduled_jobs=SUPPORT_JOBS,  # RESOLVED + 7 kun → CLOSED
)
