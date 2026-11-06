"""sales_ai domeni: AI sotuvchi (6b) — sozlamalar, bilim bazasi, sinov oynasi, navbatlar, takliflar;
baholash va "AI sifati" (6c)."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.sales_ai.api.eval_routes import router as eval_router
from app.domains.sales_ai.api.routes import conversation_router
from app.domains.sales_ai.api.routes import router as ai_router
from app.domains.sales_ai.jobs import SALES_AI_JOBS
from app.domains.sales_ai.permissions import SALES_AI_PERMISSIONS, SALES_AI_ROLE_GRANTS
from app.domains.sales_ai.subscribers import ai_reply, eval_step
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(ai_router)
shop_router.include_router(conversation_router)
platform_router = APIRouter()
platform_router.include_router(eval_router)

DOMAIN_MANIFEST = DomainManifest(
    name="sales_ai",
    schema_name="sales_ai",
    routers={"shop": shop_router, "platform": platform_router},
    permissions=SALES_AI_PERMISSIONS,
    role_grants=SALES_AI_ROLE_GRANTS,
    event_subscribers=[ai_reply, eval_step],
    scheduled_jobs=SALES_AI_JOBS,
)
