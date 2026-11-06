"""Shop egasi/menejeri uchun o'zgarishlar tarixi (M20, `audit.view`).

Faqat shu shopning yozuvlari (RLS + aniq `shop_id` sharti). Qiymatlar ko'rsatilmaydi — amal kodi va o'zgargan
maydon nomlari (07 §4.2 qoidasi bilan bir xil). Platforma xodimining ichki izohi (`reason`) egaga berilmaydi.
CSV: formula belgisi bilan boshlangan matn oldiga `'` (CSV-injection), shaxsiy ma'lumot yo'q — xodim ismi ham
yo'q (faqat `actor_id`).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models.orm import AuditEntry
from app.platform.audit.schemas import ShopAuditItem, ShopAuditList
from app.platform.staff.models.orm import Principal
from app.shared.errors.base import ValidationError
from app.shared.pagination import DEFAULT_LIMIT, decode_cursor, encode_cursor

EXPORT_MAX_ROWS = 5000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"


def changed_fields(diff: Any) -> list[str]:
    """Diff'dan faqat maydon nomlari: {"changed": [...]} yoki {"name": {"old", "new"}} ko'rinishlari."""
    if not isinstance(diff, dict):
        return []
    if set(diff) == {"changed"} and isinstance(diff["changed"], list):
        return sorted(str(name) for name in diff["changed"])
    return sorted(str(key) for key in diff)


def _bad_cursor() -> ValidationError:
    return ValidationError(
        "Cursor is invalid", fields=[{"field": "cursor", "code": "invalid_format", "params": {}}]
    )


def safe_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    return "'" + text if text.lstrip(" ").startswith(_FORMULA_START) else text


class ShopAuditQueries:
    @staticmethod
    def _conditions(
        shop_id: UUID,
        *,
        actor_id: UUID | None,
        entity_type: str | None,
        action: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [AuditEntry.shop_id == shop_id]
        if actor_id:
            conditions.append(AuditEntry.actor_id == actor_id)
        if entity_type:
            conditions.append(AuditEntry.entity_type == entity_type)
        if action:
            conditions.append(AuditEntry.action.startswith(action, autoescape=True))
        if date_from:
            conditions.append(AuditEntry.occurred_at >= date_from)
        if date_to:
            conditions.append(AuditEntry.occurred_at < date_to)
        return conditions

    async def page(
        self,
        db: AsyncSession,
        shop_id: UUID,
        *,
        actor_id: UUID | None = None,
        entity_type: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> ShopAuditList:
        conditions = self._conditions(
            shop_id,
            actor_id=actor_id,
            entity_type=entity_type,
            action=action,
            date_from=date_from,
            date_to=date_to,
        )
        if cursor:
            values = decode_cursor(cursor)
            try:
                at, last_id = datetime.fromisoformat(str(values["t"])), UUID(str(values["id"]))
            except (KeyError, ValueError) as exc:
                raise _bad_cursor() from exc
            conditions.append(
                or_(AuditEntry.occurred_at < at, and_(AuditEntry.occurred_at == at, AuditEntry.id < last_id))
            )
        rows = (
            (
                await db.execute(
                    select(AuditEntry)
                    .where(*conditions)
                    .order_by(AuditEntry.occurred_at.desc(), AuditEntry.id.desc())
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page, has_more = list(rows[:limit]), len(rows) > limit
        next_cursor = (
            encode_cursor({"t": page[-1].occurred_at.isoformat(), "id": str(page[-1].id)})
            if has_more and page
            else None
        )
        names = await self._names(db, page)
        return ShopAuditList(
            items=[
                ShopAuditItem(
                    id=r.id,
                    occurred_at=r.occurred_at,
                    action=r.action,
                    actor_type=r.actor_type,
                    actor_id=r.actor_id,
                    actor_name=names.get(r.actor_id) if r.actor_id and r.actor_type != "PLATFORM" else None,
                    entity_type=r.entity_type,
                    entity_id=r.entity_id,
                    reason=None if r.actor_type == "PLATFORM" else r.reason,
                    changed_fields=changed_fields(r.diff),
                )
                for r in page
            ],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def export_csv(
        self,
        db: AsyncSession,
        shop_id: UUID,
        *,
        actor_id: UUID | None = None,
        entity_type: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> str:
        conditions = self._conditions(
            shop_id,
            actor_id=actor_id,
            entity_type=entity_type,
            action=action,
            date_from=date_from,
            date_to=date_to,
        )
        rows = (
            (
                await db.execute(
                    select(AuditEntry)
                    .where(*conditions)
                    .order_by(AuditEntry.occurred_at.desc(), AuditEntry.id.desc())
                    .limit(EXPORT_MAX_ROWS)
                )
            )
            .scalars()
            .all()
        )
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(
            [
                "occurred_at",
                "actor_type",
                "actor_id",
                "action",
                "entity_type",
                "entity_id",
                "reason",
                "fields",
            ]
        )
        for r in rows:
            writer.writerow(
                safe_cell(v)
                for v in (
                    r.occurred_at,
                    r.actor_type,
                    r.actor_id,
                    r.action,
                    r.entity_type,
                    r.entity_id,
                    None if r.actor_type == "PLATFORM" else r.reason,
                    " ".join(changed_fields(r.diff)),
                )
            )
        return BOM + out.getvalue()

    @staticmethod
    async def _names(db: AsyncSession, rows: Sequence[AuditEntry]) -> dict[UUID, str]:
        wanted = {r.actor_id for r in rows if r.actor_id and r.actor_type != "PLATFORM"}
        if not wanted:
            return {}
        result = await db.execute(select(Principal.id, Principal.full_name).where(Principal.id.in_(wanted)))
        return dict(result.all())
