"""Telefon raqami — E.164 ko'rinishida saqlanadi (db/platform.md §4). Hozircha faqat O'zbekiston.

Qat'iy: harf yoki boshqa belgi bo'lsa — rad etiladi ("+998 90 123 45 67 x" boshqa raqamga aylanib
qolmasin). Ajratgichlar: bo'shliq, `-`, `(`, `)`, `.`. `+` faqat boshida. Mamlakat kodi bilan (`+998` yoki
`998…`) — aynan 12 raqam; 9 raqam — faqat mamlakat kodisiz (mahalliy yozuv, "90 123 45 67").
Faqat ASCII raqamlar (0–9): Python'da `\\d` arab yoki to'liq kenglikdagi raqamlarni ham ushlaydi — ular
rad etiladi, aks holda "+998٩٠…" saqlanib, qidiruvda topilmay qoladi.
"""

from __future__ import annotations

import re

from app.shared.errors.base import ValidationError

# Bo'shliqlar: oddiy, tab va nusxalashda keladigan "qattiq" bo'shliqlar (U+00A0, U+202F).
# Faqat `fullmatch` bilan: `$` oxiridagi yangi qatordan oldin ham mos keladi ("+998…\n" o'tib ketardi)
_ALLOWED = re.compile("[ \t\u00a0\u202f]*\\+?[0-9 \t\u00a0\u202f().-]*")
_DIGITS = re.compile(r"[^0-9]")
_UZ_MOBILE = re.compile(r"998[0-9]{9}")


def _invalid(field: str) -> ValidationError:
    return ValidationError(
        "Invalid phone number", fields=[{"field": field, "code": "invalid_format", "params": {}}]
    )


def normalize_phone(raw: str, field: str = "phone") -> str:
    """'+998 90 123-45-67', '998901234567', '901234567' → '+998901234567'."""
    text = raw or ""
    if not _ALLOWED.fullmatch(text):
        raise _invalid(field)
    digits = _DIGITS.sub("", text)
    has_plus = text.lstrip().startswith("+")
    if len(digits) == 9 and not has_plus:  # mahalliy yozuv: operator kodi + 7 raqam
        digits = "998" + digits
    if not _UZ_MOBILE.fullmatch(digits):
        raise _invalid(field)
    return "+" + digits
