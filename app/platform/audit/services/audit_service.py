"""Audit yozuvi — biznes o'zgarishi bilan bitta tranzaksiyada (07 §4.2, 10).

`diff` faqat xavfsiz maydonlar: shaxsiy ma'lumot va sirlar audit'ga tushmaydi (TC-SEC-08).
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models.orm import AuditEntry
from app.shared.serialization import to_json_compatible
from app.shared.tracing.context import get_trace_id
from app.shared.types.actor import ActorContext

# Maydon nomidagi SO'ZLAR shulardan biri bo'lsa — dasturchi xatosi (PII yoki sir audit'ga yozilmoqchi).
# So'z bo'yicha tekshiriladi: `customer_phone`, `refreshToken` — rad; `tokens_in`, `discard_reason` — o'tadi.
_FORBIDDEN_WORDS = frozenset(
    {
        "phone",
        "email",
        "address",
        "password",
        "passwd",
        "secret",
        "token",
        "passport",
        "card",
        "pinfl",
        "birth",
    }
)
# Ko'plik shakllari aniq ro'yxat bilan: `tokens` ATAYLAB yo'q — `tokens_in` AI xarajati (son), sir emas.
_FORBIDDEN_PLURALS = frozenset(
    {"phones", "emails", "addresses", "passwords", "secrets", "passports", "cards"}
)
# {"field": "phone", "new": "+998…"} — maydon nomi qiymat sifatida kelgan holat
_NAME_KEYS = frozenset({"field", "name", "attribute", "key", "path"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[a-z]+")


def _key_words(key: str) -> set[str]:
    return set(_WORD.findall(_CAMEL_BOUNDARY.sub("_", key).lower()))


def _is_sensitive(name: str) -> bool:
    words = _key_words(name)
    return bool(words & _FORBIDDEN_WORDS or words & _FORBIDDEN_PLURALS)


class AuditDiffError(ValueError):
    pass


def _check_diff(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive(str(key)):
                raise AuditDiffError(f"audit diff'da taqiqlangan maydon: {path}{key}")
            if str(key) in _NAME_KEYS and isinstance(item, str) and _is_sensitive(item):
                raise AuditDiffError(f"audit diff'da taqiqlangan maydon qiymati: {path}{key}={item}")
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
                diff=to_json_compatible(diff) if diff is not None else None,  # Decimal, UUID, sana
                trace_id=get_trace_id(),
            )
        )
        await db.flush()
