"""DomainManifest — domen (yoki platform moduli) o'zini ilovaga qanday ulashini e'lon qiladi (02 §2).

`main.py` `app/domains/*` dagi `DOMAIN_MANIFEST` va `app/platform/*` dagi `MODULE_MANIFEST` larni
avtomatik topadi va router'larni surface prefiksi bilan ulaydi.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter

from app.shared.types.state import StateMachineRule

Surface = Literal["auth", "shop", "storefront", "webhooks", "platform", "public"]

# 11 §2, ADR-024. URL'da domen nomi yo'q.
SURFACE_PREFIXES: dict[Surface, str] = {
    "auth": "/api/v1/auth",
    "shop": "/api/v1/shop",
    "storefront": "/api/v1/storefront/{slug}",
    "webhooks": "/api/v1/webhooks",
    "platform": "/api/v1/platform",
    "public": "/api/v1/public",
}


@dataclass(frozen=True)
class DomainManifest:
    name: str
    schema_name: str | None = None
    routers: dict[Surface, APIRouter] = field(default_factory=dict)
    state_machine_rules: Sequence[StateMachineRule] = ()  # 04, ADR-034
    # Keyingi slice'larda to'ldiriladi: S0-06 (subscribers, jobs), S0-04 (permissions)
    event_subscribers: Sequence[Callable[..., Any]] = ()
    scheduled_jobs: Sequence[Any] = ()
    permissions: Sequence[str] = ()
    privacy_handlers: Sequence[Any] = ()
    # Majburlab (force_transition) o'tib bo'lmaydigan holatlar: pul va qoldiq invarianti (04 §7)
    non_forceable_states: Mapping[str, frozenset[str]] = field(default_factory=dict)
