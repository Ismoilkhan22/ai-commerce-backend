"""Shop sayti uchun CORS (`/api/v1/storefront/*`): har shop o'z subdomenida — manzillar regex bilan.

Asosiy CORS (panellar) cookie bilan ishlaydi — saytga u ochilmaydi: sayt sahifasidagi skript refresh
cookie'ga hech qachon yeta olmasligi kerak. Bu yerda: faqat GET/POST, cookie'siz (`credentials` yo'q).
Panel CORS'i sayt yo'llarida umuman ishlamaydi (`PanelCorsMiddleware`), shuning uchun panel manzillari bu
yerda aks ettirilmaydi va `Access-Control-Allow-Credentials` hech qachon yuborilmaydi (QA M04 F1).
"""

from __future__ import annotations

import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

STOREFRONT_PREFIX = "/api/v1/storefront/"
ALLOW_METHODS = "GET, POST"
ALLOW_HEADERS = (
    "Content-Type, Idempotency-Key, Accept-Language, X-Storefront-Preview, X-Request-ID, X-Chat-Session"
)
EXPOSE_HEADERS = "Retry-After, X-Request-ID"
MAX_AGE = "600"


def is_storefront_path(path: str) -> bool:
    return path.startswith(STOREFRONT_PREFIX)


class PanelCorsMiddleware(CORSMiddleware):
    """Panellar CORS'i (cookie bilan) — sayt yo'llarida umuman ishlamaydi: u yerda o'z CORS'i bor."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_storefront_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


class StorefrontCorsMiddleware:
    def __init__(self, app: ASGIApp, origin_regex: str) -> None:
        self.app = app
        self.origin = re.compile(origin_regex)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_storefront_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allowed = origin is not None and bool(self.origin.fullmatch(origin))
        if scope["method"] == "OPTIONS" and headers.get("access-control-request-method"):
            if not allowed:
                await PlainTextResponse("Disallowed CORS origin", status_code=400)(scope, receive, send)
                return
            response = PlainTextResponse("OK", status_code=200)
            response.headers.update(
                {
                    "Access-Control-Allow-Origin": str(origin),
                    "Access-Control-Allow-Methods": ALLOW_METHODS,
                    "Access-Control-Allow-Headers": ALLOW_HEADERS,
                    "Access-Control-Max-Age": MAX_AGE,
                    "Vary": "Origin",
                }
            )
            await response(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and origin is not None:
                out = MutableHeaders(scope=message)
                # Ichkaridan nima kelsa ham: sayt javobida cookie ruxsati va begona manzil bo'lmaydi
                for name in ("access-control-allow-credentials", "access-control-allow-origin"):
                    if name in out:
                        del out[name]
                if allowed:
                    out["Access-Control-Allow-Origin"] = str(origin)
                    out["Access-Control-Expose-Headers"] = EXPOSE_HEADERS
                # Javob Origin'ga qarab farq qiladi — kesh (CDN, brauzer) buni bilishi kerak; bir marta
                vary = {part.strip().lower() for part in out.get("vary", "").split(",") if part.strip()}
                if "origin" not in vary:
                    out.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, send_with_cors)
