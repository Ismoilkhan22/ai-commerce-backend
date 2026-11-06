"""catalog ruxsatlari va rollar (10 §6.2, business/04, DEC-131, DEC-133).

PC moslik (`catalog.compatibility.check`) — 6-modul bilan qo'shiladi.
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

# Import (5c, 18 §13): ega va menejer — to'liq; omborchi — faqat qoldiq importi (STOCK_ONLY, DEC-140,
# 2-qaror) — service `catalog.product.edit` va `commerce.stock.receive` bo'yicha cheklaydi
IMPORT = "catalog.import.run"
# Yetkazib beruvchi narx ro'yxati (DEC-149): AI o'qiydi va moslaydi, narxni ega yoki menejer tasdiqlaydi
PRICE_LIST = "catalog.price_list.run"

CATALOG_PERMISSIONS = sorted(MANAGE | {"catalog.product.archive", IMPORT, PRICE_LIST})

CATALOG_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": MANAGE | {"catalog.product.archive", IMPORT, PRICE_LIST},  # arxivlash — faqat ega (DEC-133)
    "MANAGER": MANAGE | {IMPORT, PRICE_LIST},
    "SALES": VIEW,
    "WAREHOUSE": VIEW | {IMPORT},
}
