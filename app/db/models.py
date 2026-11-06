"""Har schema uchun ORM modellari qaysi modullarda ekani — Alembic autogenerate shu yerdan topadi.

Composition root (domenlarni import qila oladi). Yangi model moduli qo'shilganda ro'yxatga yoziladi.
"""

from __future__ import annotations

import importlib

from sqlalchemy import MetaData

from app.shared.db.base import Base

MODEL_MODULES: dict[str, tuple[str, ...]] = {
    "platform": (
        "app.platform.use.models.orm",
        "app.shared.idempotency.models",
        "app.platform.shops.models.orm",
        "app.platform.staff.models.orm",
        "app.platform.auth.models.orm",
        "app.platform.storage.models.orm",
        "app.platform.jobs.models.orm",
        "app.platform.notifications.models.orm",
        "app.shared.events.models",  # outbox_events, consumer_receipts (har outbox schemasida)
    ),
    "audit": ("app.platform.audit.models.orm",),
    "catalog": (
        "app.domains.catalog.products.models.orm",
        "app.domains.catalog.pricing.models.orm",
        "app.domains.catalog.pc_specs.models.orm",
        "app.domains.catalog.imports.models.orm",
        "app.shared.events.models",
    ),
    "commerce": (
        "app.domains.commerce.inventory.models.orm",
        "app.domains.commerce.quick_sales.models.orm",
        "app.domains.commerce.orders.models.orm",
        "app.shared.events.models",
    ),
    "messaging": ("app.domains.messaging.models.orm", "app.shared.events.models"),
    "sales_ai": (),
    "storefront": ("app.domains.storefront.models.orm", "app.shared.events.models"),
    "support": (),
    "reporting": (),
}


def load_metadata(schema: str) -> MetaData:
    for module in MODEL_MODULES[schema]:
        importlib.import_module(module)
    return Base.metadata
