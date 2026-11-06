"""structlog JSON konfiguratsiyasi. To'liq log sxemasi va PII filtri — S0-05 (09-observability)."""

from __future__ import annotations

import logging
import re

import structlog

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
