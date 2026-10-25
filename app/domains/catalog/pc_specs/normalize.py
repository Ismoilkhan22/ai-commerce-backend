"""MPN va model nomini solishtirish uchun normallashtirish (engineering/17 §5).

Katta harf, bo'shliq va belgilarsiz: "V516-012R" → "V516012R", "GeForce RTX 4060 Ti" → "GEFORCERTX4060TI".
`Ti`, `SUPER`, `OC` va xotira hajmi saqlanadi — "RTX 4060" va "RTX 4060 Ti" hech qachon bir xil chiqmaydi.
"""

from __future__ import annotations

import re

_NOT_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


def normalize_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _NOT_ALNUM.sub("", value.upper())
    return normalized or None


def normalize_brand(value: str | None) -> str | None:
    return normalize_code(value)
