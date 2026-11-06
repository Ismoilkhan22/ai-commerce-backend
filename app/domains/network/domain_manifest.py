"""network domeni (Stage 2): umumiy katalog va ommaviy takliflar — db/network.md, engineering/28."""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.network.api.marketplace_routes import router as marketplace_router
from app.domains.network.api.partner_routes import router as partner_router
from app.domains.network.api.platform_routes import router as platform_network_router
from app.domains.network.api.routes import router as shop_network_router
from app.domains.network.permissions import NETWORK_PERMISSIONS, NETWORK_ROLE_GRANTS
from app.domains.network.subscribers import pos_stock_applied, refresh_offers, shop_status_changed
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(shop_network_router)
public_router = APIRouter()  # Stage 3: xaridorning global qidiruvi (db/marketplace.md)
public_router.include_router(marketplace_router)
platform_router = APIRouter()
platform_router.include_router(platform_network_router)

DOMAIN_MANIFEST = DomainManifest(
    name="network",
    schema_name="network",
    routers={
        "shop": shop_router,
        "platform": platform_router,
        "public": public_router,
        "partner": partner_router,
    },
    permissions=NETWORK_PERMISSIONS,
    role_grants=NETWORK_ROLE_GRANTS,
    event_subscribers=[refresh_offers, shop_status_changed, pos_stock_applied],
)
