"""catalog domeni: shop paneli (mahsulotlar, narxlar, bog'lash) va platforma paneli (toifalar, kutubxona)."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.catalog.imports.api.routes import router as imports_router
from app.domains.catalog.imports.state_machine import IMPORT_RULES
from app.domains.catalog.imports.subscribers import IMPORT_JOBS, finish_import, run_import_chunk
from app.domains.catalog.pc_specs.api.platform_routes import router as specs_platform_router
from app.domains.catalog.pc_specs.api.routes import router as specs_router
from app.domains.catalog.permissions import CATALOG_PERMISSIONS, CATALOG_ROLE_GRANTS
from app.domains.catalog.price_lists.api.routes import router as price_lists_router
from app.domains.catalog.price_lists.subscribers import read_price_list
from app.domains.catalog.pricing.api.routes import router as pricing_router
from app.domains.catalog.products.api.card_draft_routes import router as card_draft_router
from app.domains.catalog.products.api.platform_routes import router as categories_platform_router
from app.domains.catalog.products.api.routes import router as products_router
from app.domains.catalog.products.state_machine import PRODUCT_RULES
from app.domains.catalog.subscribers import CATALOG_JOBS, relink_on_spec_updated
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(card_draft_router)
shop_router.include_router(products_router)
shop_router.include_router(pricing_router)
shop_router.include_router(specs_router)
shop_router.include_router(imports_router)
shop_router.include_router(price_lists_router)

platform_router = APIRouter()
platform_router.include_router(categories_platform_router)
platform_router.include_router(specs_platform_router)

DOMAIN_MANIFEST = DomainManifest(
    name="catalog",
    schema_name="catalog",
    routers={"shop": shop_router, "platform": platform_router},
    state_machine_rules=[*PRODUCT_RULES, *IMPORT_RULES],
    permissions=CATALOG_PERMISSIONS,
    role_grants=CATALOG_ROLE_GRANTS,
    event_subscribers=[relink_on_spec_updated, run_import_chunk, finish_import, read_price_list],
    scheduled_jobs=[*CATALOG_JOBS, *IMPORT_JOBS],
)
