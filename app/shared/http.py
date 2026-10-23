"""HTTP yordamchilari: If-Match / ETag (11 §5, 12 §4)."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header

from app.shared.errors.base import InvalidRequestError, VersionConflictError

_ETAG = re.compile(r'^(W/)?"v(\d+)"$')


def etag(version: int) -> str:
    return f'"v{version}"'


async def require_if_match(if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    """`If-Match: "v4"` → 4. Tahrir formalarida majburiy."""
    if not if_match:
        raise InvalidRequestError("If-Match header is required", header="If-Match")
    match = _ETAG.match(if_match.strip())
    if not match:
        raise InvalidRequestError("If-Match format is invalid", header="If-Match")
    return int(match.group(2))


def check_version(current: int, expected: int) -> None:
    if current != expected:
        raise VersionConflictError("Version mismatch", current_version=current, your_version=expected)
