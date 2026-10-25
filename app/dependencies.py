"""Composition root: domenlararo Query Port implementatsiyalari va DI provider'lar (02 §2, ADR-032).

`app.workers` bilan birga domenlarni import qila oladigan yagona joy. Domenlar faqat
`app/shared/contracts/` dagi interfeyslarni biladi; ulanish shu yerda bo'ladi.
"""

from __future__ import annotations

from app.config.settings import Settings, get_settings
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import OrderQueryPort, StockQueryPort

__all__ = ["Settings", "get_catalog_query", "get_order_query", "get_settings", "get_stock_query"]


def get_catalog_query() -> CatalogQueryPort:
    from app.domains.catalog.query_port import CatalogQueryPortImpl

    return CatalogQueryPortImpl()


def get_stock_query() -> StockQueryPort:
    """Sayt (4-modul) va AI mavjudlikni shu orqali o'qiydi — faqat sotuvga mavjud son va holat."""
    from app.domains.commerce.query_port import StockQueryPortImpl

    return StockQueryPortImpl(get_catalog_query())


def get_order_query() -> OrderQueryPort:
    """Platforma shopni yopishdan oldin ochiq buyurtmalarni shu orqali tekshiradi (TC-023)."""
    from app.domains.commerce.query_port import OrderQueryPortImpl

    return OrderQueryPortImpl()
