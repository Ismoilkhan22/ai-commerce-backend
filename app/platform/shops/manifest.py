"""platform/shops moduli: shop, filiallar, sozlamalar; platforma paneli (DEC-122)."""

from __future__ import annotations

from fastapi import APIRouter

from app.platform.shops.api.platform_overview_routes import router as platform_overview_router
from app.platform.shops.api.platform_routes import router as platform_shops_router
from app.platform.shops.api.shop_audit_routes import router as shop_audit_router
from app.platform.shops.api.shop_routes import router as shop_profile_router
from app.platform.shops.api.signup_routes import router as signup_router
from app.platform.shops.state_machine import SHOP_RULES
from app.shared.types.manifest import DomainManifest

# Shop surface'i: profil, filiallar, o'zgarishlar tarixi
shop_router = APIRouter()
shop_router.include_router(shop_profile_router)
shop_router.include_router(shop_audit_router)

# Platforma surface'i: /platform/shops/* va /platform/dashboard, /platform/audit
platform_router = APIRouter()
platform_router.include_router(platform_shops_router)
platform_router.include_router(platform_overview_router)

MODULE_MANIFEST = DomainManifest(
    name="shops",
    schema_name="platform",
    # M21: /auth/signup/* — ochiq, `FEATURE_SELF_SIGNUP` o‘chiq bo‘lsa 501 FEATURE_NOT_AVAILABLE
    routers={"shop": shop_router, "platform": platform_router, "auth": signup_router},
    state_machine_rules=SHOP_RULES,
    role_grants={  # 10 §6.1, DEC-131 (4 rol)
        "OWNER": frozenset(
            {
                "shops.settings.view",
                "shops.settings.edit",
                "shops.policy.edit",
                "shops.branch.edit",
                "audit.view",
            }
        ),
        "MANAGER": frozenset({"shops.settings.view", "audit.view"}),
    },
)
