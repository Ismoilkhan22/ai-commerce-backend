"""platform/shops moduli: shop, filiallar, sozlamalar; platforma paneli (DEC-122)."""

from __future__ import annotations

from app.platform.shops.api.platform_routes import router as platform_router
from app.platform.shops.api.shop_routes import router as shop_router
from app.platform.shops.state_machine import SHOP_RULES
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="shops",
    schema_name="platform",
    routers={"shop": shop_router, "platform": platform_router},
    state_machine_rules=SHOP_RULES,
    role_grants={  # 10 §6.1, DEC-131 (4 rol)
        "OWNER": frozenset(
            {"shops.settings.view", "shops.settings.edit", "shops.policy.edit", "shops.branch.edit"}
        ),
        "MANAGER": frozenset({"shops.settings.view"}),
    },
)
