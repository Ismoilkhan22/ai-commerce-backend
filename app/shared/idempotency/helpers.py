"""Idempotent yozish endpoint'i uchun yordamchi (K-06, 11 §5).

    return await run_idempotent(db, ctx.actor.shop_id, "shops.branch.create", key, body, produce)

Takroriy so'rov — saqlangan javob (aynan bir xil); boshqa tana — 409; parallel dublikat — 409.

Javobda sir bo'lsa (taklif yoki parol tiklash havolasi), u bazaga YOZILMAYDI: `stored` sirsiz qismni
qaytaradi, takroriy so'rovda esa `on_replay` yangi havola beradi (eskisi bekor — faqat oxirgisi ishlaydi).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.idempotency.store import IdempotencyStore, request_hash
from app.shared.serialization import to_json_compatible

_store = IdempotencyStore()
# Faqat lokal/test standarti; ilova ishga tushganda `configure_request_hash_key` sozlamadan o'rnatadi
DEV_HASH_KEY = b"dev-only-idempotency-hash-key-change-me"
_hash_key = DEV_HASH_KEY


def configure_request_hash_key(key: bytes) -> None:
    """`IDEMPOTENCY_HASH_KEY` — barmoq izi kaliti (create_app chaqiradi)."""
    global _hash_key  # jarayon bo'yicha bitta sozlama, ishga tushishda bir marta
    _hash_key = key


def _jsonable(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else to_json_compatible(value)


async def run_idempotent[T](
    db: AsyncSession,
    shop_id: UUID | None,
    operation: str,
    key: str,
    request_body: BaseModel | dict[str, Any] | None,
    produce: Callable[[], Awaitable[T]],
    *,
    stored: Callable[[T], Any] | None = None,
    on_replay: Callable[[Any], Awaitable[Any]] | None = None,
    status: int = 200,
) -> T | Any:
    body = _jsonable(request_body) if request_body is not None else None
    req_hash = request_hash("POST", operation, body, _hash_key)
    previous = await _store.begin(db, shop_id, operation, key, req_hash)
    if previous is not None:
        return await on_replay(previous.body) if on_replay else previous.body
    result = await produce()
    await _store.complete(
        db, shop_id, operation, key, status, _jsonable(stored(result) if stored else result)
    )
    return result
