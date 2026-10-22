"""So'rov konteksti (contextvars): request_id va trace_id.

S0-05 da trace_id OpenTelemetry span'idan olinadi.
"""

from __future__ import annotations

import re
import secrets
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)

# W3C traceparent: version-traceid-parentid-flags
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def get_request_id() -> str | None:
    return _request_id.get()


def get_trace_id() -> str | None:
    return _trace_id.get()


def set_request_context(request_id: str, trace_id: str) -> None:
    _request_id.set(request_id)
    _trace_id.set(trace_id)


def trace_id_from_traceparent(header: str | None) -> str | None:
    """Yaroqli `traceparent` dan trace_id; nol trace_id W3C bo'yicha yaroqsiz."""
    if not header:
        return None
    match = _TRACEPARENT.match(header.strip().lower())
    if not match or match.group(1) == "0" * 32:
        return None
    return match.group(1)


def sanitize_request_id(header: str | None) -> str | None:
    """Klient yuborgan X-Request-ID faqat xavfsiz belgilardan iborat bo'lsa qabul qilinadi (log injection)."""
    if header and _REQUEST_ID.match(header):
        return header
    return None


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_request_id() -> str:
    return secrets.token_hex(16)
