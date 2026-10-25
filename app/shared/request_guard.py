"""RequestGuardMiddleware — so'rov endpoint'ga yetguncha umumiy tekshiruvlar va qayta urinish.

1. **NUL belgisi** (`\\x00`, `%00`). PostgreSQL matnda uni saqlay olmaydi — tekshirilmasa 500 bo'lardi:
   - yo'lda → 404 (bunday manzil yo'q);
   - query parametrida → 422 `invalid_format` (maydon — parametr nomi);
   - JSON tanasida (qiymat yoki kalit) → 422 `invalid_format` (maydon yo'li: `skus[0].variant_name`).
2. **NaN / Infinity** JSON'da — standart JSON emas, jsonb ham saqlamaydi → 422 `invalid_format`.
3. **JSON tana chegarasi** — 1 MiB (eng katta forma ham bir necha KB) → 413. Fayllar JSON emas, ular
   o'z endpoint'ida o'z chegarasi bilan o'qiladi.
4. **Deadlock (`40P01`) yoki serialization (`40001`)** — butun so'rov (tranzaksiya) qayta bajariladi:
   ko'pi bilan 3 urinish, 20–200 ms jitter (12 §3). Tranzaksiya ichida tashqi effekt yo'q, shuning uchun
   xavfsiz. Tanasi qayta yuborib bo'lmaydigan so'rov (fayl) qayta urinilmaydi. `/api/v1/auth/` ham
   qayta urinilmaydi: u yerda tranzaksiyadan tashqari effekt bor — rate limit hisoblagichi (Redis),
   qayta urinish uni ikki marta oshirardi. Urinishlar tugasa — 409 `VERSION_CONFLICT`
   ("ma'lumot o'zgarmoqda, qayta urinib ko'ring").
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl

import structlog
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.errors.handlers import error_response
from app.shared.text import NUL

logger = structlog.get_logger(__name__)

MAX_JSON_BYTES = 1024 * 1024
MAX_ATTEMPTS = 3
RETRY_JITTER_S = (0.02, 0.2)
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})
# Tranzaksiyadan tashqari effekti bor yo'llar (rate limit hisoblagichi) — butun so'rov qayta bajarilmaydi
NO_RETRY_PREFIXES = ("/api/v1/auth/",)
_MAX_REPORTED_FIELDS = 50


class _NonFinite(str):
    """`json.loads(parse_constant=...)` belgisi: NaN, Infinity, -Infinity."""


def sqlstate_of(exc: BaseException) -> str | None:
    """SQLAlchemy → asyncpg zanjiridan PostgreSQL xato kodi (`40P01` ...)."""
    current: BaseException | None = exc
    for _ in range(5):
        if current is None:
            return None
        for attr in ("pgcode", "sqlstate"):
            value = getattr(current, attr, None)
            if isinstance(value, str):
                return value
        current = getattr(current, "orig", None) or current.__cause__
    return None


def _invalid(fields: Iterable[str]) -> JSONResponse:
    unique = sorted(set(fields))[:_MAX_REPORTED_FIELDS]
    return error_response(
        "VALIDATION_FAILED",
        "Request validation failed",
        {"fields": [{"field": field, "code": "invalid_format", "params": {}} for field in unique]},
    )


def _query_problems(query_string: bytes) -> list[str]:
    pairs = parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
    return [key.replace(NUL, "") or "query" for key, value in pairs if NUL in key or NUL in value]


def _json_problems(data: Any) -> list[str]:
    """NUL va NaN/Infinity bor maydonlar yo'li (11 §6.3 formatida). Rekursiyasiz — chuqur JSON ham xavfsiz."""
    problems: list[str] = []
    stack: list[tuple[str, Any]] = [("", data)]
    while stack and len(problems) < _MAX_REPORTED_FIELDS:
        path, value = stack.pop()
        if isinstance(value, _NonFinite) or (isinstance(value, str) and NUL in value):
            problems.append(path or "body")
        elif isinstance(value, dict):
            for key, item in value.items():
                clean = key.replace(NUL, "")
                child = f"{path}.{clean}" if path else clean
                if NUL in key:
                    problems.append(path or "body")
                stack.append((child, item))
        elif isinstance(value, list):
            stack.extend((f"{path}[{index}]", item) for index, item in enumerate(value))
    return problems


