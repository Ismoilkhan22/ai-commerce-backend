"""structlog JSON konfiguratsiyasi. To'liq log sxemasi va PII filtri — S0-05 (09-observability)."""

from __future__ import annotations

import logging
import os
import re

import structlog
from structlog.types import EventDict

_QUERY = re.compile(r"\?[^\s\"']*")


class RedactQueryFilter(logging.Filter):
    """Uvicorn'ning o'z xabarlaridagi query qatorini yashiradi: `"WebSocket /api/v1/ws?ticket=…" [accepted]`
    ticket'ni (30 soniyalik kalit) logga yozardi (QA 5a F6, 26 §4)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_QUERY.sub("?…", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str) and "?" in record.msg:
            record.msg = _QUERY.sub("?…", record.msg)
        return True


class _ServiceFields:
    """Har JSON qatorga `service`, `env`, `version` (09 §4): bir nechta jarayon loglari bitta joyda ajraladi.
    Qiymatlar env'dan (SERVICE_NAME, APP_ENV, APP_VERSION — deploy beradi)."""

    def __init__(self) -> None:
        self.fields = {
            "service": os.environ.get("SERVICE_NAME", "api"),
            "env": os.environ.get("APP_ENV", "local"),
            "version": os.environ.get("APP_VERSION", "dev"),
        }

    def __call__(self, logger: object, name: str, event: EventDict) -> EventDict:
        for key, value in self.fields.items():
            event.setdefault(key, value)
        return event


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # request_id, trace_id (shared/tracing)
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            *([_ServiceFields()] if json else []),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        cache_logger_on_first_use=True,
    )
    # Uvicorn kirish logi to'liq URL'ni yozadi (query bilan — telefon, 26 §4). Uning o'rniga
    # RequestContextMiddleware'dagi `http.request` (query qiymatlarisiz). `--no-access-log` ham shu ish.
    logging.getLogger("uvicorn.access").disabled = True
    error_logger = logging.getLogger("uvicorn.error")  # WebSocket "accepted"/"open"/"closed" xabarlari
    if not any(isinstance(flt, RedactQueryFilter) for flt in error_logger.filters):
        error_logger.addFilter(RedactQueryFilter())
    # Sentry — faqat SENTRY_DSN bo'lsa (09 §9). Har jarayon (api, worker'lar) shu funksiyani chaqiradi
    from app.config.observability import init_sentry
    from app.config.settings import get_settings

    init_sentry(get_settings())
