"""Composition root: domenlararo Query Port implementatsiyalari va DI provider'lar (02 §2, ADR-032).

`app.workers` bilan birga domenlarni import qila oladigan yagona joy. Domenlar faqat
`app/shared/contracts/` dagi interfeyslarni biladi; ulanish shu yerda bo'ladi.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import Settings, get_settings
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import ConversationOrdersPort, OrderQueryPort, StockQueryPort
from app.shared.contracts.imports import ImportStockResults, ImportStockSource
from app.shared.contracts.messaging import ChatAvailabilityPort

__all__ = [
    "Settings",
    "get_catalog_query",
    "get_chat_availability",
    "get_conversation_orders",
    "get_import_stock_results",
    "get_import_stock_source",
    "get_order_query",
    "get_settings",
    "get_stock_query",
]


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


def get_conversation_orders(commerce: Any) -> ConversationOrdersPort:
    """messaging (5b) suhbatdan buyurtma qoralamasi va bog'lash — commerce'ning OrderService'i orqali."""
    from app.domains.commerce.query_port import ConversationOrdersPortImpl

    return ConversationOrdersPortImpl(commerce.orders)


def get_import_stock_source() -> ImportStockSource:
    """commerce katalog importining qoldiq qatorlarini shu orqali o'qiydi (18 §7)."""
    from app.domains.catalog.query_port import ImportStockSourceImpl

    return ImportStockSourceImpl()


def get_chat_availability() -> ChatAvailabilityPort:
    """Sayt chat tugmasini faqat sayt chati yoqilgan shopda ko'rsatadi (5b)."""
    from app.domains.messaging.query_port import ChatAvailabilityPortImpl

    return ChatAvailabilityPortImpl()


def get_import_stock_results() -> ImportStockResults:
    """catalog import hisobotida qoldiq natijasini va joriy qoldiqni shu orqali o'qiydi."""
    from app.domains.commerce.query_port import ImportStockResultsImpl

    return ImportStockResultsImpl()
