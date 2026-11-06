"""Sayt buyurtma formasidagi rozilik va maxfiylik siyosati shabloni (engineering/26 §8, storefront.md §2).

Matn platformaniki — huquqshunos tekshiradi, shop o'zicha yozmaydi; shop rekvizitlari shablonga qo'yiladi.
Xaridor rozilik belgisini qo'yganda `commerce.orders.consent_version` ga shu versiya yoziladi.

Matn (`consent.*`, `privacy.*` — locales/*.yml) o'zgarsa, versiya ham yangilanadi: aks holda bazadagi
versiya xaridor aslida ko'rmagan matnga ishora qilib qoladi. `CONSENT_FINGERPRINT` buni testda ushlaydi.
"""

from __future__ import annotations

import hashlib

from app.shared.i18n.locale import SUPPORTED_LOCALES
from app.shared.i18n.translator import load_catalog

STOREFRONT_CONSENT_VERSION = "sf-order-2026-10-26"
# Matn barmoq izi (uchala til). Test yiqilsa: matn o'zgargan — versiyani ham, shu qiymatni ham yangilang
CONSENT_FINGERPRINT = "9532395ffabd2d16"

CONSENT_KEYS = ("consent.storefront_order",)
PRIVACY_KEYS = (
    "privacy.title",
    "privacy.intro",
    "privacy.data",
    "privacy.purpose",
    "privacy.storage",
    "privacy.rights",
    "privacy.contact",
)


def consent_fingerprint() -> str:
    """Rozilik va siyosat matnining hash'i (uchala til) — versiya bilan birga o'zgarishi kerak."""
    parts: list[str] = []
    for locale in SUPPORTED_LOCALES:
        catalog = load_catalog(locale)
        parts.extend(f"{locale}:{key}={catalog.get(key, '')}" for key in (*CONSENT_KEYS, *PRIVACY_KEYS))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
