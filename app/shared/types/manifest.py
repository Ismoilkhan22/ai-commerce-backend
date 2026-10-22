"""DomainManifest — domen (yoki platform moduli) o'zini ilovaga qanday ulashini e'lon qiladi (02 §2).

`main.py` `app/domains/*` dagi `DOMAIN_MANIFEST` va `app/platform/*` dagi `MODULE_MANIFEST` larni
avtomatik topadi va router'larni surface prefiksi bilan ulaydi.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter

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
    # Keyingi slice'larda to'ldiriladi: S0-07 (state rules), S0-06 (subscribers, jobs), S0-04 (permissions)
    state_machine_rules: Sequence[Any] = ()
    event_subscribers: Sequence[Callable[..., Any]] = ()
    scheduled_jobs: Sequence[Any] = ()
    permissions: Sequence[str] = ()
    privacy_handlers: Sequence[Any] = ()
