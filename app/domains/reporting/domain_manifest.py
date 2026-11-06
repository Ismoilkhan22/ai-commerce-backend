"""reporting domeni: hisobot read model'lari va hisobot API (7c-modul, 19, DEC-146).

Boshqa domenlarning event'larini tinglab o'zining sodda jadvallariga yozadi; hisobotlar faqat shu jadvallardan
o'qiladi. Rejali ishlar: ombor qiymati va AI xarajati kunlik yig'malari (soatlik).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.reporting.api.routes import router as reports_router
from app.domains.reporting.jobs import REPORTING_JOBS
from app.domains.reporting.permissions import REPORTING_PERMISSIONS, REPORTING_ROLE_GRANTS
from app.domains.reporting.subscribers import SUBSCRIBERS
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(reports_router)

DOMAIN_MANIFEST = DomainManifest(
    name="reporting",
    schema_name="reporting",
    routers={"shop": shop_router},
    event_subscribers=SUBSCRIBERS,
    scheduled_jobs=REPORTING_JOBS,
    permissions=REPORTING_PERMISSIONS,
    role_grants=REPORTING_ROLE_GRANTS,
)
