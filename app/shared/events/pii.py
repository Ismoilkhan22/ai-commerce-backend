"""Event payload'ida shaxsiy ma'lumot va sir yo'qligi (05 §3.1, 26 §4).

Maydon nomidagi so'z bo'yicha tekshiriladi (`customer_phone`, `deliveryAddress` — rad;
`phone_count` ham rad — ataylab qattiq). Topilsa — dasturchi xatosi: event yozilmaydi.
"""

from __future__ import annotations

import re
from typing import Any

FORBIDDEN_WORDS = frozenset(
    {
        "phone",
        "phones",
        "email",
        "emails",
        "address",
        "addresses",
        "password",
        "secret",
        "secrets",
        "token",
        "passport",
        "card",
        "pinfl",
        "birth",
        "name",
        "names",
        "text",
        "body",
        "comment",
        "message",
    }
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[a-z]+")


class EventPayloadError(ValueError):
    """Payload'da taqiqlangan maydon — PII yoki sir event'ga tushmoqchi."""


def _words(key: str) -> set[str]:
    return set(_WORD.findall(_CAMEL_BOUNDARY.sub("_", key).lower()))


def forbidden_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _words(str(key)) & FORBIDDEN_WORDS:
                found.append(f"{path}{key}")
            found.extend(forbidden_keys(item, f"{path}{key}."))
    elif isinstance(value, list):
        for item in value:
            found.extend(forbidden_keys(item, path))
    return found


def check_payload(payload: dict[str, Any]) -> None:
    if bad := forbidden_keys(payload):
        raise EventPayloadError(f"event payload'ida taqiqlangan maydon: {', '.join(bad)}")
