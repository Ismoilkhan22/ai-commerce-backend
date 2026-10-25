"""Cursor pagination (11 §4.1): `?limit=` (≤100) va opaque `?cursor=`.

Cursor — saralash qiymati + `id` (base64 JSON). Offset ishlatilmaydi: ro'yxat o'zgarsa ham sahifalar
siljimaydi va chuqur sahifalar sekinlashmaydi.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from app.shared.errors.base import ValidationError

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise _invalid() from exc
    if not isinstance(value, dict):
        raise _invalid()
    return value


def _invalid() -> ValidationError:
    return ValidationError(
        "Cursor is invalid", fields=[{"field": "cursor", "code": "invalid_format", "params": {}}]
    )
