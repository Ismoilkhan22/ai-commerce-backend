"""Backend tarjimalari (11 §8.3–8.4): eksport sarlavhalari, holat nomlari, xato matnlari (bot/eksport uchun).

Dashboard interfeysi va API xatolarini frontend tarjima qiladi; backend xodimga matn yubormaydi.
Ko'plik shakllari (ICU plural) — xabar shablonlari bilan birga (20-notifications).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.shared.i18n.locale import FALLBACK_LOCALE, SUPPORTED_LOCALES, Locale, get_locale

LOCALES_DIR = Path(__file__).parent / "locales"


@cache
def load_catalog(locale: Locale) -> dict[str, str]:
    """YAML'ni tekis lug'atga aylantiradi: {"errors.NOT_FOUND": "..."}."""
    raw = yaml.safe_load((LOCALES_DIR / f"{locale}.yml").read_text(encoding="utf-8")) or {}
    flat: dict[str, str] = {}

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}.{key}" if prefix else str(key), value)
        else:
            flat[prefix] = str(node)

    walk("", raw)
    return flat


def t(key: str, locale: Locale | None = None, **params: object) -> str:
    """Tarjima: so'ralgan til → `uz` → kalitning o'zi."""
    loc = locale or get_locale()
    template = load_catalog(loc).get(key) or load_catalog(FALLBACK_LOCALE).get(key) or key
    try:
        return template.format(**params) if params else template
    except (KeyError, IndexError):
        return template


def missing_keys() -> dict[Locale, set[str]]:
    """Har til uchun boshqa tillarda bor, lekin unda yo'q kalitlar (CI tekshiruvi, 11 §8.6)."""
    all_keys = set().union(*(load_catalog(loc).keys() for loc in SUPPORTED_LOCALES))
    return {loc: all_keys - load_catalog(loc).keys() for loc in SUPPORTED_LOCALES}
