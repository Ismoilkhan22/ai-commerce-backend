"""commerce domeni: shop paneli — ombor, tez sotuv, buyurtmalar (3-modul).

Saytdan buyurtma so'rovi va buyurtma holati (`storefront` surface, DEC-115) — 4-modul; lead, PC taklifi,
"PC yig'ish" sahifasi va xaridor taklif havolasi — 6a.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domains.commerce.inventory.api.routes import router as inventory_router
from app.domains.commerce.inventory.import_subscriber import apply_import_stock
from app.domains.commerce.jobs import COMMERCE_JOBS
from app.domains.commerce.orders.api.routes import router as orders_router
from app.domains.commerce.orders.api.storefront_routes import router as storefront_orders_router
from app.domains.commerce.orders.services.privacy import erase_customer_handler
from app.domains.commerce.permissions import COMMERCE_PERMISSIONS, COMMERCE_ROLE_GRANTS
from app.domains.commerce.quick_sales.api.routes import router as quick_sales_router
from app.domains.commerce.quotes.api.public_routes import router as public_quotes_router
from app.domains.commerce.quotes.api.routes import builds_router, leads_router, quotes_router
from app.domains.commerce.quotes.jobs import QUOTE_JOBS, lead_activity, lead_won
from app.domains.commerce.quotes.state_machine import LEAD_RULES, QUOTE_RULES
from app.domains.commerce.state_machine import NON_FORCEABLE, ORDER_RULES, RESERVATION_RULES
from app.shared.types.manifest import DomainManifest

shop_router = APIRouter()
shop_router.include_router(inventory_router)
shop_router.include_router(quick_sales_router)
shop_router.include_router(orders_router)
shop_router.include_router(leads_router)
shop_router.include_router(quotes_router)
shop_router.include_router(builds_router)
storefront_router = APIRouter()
storefront_router.include_router(storefront_orders_router)
storefront_router.include_router(public_quotes_router)

DOMAIN_MANIFEST = DomainManifest(
    name="commerce",
    schema_name="commerce",
    routers={"shop": shop_router, "storefront": storefront_router},
    state_machine_rules=[*ORDER_RULES, *RESERVATION_RULES, *LEAD_RULES, *QUOTE_RULES],
    permissions=COMMERCE_PERMISSIONS,
    role_grants=COMMERCE_ROLE_GRANTS,
    privacy_handlers=[erase_customer_handler],
    non_forceable_states=NON_FORCEABLE,
    event_subscribers=[apply_import_stock, lead_won, lead_activity],  # import qoldig'i (5c); lead WON (6a)
    scheduled_jobs=(*COMMERCE_JOBS, *QUOTE_JOBS),  # 24/72 soat eslatmalari, kechki ombor solishtiruvi (S0-06)
)
