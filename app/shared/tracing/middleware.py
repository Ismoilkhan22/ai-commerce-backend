"""RequestContextMiddleware — eng tashqi middleware (01 §5, 09).

- request_id va trace_id ni o'rnatadi (contextvars + structlog);
- har javobga `X-Request-ID` qo'shadi;
- ichkarida ushlanmagan har qanday xatoni K-07 envelope'li 500 ga aylantiradi (TC-CONV-03).
"""

from __future__ import annotations

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

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("unhandled_exception", path=scope.get("path"))
            if response_started or scope["type"] != "http":
                raise
            await internal_error_response()(scope, receive, send_with_request_id)
