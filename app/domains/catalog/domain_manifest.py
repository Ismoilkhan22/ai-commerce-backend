"""catalog domeni: shop paneli (mahsulotlar, narxlar, bog'lash) va platforma paneli (toifalar, kutubxona)."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.catalog.pc_specs.api.platform_routes import router as specs_platform_router
from app.domains.catalog.pc_specs.api.routes import router as specs_router
from app.domains.catalog.permissions import CATALOG_PERMISSIONS, CATALOG_ROLE_GRANTS
from app.domains.catalog.pricing.api.routes import router as pricing_router
from app.domains.catalog.products.api.platform_routes import router as categories_platform_router
from app.domains.catalog.products.api.routes import router as products_router
from app.domains.catalog.products.state_machine import PRODUCT_RULES
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(products_router)
shop_router.include_router(pricing_router)
shop_router.include_router(specs_router)

platform_router = APIRouter()
platform_router.include_router(categories_platform_router)
platform_router.include_router(specs_platform_router)

DOMAIN_MANIFEST = DomainManifest(
    name="catalog",
    schema_name="catalog",
    routers={"shop": shop_router, "platform": platform_router},
    state_machine_rules=PRODUCT_RULES,
    permissions=CATALOG_PERMISSIONS,
    role_grants=CATALOG_ROLE_GRANTS,
)
