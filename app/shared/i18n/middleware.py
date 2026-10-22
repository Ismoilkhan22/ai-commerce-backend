"""I18nMiddleware — `Accept-Language` → so'rov tili (11 §8.2).

Xodim profilining tili (`principals.locale`) S0-04 da `ActorContext` yig'ilganda ustun qo'yiladi.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.shared.i18n.locale import FALLBACK_LOCALE, Locale, negotiate_locale, set_locale


class I18nMiddleware:
    def __init__(self, app: ASGIApp, default_locale: Locale = FALLBACK_LOCALE) -> None:
        self.app = app
        self.default_locale = default_locale

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            accept_language = Headers(scope=scope).get("accept-language")
            set_locale(negotiate_locale(accept_language, self.default_locale))
        await self.app(scope, receive, send)
