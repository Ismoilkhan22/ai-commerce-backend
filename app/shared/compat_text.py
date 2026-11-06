"""Moslik natijasi matnini yasash (engineering/17 §7): `message_key` + faktlar → so'ralgan tildagi matn.

Engine va muzlagan natijalar (taklif snapshot'lari, QA 6a F3) bir xil funksiyadan foydalanadi: snapshot'da
matn emas, kalit va faktlar saqlanadi — o'qishda xodim yoki xaridor tilida qayta yasaladi.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.i18n.locale import Locale
from app.shared.i18n.translator import t

CATEGORY_KEYS = ("category", "missing", "categories")  # qiymati toifa kodi — matnda toifa nomi


def _text(value: Any) -> Any:
    """Shablon uchun: ro'yxat — "ATX, MICRO_ATX"."""
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return value


def render_params(values: Mapping[str, Any], locale: Locale) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for name, value in values.items():
        if name in CATEGORY_KEYS:
            codes = value if isinstance(value, list | tuple) else [value]
            value = [t(f"compat.categories.{code}", locale) for code in codes]
        params[name] = _text(value)
    return params


def render_explanation(message_key: str, facts: Mapping[str, Any], locale: Locale) -> str:
    # `reason` — xabar kalitining qismi (compat.rules.<ID>.<reason>), shablon parametri emas
    return t(message_key, locale, **render_params({k: v for k, v in facts.items() if k != "reason"}, locale))


def render_hint(hint: Mapping[str, Any] | None, locale: Locale) -> str | None:
    if not hint or not hint.get("code"):
        return None
    params = render_params({k: v for k, v in hint.items() if k != "code"}, locale)
    return t(f"compat.hints.{hint['code']}", locale, **params)
