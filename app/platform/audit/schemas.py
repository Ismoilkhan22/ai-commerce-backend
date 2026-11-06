"""Egaga mo'ljallangan "O'zgarishlar tarixi" (M20): amal kodi va o'zgargan maydon NOMLARI — qiymatlar yo'q."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ShopAuditItem(BaseModel):
    id: UUID
    occurred_at: datetime
    action: str  # "commerce.order.confirmed", "orders.denied" — frontend i18n orqali tarjima qiladi
    actor_type: str  # STAFF | AI | CUSTOMER | SYSTEM | PLATFORM
    actor_id: UUID | None
    actor_name: str | None
    entity_type: str
    entity_id: UUID | None
    reason: str | None
    changed_fields: list[str]


class ShopAuditList(BaseModel):
    items: list[ShopAuditItem]
    next_cursor: str | None
    has_more: bool
