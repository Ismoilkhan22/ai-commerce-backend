"""storefront domeni: shop paneli ("Shop sayti") va ommaviy sayt API (4-modul, DEC-135).

Saytdan buyurtma so'rovi va buyurtma holati sahifasi — `commerce` (DEC-115), shu surface'da.
"""

from __future__ import annotations

from app.domains.storefront.api.public_routes import router as public_router
from app.domains.storefront.api.routes import router as panel_router
from app.domains.storefront.permissions import STOREFRONT_PERMISSIONS, STOREFRONT_ROLE_GRANTS
from app.domains.storefront.state_machine import SITE_RULES
from app.domains.storefront.subscribers import invalidate_site_cache
from app.shared.types.manifest import DomainManifest

DOMAIN_MANIFEST = DomainManifest(
    name="storefront",
    schema_name="storefront",
    routers={"shop": panel_router, "storefront": public_router},
    state_machine_rules=SITE_RULES,
    permissions=STOREFRONT_PERMISSIONS,
    role_grants=STOREFRONT_ROLE_GRANTS,
    event_subscribers=[invalidate_site_cache],  # sayt keshi event bilan (08 §4.3)
)
