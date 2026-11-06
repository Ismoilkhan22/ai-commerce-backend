"""Idempotency (K-06, 12 §9): bir xil `Idempotency-Key` bilan so'rov ikki marta bajarilmaydi.

Yozuv biznes o'zgarishi bilan **bitta tranzaksiyada**: COMMIT bo'lmasa, kalit ham yo'q.

Bir vaqtda kelgan dublikat KUTMAYDI (founder, 2026-10-23): tranzaksiya qulfi
(`pg_try_advisory_xact_lock`) band bo'lsa — darhol 409 REQUEST_IN_PROGRESS. Klient kutib qayta yuboradi:
- birinchisi muvaffaqiyatli bo'lsa — saqlangan javobni oladi;
- birinchisi yiqilgan yoki server o'chgan bo'lsa — tranzaksiya bekor, qulf ochiq:
  so'rov yangidek bajariladi.

    async with db.begin():
        stored = await idempotency.begin(db, shop_id, "order.confirm", key, request_hash)
        if stored:
            return stored.body          # takroriy so'rov
        ... biznes o'zgarishi ...
        await idempotency.complete(db, shop_id, "order.confirm", key, 200, body)

So'rov "barmoq izi" (`request_hash`) — server kaliti bilan HMAC (`h1:` + hex). Oddiy SHA-256 bo'lsa, bazani
o'qigan odam tana ichidagi telefonni oflayn tanlab topa olardi (QA M04 F2): boshqa maydonlar buyurtmada ochiq
turadi, telefon esa ~10^7 variant. Kalitsiz eski qatorlarni `platform_0008` o'chirgan, CHECK endi faqat `h1:`
ga ruxsat beradi.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.errors.base import IdempotencyKeyReusedError, RequestInProgressError
from app.shared.idempotency.models import IdempotencyKey
from app.shared.serialization import to_json_compatible

NIL_SHOP_ID = UUID(int=0)
DEFAULT_TTL = timedelta(hours=24)
HASH_PREFIX = "h1:"  # kalitli barmoq izi (HMAC-SHA256)


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any


def _canonical(method: str, path: str, body: Any) -> bytes:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"{method.upper()} {path}\n{canonical}".encode()


def request_hash(method: str, path: str, body: Any, key: bytes) -> str:
    """Kalitli barmoq izi: kalitsiz uni tana bilan solishtirib bo'lmaydi."""
    return HASH_PREFIX + hmac.new(key, _canonical(method, path, body), hashlib.sha256).hexdigest()


class IdempotencyStore:
    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self.ttl = ttl

    async def begin(
        self,
        db: AsyncSession,
        shop_id: UUID | None,
        operation: str,
        key: str,
        req_hash: str,
    ) -> StoredResponse | None:
        """Yangi kalit — None (davom eting). Takroriy — saqlangan javob. Boshqa tana — 409."""
        scope = shop_id or NIL_SHOP_ID
        now = datetime.now(UTC)
        # Bloklamaydigan qulf: shu kalit bilan boshqa so'rov ishlayotgan bo'lsa — kutmasdan 409.
        # Qulf tranzaksiya tugashi bilan (COMMIT yoki ROLLBACK) o'zi ochiladi.
        locked = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"idempotency:{scope}:{operation}:{key}"},
        )
        if not locked.scalar_one():
            raise RequestInProgressError("A request with this Idempotency-Key is in progress")
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
        if not hmac.compare_digest(row.request_hash, req_hash):
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
            .values(
                response_status=status, response_body=to_json_compatible(body)
            )  # javob bilan aynan bir xil
        )
