"""storefront ruxsatlari (10 §6.6): sozlamani faqat ega o'zgartiradi, menejer ko'radi."""

from __future__ import annotations

from collections.abc import Mapping

SITE_VIEW = "storefront.site.view"
SITE_EDIT = "storefront.site.edit"  # logotip, rang, kontaktlar, sahifalar, ochish/yopish

STOREFRONT_PERMISSIONS = sorted({SITE_VIEW, SITE_EDIT})

STOREFRONT_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": frozenset({SITE_VIEW, SITE_EDIT}),
    "MANAGER": frozenset({SITE_VIEW}),
}
