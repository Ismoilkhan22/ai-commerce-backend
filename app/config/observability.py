"""Sentry (09 §9, S0-05): faqat `SENTRY_DSN` bo'lsa yoqiladi; PII Sentry'ga ketmaydi.

Qavatlar:
1. SDK sozlamasi: `send_default_pii=False`, request body hech qachon, lokal o'zgaruvchilar yo'q.
2. `before_send`: request'dan faqat metod va query'siz URL qoladi (header, cookie, body, query — yo'q);
   `user` — faqat `id` (actor_id); matnlardagi telefon, email, token shakllari niqoblanadi;
   kutilgan `DomainError` (4xx) yuborilmaydi.
3. `before_breadcrumb`: HTTP breadcrumb'lar tashlanadi (Telegram API manzilida bot token bor).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config.settings import Settings

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "[bot-token]"),  # Telegram bot token
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [token]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[jwt]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<![\w-])\+?(?:\d[\s()-]?){9,15}(?![\w-])"), "[phone]"),  # 9+ raqam; sana emas
    (re.compile(r"\?[^\s\"']+"), "?…"),  # URL query (qidiruvda telefon, WS ticket, imzo)
)
_DROP_BREADCRUMBS = frozenset({"httplib", "http", "httpx", "requests", "redis", "query"})


def scrub_text(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[…]"
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {key: _scrub(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, depth + 1) for item in value]
    return value


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    from app.shared.errors.base import DomainError

    exc_info = hint.get("exc_info")
    if exc_info and isinstance(exc_info[1], DomainError):
        return None
    request = event.get("request")
    if isinstance(request, dict):
        event["request"] = {
            "method": request.get("method"),
            "url": str(request.get("url") or "").split("?", 1)[0],
        }
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if user.get("id") else {}
    for field in ("exception", "logentry", "message", "extra", "contexts", "tags", "breadcrumbs"):
        if field in event:
            event[field] = _scrub(event[field])
    return event


def before_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    if crumb.get("category") in _DROP_BREADCRUMBS or crumb.get("type") == "http":
        return None
    return dict(_scrub(crumb))


def init_sentry(settings: Settings) -> bool:
    """Bir marta, jarayon boshida (configure_logging chaqiradi). DSN yo'q — hech narsa qilmaydi."""
    if settings.sentry_dsn is None or not settings.sentry_dsn.get_secret_value():
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env,
        release=settings.app_version,
        server_name=settings.service_name,  # xost nomi emas — jarayon (api, task-worker, ...)
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=before_send,  # type: ignore[arg-type]
        before_breadcrumb=before_breadcrumb,
    )
    sentry_sdk.set_tag("service", settings.service_name)
    return True