def _is_json(headers: Headers) -> bool:
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return content_type == "application/json" or content_type.endswith("+json")


def _replayable(headers: Headers) -> bool:
    """Tanani xotirada saqlab, qayta yuborsa bo'ladimi: JSON yoki tanasiz so'rov. Fayl — yo'q."""
    has_body = headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in headers
    return _is_json(headers) or not has_body


async def _read_body(receive: Receive, limit: int) -> tuple[bytes | None, bool]:
    """(tana, juda katta). Klient uzilsa — (None, False)."""
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None, False
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None, True
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks), False


def _replay(body: bytes, receive: Receive) -> Receive:
    delivered = False

    async def replay() -> Message:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()  # keyin — klient uzilishini kutish (asl kanal)

    return replay


class RequestGuardMiddleware:
    def __init__(
        self, app: ASGIApp, *, max_json_bytes: int = MAX_JSON_BYTES, attempts: int = MAX_ATTEMPTS
    ) -> None:
        self.app = app
        self.max_json_bytes = max_json_bytes
        self.attempts = attempts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if NUL in scope.get("path", ""):
            await error_response("NOT_FOUND", "Not found")(scope, receive, send)
            return
        if problems := _query_problems(scope.get("query_string", b"")):
            await _invalid(problems)(scope, receive, send)
            return
        headers = Headers(scope=scope)
        body: bytes | None = None
        if _replayable(headers):
            body, too_large = await _read_body(receive, self.max_json_bytes)
            if too_large:
                response = error_response(
                    "PAYLOAD_TOO_LARGE", "Request body too large", {"max_bytes": self.max_json_bytes}
                )
                await response(scope, receive, send)
                return
            if body is None:
                return  # klient uzildi
            if body and _is_json(headers):
                try:
                    data = json.loads(body, parse_constant=_NonFinite)
                except RecursionError:
                    await error_response("INVALID_REQUEST", "Malformed JSON body")(scope, receive, send)
                    return
                except ValueError:
                    data = None  # buzuq JSON — FastAPI o'zi 400 qaytaradi
                if data is not None and (problems := _json_problems(data)):
                    await _invalid(problems)(scope, receive, send)
                    return
        await self._run(scope, receive, send, body)

    async def _run(self, scope: Scope, receive: Receive, send: Send, body: bytes | None) -> None:
        retryable = body is not None and not scope.get("path", "").startswith(NO_RETRY_PREFIXES)
        attempts = self.attempts if retryable else 1
        initial_state = dict(scope.get("state") or {})
        for attempt in range(1, attempts + 1):
            started = False

            async def tracked(message: Message) -> None:
                nonlocal started
                if message["type"] == "http.response.start":
                    started = True
                await send(message)

            # Har urinish toza holatdan: oldingi urinishning request.state'i (actor, shop) qolmasin
            attempt_scope = {**scope, "state": dict(initial_state)}
            try:
                await self.app(
                    attempt_scope, _replay(body, receive) if body is not None else receive, tracked
                )
                return
            except DBAPIError as exc:
                sqlstate = sqlstate_of(exc)
                if started or sqlstate not in RETRYABLE_SQLSTATES:
                    raise
                logger.warning("transaction_retry", attempt=attempt, sqlstate=sqlstate)
            if attempt < attempts:
                await asyncio.sleep(random.uniform(*RETRY_JITTER_S))  # noqa: S311 — jitter, kriptografiya emas
        await error_response("VERSION_CONFLICT", "Data is being changed concurrently, retry")(
            scope, receive, send
        )
