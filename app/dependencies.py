"""Composition root: domenlararo Query Port implementatsiyalari va DI provider'lar (02 §2, ADR-032).

`app.workers` bilan birga domenlarni import qila oladigan yagona joy. Domenlar faqat
`app/shared/contracts/` dagi interfeyslarni biladi; ulanish shu yerda bo'ladi.
"""

from __future__ import annotations

from app.config.settings import Settings, get_settings
from app.shared.contracts.catalog import CatalogQueryPort

__all__ = ["Settings", "get_catalog_query", "get_settings"]


def get_catalog_query() -> CatalogQueryPort:
    from app.domains.catalog.query_port import CatalogQueryPortImpl

    return CatalogQueryPortImpl()
