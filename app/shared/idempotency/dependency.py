"""`Idempotency-Key` header'i — barcha yozish POST'larida majburiy (11 §5)."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header

from app.shared.errors.base import InvalidRequestError

_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


async def get_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if not idempotency_key:
        raise InvalidRequestError("Idempotency-Key header is required", header="Idempotency-Key")
    if not _KEY.match(idempotency_key):
        raise InvalidRequestError("Idempotency-Key format is invalid", header="Idempotency-Key")
    return idempotency_key
