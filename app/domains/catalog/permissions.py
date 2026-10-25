"""catalog ruxsatlari va rollar (10 §6.2, business/04, DEC-131, DEC-133).

Import (`catalog.import.*`) — 5-modul, PC moslik (`catalog.compatibility.check`) — 6-modul bilan qo'shiladi.
"""

from __future__ import annotations

from collections.abc import Mapping

VIEW = frozenset({"catalog.product.view", "catalog.price.view"})
MANAGE = VIEW | frozenset(
    {
        "catalog.product.edit",
        "catalog.product.publish",
        "catalog.price.change",
        "catalog.exchange_rate.edit",
        "catalog.spec.link",
    }
)

CATALOG_PERMISSIONS = sorted(MANAGE | {"catalog.product.archive"})

CATALOG_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": MANAGE | {"catalog.product.archive"},  # arxivlash — faqat ega (DEC-133)
    "MANAGER": MANAGE,
    "SALES": VIEW,
    "WAREHOUSE": VIEW,
}
