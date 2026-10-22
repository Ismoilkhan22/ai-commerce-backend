"""PostgreSQL schemalari — har domen o'z schemasida (ADR-035, 07 §3).

Tartib: `platform` → `audit` → qolganlari. `schemas.sql` shu ro'yxat bilan sinxron (test tekshiradi).
"""

from __future__ import annotations

SCHEMAS: tuple[str, ...] = (
    "platform",
    "audit",
    "catalog",
    "commerce",
    "messaging",
    "sales_ai",
    "storefront",
    "support",
    "reporting",
)

RUNTIME_ROLE = "app_runtime"
MIGRATOR_ROLE = "app_migrator"
