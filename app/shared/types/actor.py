"""ActorContext — so'rov kim nomidan va qaysi shop uchun bajarilayotgani (10 §3).

Faqat server tomonida yig'iladi (S0-04: JWT + DB'dagi a'zolik). `shop_id` hech qachon klientdan olinmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

ActorType = Literal["STAFF", "AI_AGENT", "CUSTOMER", "SYSTEM", "PLATFORM"]
Surface = Literal["shop", "storefront", "webhooks", "platform", "worker"]


@dataclass(frozen=True)
class ActorContext:
    actor_type: ActorType
    actor_id: UUID | None
    shop_id: UUID | None
    surface: Surface
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    branch_ids: frozenset[UUID] | None = None  # None — barcha filiallar
    locale: str = "uz"
    membership_id: UUID | None = None

    @classmethod
    def system(cls, shop_id: UUID | None = None) -> ActorContext:
        """Fon vazifalari va rejali ishlar uchun (actor_id yo'q)."""
        return cls(actor_type="SYSTEM", actor_id=None, shop_id=shop_id, surface="worker")
