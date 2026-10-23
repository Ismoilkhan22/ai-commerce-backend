"""Idempotency (K-06, 12 §9): bir xil `Idempotency-Key` bilan so'rov ikki marta bajarilmaydi.

Yozuv biznes o'zgarishi bilan **bitta tranzaksiyada**: COMMIT bo'lmasa, kalit ham yo'q.
Bir vaqtda kelgan ikkinchi so'rov unikal indeksda birinchisi tugashini kutadi, so'ng saqlangan javobni oladi.

    async with db.begin():
        stored = await idempotency.begin(db, shop_id, "order.confirm", key, request_hash)
        if stored:
            return stored.body          # takroriy so'rov
        ... biznes o'zgarishi ...
        await idempotency.complete(db, shop_id, "order.confirm", key, 200, body)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.errors.base import IdempotencyKeyReusedError
from app.shared.idempotency.models import IdempotencyKey

NIL_SHOP_ID = UUID(int=0)
DEFAULT_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any


def request_hash(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(f"{method.upper()} {path}\n{canonical}".encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self.ttl = ttl

    async def begin(
        self, db: AsyncSession, shop_id: UUID | None, operation: str, key: str, req_hash: str
    ) -> StoredResponse | None:
        """Yangi kalit — None (davom eting). Takroriy — saqlangan javob. Boshqa tana — 409."""
        scope = shop_id or NIL_SHOP_ID
        now = datetime.now(UTC)
        inserted = await db.execute(
            insert(IdempotencyKey)
            .values(
                shop_id=scope, operation=operation, key=key, request_hash=req_hash, expires_at=now + self.ttl
            )
            .on_conflict_do_nothing()
            .returning(IdempotencyKey.key)
        )
        if inserted.scalar_one_or_none() is not None:
            return None

        row = (
            await db.execute(
                select(IdempotencyKey)
                .where(
                    IdempotencyKey.shop_id == scope,
                    IdempotencyKey.operation == operation,
                    IdempotencyKey.key == key,
                )
                .with_for_update()
            )
        ).scalar_one()
        if row.expires_at <= now:
            # Muddati o'tgan kalit — yangidek ishlatiladi
            row.request_hash, row.response_status, row.response_body = req_hash, None, None
            row.expires_at = now + self.ttl
            await db.flush()
            return None
        if row.request_hash != req_hash:
            raise IdempotencyKeyReusedError("Idempotency key reused with a different request")
        if row.response_status is None:
            # Birinchi so'rov COMMIT qildi, lekin javob saqlamagan — dasturchi xatosi (complete yo'q)
            raise RuntimeError(f"idempotency: {operation} uchun javob saqlanmagan")
        return StoredResponse(row.response_status, row.response_body)

    async def complete(
        self, db: AsyncSession, shop_id: UUID | None, operation: str, key: str, status: int, body: Any
    ) -> None:
        await db.execute(
            update(IdempotencyKey)
            .where(
                IdempotencyKey.shop_id == (shop_id or NIL_SHOP_ID),
                IdempotencyKey.operation == operation,
                IdempotencyKey.key == key,
            )
            .values(response_status=status, response_body=body)
        )
