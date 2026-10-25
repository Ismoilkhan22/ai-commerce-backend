"""RequestContextMiddleware — eng tashqi middleware (01 §5, 09).

- request_id va trace_id ni o'rnatadi (contextvars + structlog);
- har javobga `X-Request-ID` qo'shadi;
- ichkarida ushlanmagan har qanday xatoni K-07 envelope'li 500 ga aylantiradi (TC-CONV-03);
- har so'rov uchun bitta kirish logi (`http.request`): metod, yo'l, holat, davomiylik va query
  parametrlarining faqat NOMLARI. Qiymatlar yozilmaydi: `?q=+998…` (telefon bo'yicha qidiruv)
  logga tushmasin (26 §4).
- yo'l o'rniga mos kelgan route SHABLONI yoziladi: `/api/v1/auth/invites/{token}/accept` — bir martalik
  havola tokeni va ID'lar logga tushmaydi (QA N3, TC-SEC-08). Route topilmasa (404) — yo'l bo'laklari
  niqoblanadi (`redact_path`).
  Uvicorn'ning o'z kirish logi o'chiriladi (`app.config.logging`) — u to'liq URL'ni yozadi.
"""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qsl

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.errors.handlers import internal_error_response
from app.shared.tracing.context import (
    new_request_id,
    new_trace_id,
    sanitize_request_id,
    set_request_context,
    trace_id_from_traceparent,
)

logger = structlog.get_logger(__name__)
access_logger = structlog.get_logger("app.access")

_MAX_QUERY_KEYS = 20
_MAX_SEGMENTS = 8
_UUID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_PLAIN = re.compile(r"^[a-z][a-z-]{0,30}$")  # "api", "shop", "orders", "exchange-rates"
_VERSION = re.compile(r"^v[0-9]{1,2}$")


def redact_path(path: str) -> str:
    """Route topilmagan yo'l: faqat oddiy so'zlar qoladi, qolgani niqob — `/api/v1/x/{id}/{seg}`."""
    out: list[str] = []
    for segment in path.split("/")[1 : _MAX_SEGMENTS + 1]:
        if _PLAIN.match(segment) or _VERSION.match(segment):
            out.append(segment)
        elif _UUID.match(segment):
            out.append("{id}")
        else:
            out.append("{seg}")
    return "/" + "/".join(out)


def route_path(scope: Scope) -> str:
    """Mos kelgan route shabloni (`/api/v1/shop/orders/{order_id}`), topilmasa — niqoblangan yo'l."""
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return redact_path(str(scope.get("path", "")))


def query_keys(query_string: bytes) -> list[str]:
    """`q=+998…&limit=20` → `["limit", "q"]` — qiymatlarsiz (PII bo'lishi mumkin)."""
    try:
        pairs = parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
    except ValueError:
        return []
    return sorted({key[:40] for key, _ in pairs})[:_MAX_QUERY_KEYS]


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = sanitize_request_id(headers.get("x-request-id")) or new_request_id()
        trace_id = trace_id_from_traceparent(headers.get("traceparent")) or new_trace_id()
        set_request_context(request_id, trace_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, trace_id=trace_id)

        response_started = False
        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("unhandled_exception", path=route_path(scope))
            if response_started or scope["type"] != "http":
                raise
            await internal_error_response()(scope, receive, send_with_request_id)
        finally:
            if scope["type"] == "http":
                access_logger.info(
                    "http.request",
                    method=scope.get("method"),
                    path=route_path(scope),
                    query_keys=query_keys(scope.get("query_string", b"")),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
