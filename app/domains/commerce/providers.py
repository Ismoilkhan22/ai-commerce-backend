"""commerce servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Katalog narxi va SKU'si `CatalogQueryPort` orqali keladi — `catalog` kodi import qilinmaydi (ADR-032).
Saytdan buyurtma so'rovi uchun sayt holati — `SitePort`, mavjudlik — `StockQueryPort` (4-modul).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.commerce.inventory.services.stock_service import StockService
from app.domains.commerce.orders.services.lifecycle_service import OrderLifecycleService
from app.domains.commerce.orders.services.order_service import OrderService
from app.domains.commerce.orders.services.privacy import OrderPrivacyService
from app.domains.commerce.orders.services.storefront_service import StorefrontOrderService
from app.domains.commerce.orders.services.views import OrderViews
from app.domains.commerce.quick_sales.services.quick_sale_service import QuickSaleService
from app.platform.audit.services.audit_service import AuditService
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import StockQueryPort
from app.shared.contracts.storefront import SitePort


@dataclass(frozen=True)
class CommerceServices:
    stock: StockService
    quick_sales: QuickSaleService
    orders: OrderService
    lifecycle: OrderLifecycleService
    privacy: OrderPrivacyService
    storefront: StorefrontOrderService
    site: SitePort


def build_commerce_services(
    use: UseService,
    audit: AuditService,
    files: FileService,
    catalog: CatalogQueryPort,
    stock_query: StockQueryPort,
    site: SitePort,
) -> CommerceServices:
    stock = StockService(audit, files, catalog)
    views = OrderViews()
    orders = OrderService(audit, catalog, views)
    return CommerceServices(
        stock=stock,
        quick_sales=QuickSaleService(audit, stock, catalog),
        orders=orders,
        lifecycle=OrderLifecycleService(use, audit, orders, stock, catalog, views),
        privacy=OrderPrivacyService(audit),
        storefront=StorefrontOrderService(use, audit, orders, catalog, stock_query),
        site=site,
    )


def commerce_services(request: Request) -> CommerceServices:
    return request.app.state.commerce  # type: ignore[no-any-return]
