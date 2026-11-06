"""Kesh kalitlari (08 §4.1) — boshqacha kalit qurilmaydi.

    cos:v1:shop:{shop_id}:<domain>:<resource>:<variant>
    cos:v1:global:<domain>:<variant>

Shop kalitida `shop_id` prefiksi majburiy: bir shop kaliti boshqasiga hech qachon to'g'ri kelmaydi.
Kalitda foydalanuvchi kiritgan xom matn yo'q — parametrlar normallashtirilib hash'lanadi.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

PREFIX = "cos:v1"


def _digest(params: dict[str, object]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def shop_key(shop_id: UUID, domain: str, resource: str, **params: object) -> str:
    """`cos:v1:shop:{id}:storefront:products:list:<hash>`. Parametrsiz — `...:storefront:site`."""
    base = f"{PREFIX}:shop:{shop_id}:{domain}:{resource}"
    return f"{base}:{_digest(params)}" if params else base


def global_key(domain: str, **params: object) -> str:
    """Shopsiz kalit (masalan `slug → shop_id`): parametrlar hash'lanadi."""
    return f"{PREFIX}:global:{domain}:{_digest(params)}"
