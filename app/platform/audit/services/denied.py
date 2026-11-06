"""Rad etilgan urinishlar audit'ga (TC-029, TC-ISO-01): ruxsat, filial doirasi yoki egalik
tekshiruvi 403 bersa —
`<resurs>.denied` yozuvi: kim, qaysi marshrut, qaysi obyekt, sabab kodi. Shaxsiy ma'lumot yo'q: marshrut
SHABLONI (`/orders/{order_id}/confirm`), so'rov tanasi va query yozilmaydi.

Markaziy: global xato handler'i (`app.shared.errors.handlers`) 403 `DomainError` ni ushlaganda chaqiradi —
har endpoint'ga alohida kod kerak emas. Arzon: bitta qator, xodim va marshrut bo'yicha daqiqasiga 5 tagacha
(parolni terib ko'rish yoki skript jurnalni to'ldirib yubormasin). Xato bo'lsa javobga ta'sir qilmaydi.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import Request

from app.platform.audit.services.audit_service import AuditService
from app.shared.db.session import Database
from app.shared.errors.base import DomainError
from app.shared.ratelimit import RateLimiter

logger = structlog.get_logger(__name__)

DENIED_PER_MINUTE = 5  # xodim + marshrut bo'yicha


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


class DeniedAttemptRecorder:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def __call__(self, request: Request, exc: DomainError) -> None:
        """Handler chaqiradi. Audit xatosi 403 javobini buzmaydi."""
        try:
            await self.record(request, exc)
        except Exception:
            logger.warning("denied_audit_failed", exc_info=True)

    async def record(self, request: Request, exc: DomainError) -> None:
        actor = getattr(request.state, "actor", None)
        if actor is None or actor.shop_id is None or actor.actor_id is None:
            return  # kim ekani noma'lum yoki platforma panel'i — shop jurnaliga tushmaydi
        route_path = getattr(request.scope.get("route"), "path", None) or ""  # prefikssiz: /orders/{order_id}
        template = str(request.scope.get("path", ""))  # haqiqiy ID'lar shablon nomiga almashtiriladi
        for name, value in request.path_params.items():
            template = template.replace(str(value), "{" + name + "}")
        route = template or "-"
        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None and await limiter.hit(
            f"denied-audit:{actor.actor_id}:{route}", DENIED_PER_MINUTE, 60
        ):
            return
        resource = route_path.strip("/").split("/", 1)[0] or "-"
        entity_id = next((u for v in request.path_params.values() if (u := _uuid(v))), None)
        reason = exc.details.get("reason")
        diff: dict[str, Any] = {"method": request.method, "route": route, "code": exc.code}
        if isinstance(exc.details.get("permission"), str):
            diff["permission"] = exc.details["permission"]
        database: Database = request.app.state.db
        async with database.transaction(actor.shop_id) as db:
            await self.audit.record(
                db,
                action=f"{resource}.denied",
                entity_type=resource,
                entity_id=entity_id,
                actor=actor,
                reason=reason if isinstance(reason, str) else exc.code,
                diff=diff,
            )
