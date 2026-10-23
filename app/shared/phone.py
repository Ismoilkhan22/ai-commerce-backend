"""Telefon raqami — E.164 ko'rinishida saqlanadi (db/platform.md §4). Hozircha faqat O'zbekiston."""

from __future__ import annotations

import re

from app.shared.errors.base import ValidationError

_DIGITS = re.compile(r"\D")
_UZ_MOBILE = re.compile(r"^998\d{9}$")


def normalize_phone(raw: str, field: str = "phone") -> str:
    """'+998 90 123-45-67', '998901234567', '901234567' → '+998901234567'."""
    digits = _DIGITS.sub("", raw or "")
    if len(digits) == 9:
        digits = "998" + digits
    if not _UZ_MOBILE.match(digits):
        raise ValidationError(
            "Invalid phone number", fields=[{"field": field, "code": "invalid_format", "params": {}}]
        )
    return "+" + digits
