"""HTTP yordamchilari: If-Match / ETag (11 §5, 12 §4), Location (11 §4)."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import Header, Request, Response

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


def split_commas(value: Any) -> Any:
    """`?status=A,B` va `?status=A&status=B` bir xil (11 §4.1): `BeforeValidator` uchun."""
    if isinstance(value, list):
        return [part.strip() for item in value for part in str(item).split(",") if part.strip()]
    return value


def set_location(request: Request, response: Response, route_name: str, **path_params: Any) -> None:
    """201 javobida yaratilgan resurs manzili: `Location: /api/v1/shop/products/{id}` (11 §4)."""
    params = {key: str(value) for key, value in path_params.items()}
    response.headers["Location"] = request.url_for(route_name, **params).path


def result_field(result: Any, name: str = "id") -> Any:
    """Idempotent endpoint natijasi: birinchi marta — model, takroriy so'rovda — saqlangan dict."""
    return result[name] if isinstance(result, dict) else getattr(result, name)


def check_version(current: int, expected: int) -> None:
    if current != expected:
        raise VersionConflictError("Version mismatch", current_version=current, your_version=expected)
