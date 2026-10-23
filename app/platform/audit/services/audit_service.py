"""Audit yozuvi — biznes o'zgarishi bilan bitta tranzaksiyada (07 §4.2, 10).

`diff` faqat xavfsiz maydonlar: shaxsiy ma'lumot va sirlar audit'ga tushmaydi (TC-SEC-08).
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models.orm import AuditEntry
from app.shared.tracing.context import get_trace_id
from app.shared.types.actor import ActorContext

# Kalit nomida shular bo'lsa — dasturchi xatosi (PII yoki sir audit'ga yozilmoqchi)
_FORBIDDEN_KEY = re.compile(r"phone|email|address|password|secret|token|passport|card|pinfl|birth", re.I)


class AuditDiffError(ValueError):
    pass


def _check_diff(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _FORBIDDEN_KEY.search(str(key)):
                raise AuditDiffError(f"audit diff'da taqiqlangan maydon: {path}{key}")
            _check_diff(item, f"{path}{key}.")
    elif isinstance(value, list):
        for item in value:
            _check_diff(item, path)


class AuditService:
    async def record(
        self,
        db: AsyncSession,
        *,
        action: str,
        entity_type: str,
        entity_id: UUID | None,
        actor: ActorContext,
        entity_version: int | None = None,
        reason: str | None = None,
        diff: dict[str, Any] | None = None,
    ) -> None:
        if diff is not None:
            _check_diff(diff)
        db.add(
            AuditEntry(
                shop_id=actor.shop_id,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_version=entity_version,
                reason=reason,
                diff=diff,
                trace_id=get_trace_id(),
            )
        )
        await db.flush()
