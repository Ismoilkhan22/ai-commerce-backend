"""Global xato handler'lari — barcha surface'lar uchun K-07 envelope (11 §6–7).

Kutilmagan xatolar (`Exception`) bu yerda emas, `RequestContextMiddleware` da ushlanadi —
shunda 500 javobida ham `X-Request-ID` bo'ladi.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.errors.base import DomainError
from app.shared.errors.catalog import status_for
from app.shared.serialization import to_json_compatible
from app.shared.tracing.context import get_trace_id

logger = structlog.get_logger(__name__)

# Starlette HTTPException status → katalog kodi. FastAPI'ning {"detail": ...} formati hech qachon chiqmaydi.
_HTTP_STATUS_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}

# Pydantic xato turi → `details.fields[].code` (11 §6.3)
_PYDANTIC_CODES = {
    "missing": "required",
    "greater_than": "min_value",
    "greater_than_equal": "min_value",
    "less_than": "max_value",
    "less_than_equal": "max_value",
    "string_too_short": "min_length",
    "too_short": "min_length",
    "string_too_long": "max_length",
    "too_long": "max_length",
    "enum": "invalid_choice",
    "literal_error": "invalid_choice",
}
_PYDANTIC_PARAMS = {
    "ge": "min",
    "gt": "min",
    "le": "max",
    "lt": "max",
    "min_length": "min",
    "max_length": "max",
}
_LOCATION_ROOTS = {"body", "query", "path", "header", "cookie"}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    # details'da UUID, Decimal, datetime bo'lishi mumkin — aylantirilmasa, xato javobining o'zi 500 bo'ladi
    safe_details = to_json_compatible(details or {})
    return {"error": {"code": code, "message": message, "details": safe_details, "trace_id": get_trace_id()}}


def error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    status = status_code or status_for(code)
    return JSONResponse(error_body(code, message, details), status_code=status, headers=headers)


def internal_error_response() -> JSONResponse:
    return error_response("INTERNAL_ERROR", "Internal server error")


def _field_path(loc: tuple[int | str, ...]) -> str:
    parts = list(loc[1:] if loc and loc[0] in _LOCATION_ROOTS else loc)
    path = ""
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path


def validation_fields(errors: list[Any]) -> list[dict[str, Any]]:
    fields = []
    for err in errors:
        ctx = err.get("ctx") or {}
        params = {_PYDANTIC_PARAMS[k]: v for k, v in ctx.items() if k in _PYDANTIC_PARAMS}
        fields.append(
            {
                "field": _field_path(tuple(err.get("loc", ()))),
                "code": _PYDANTIC_CODES.get(err.get("type", ""), "invalid_format"),
                "params": params,
            }
        )
    return fields


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    status = status_for(exc.code)
    log = logger.error if status >= 500 else logger.warning
    log("domain_error", code=exc.code, status=status)
    return error_response(exc.code, exc.message, exc.details)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    logger.warning("validation_failed")
    return error_response(
        "VALIDATION_FAILED", "Request validation failed", {"fields": validation_fields(list(exc.errors()))}
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Bizning kodda HTTPException ishlatilmaydi (DomainError ishlating) — bu framework va kutubxonalardan
    keladiganlar uchun. Katalogda yo'q 4xx o'z statusini saqlaydi: 409 ni 500 qilsak, klient
    "server xatosi, qayta urinish mumkin" deb noto'g'ri tushunadi."""
    assert isinstance(exc, StarletteHTTPException)
    headers = dict(exc.headers) if exc.headers else None
    code = _HTTP_STATUS_CODES.get(exc.status_code)
    if code is None:
        is_client_error = 400 <= exc.status_code < 500
        code = "INVALID_REQUEST" if is_client_error else "INTERNAL_ERROR"
        status = exc.status_code if is_client_error else 500
        (logger.warning if is_client_error else logger.error)(
            "unmapped_http_exception", status=exc.status_code
        )
        return error_response(code, code, headers=headers, status_code=status)
    message = exc.detail if isinstance(exc.detail, str) else code
    return error_response(code, message, headers=headers)


async def _stale_data_handler(_: Request, exc: Exception) -> JSONResponse:
    # VersionMixin: obyekt o'qilgandan keyin boshqa tranzaksiyada o'zgargan (12 §4)
    logger.warning("version_conflict")
    return error_response("VERSION_CONFLICT", "Resource was modified by another request")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(StaleDataError, _stale_data_handler)
