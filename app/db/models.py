"""Har schema uchun ORM modellari qaysi modullarda ekani — Alembic autogenerate shu yerdan topadi.

Composition root (domenlarni import qila oladi). Yangi model moduli qo'shilganda ro'yxatga yoziladi.
"""

from __future__ import annotations

import importlib

from sqlalchemy import MetaData

from app.shared.db.base import Base

MODEL_MODULES: dict[str, tuple[str, ...]] = {
    "platform": ("app.platform.use.models.orm", "app.shared.idempotency.models"),
    "audit": ("app.platform.audit.models.orm",),
    "catalog": (),
    "commerce": (),
    "messaging": (),
    "sales_ai": (),
    "storefront": (),
    "support": (),
    "reporting": (),
}


def load_metadata(schema: str) -> MetaData:
    for module in MODEL_MODULES[schema]:
        importlib.import_module(module)
    return Base.metadata
