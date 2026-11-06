"""network ruxsatlari (Stage 2, M24): ommaviy takliflarni ko'rish va boshqarish — ega va menejer."""

from __future__ import annotations

from collections.abc import Mapping

VIEW = "network.offer.view"
MANAGE = "network.offer.manage"
API_KEYS = "network.api_key.manage"  # M30: hamkor API kalitlari — faqat ega

NETWORK_PERMISSIONS = sorted({VIEW, MANAGE, API_KEYS})

NETWORK_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": frozenset({VIEW, MANAGE, API_KEYS}),
    "MANAGER": frozenset({VIEW, MANAGE}),
}
