"""/health/live va /health/ready (02, 22).

Readiness tekshiruvlari lifespan'da ro'yxatga olinadi (S0-03: PostgreSQL, S0-06: Redis).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.shared.errors.handlers import error_response

ReadinessCheck = Callable[[], Awaitable[None]]

CHECK_TIMEOUT_SECONDS = 2.0

router = APIRouter(prefix="/health", tags=["health"], include_in_schema=False)


def readiness_checks(request: Request) -> dict[str, ReadinessCheck]:
    checks: dict[str, ReadinessCheck] = getattr(request.app.state, "readiness_checks", {})
    return checks


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    results: dict[str, str] = {}
    for name, check in readiness_checks(request).items():
        try:
            await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
            results[name] = "ok"
        except Exception:  # tekshiruv natijasi; xato tafsiloti tashqariga chiqmaydi
            results[name] = "fail"
    if any(status != "ok" for status in results.values()):
        return error_response("SERVICE_UNAVAILABLE", "Service not ready", {"checks": results})
    return JSONResponse({"status": "ready", "checks": results})
