"""platform/storage moduli: fayl yuklash va berish (S0-08)."""

from __future__ import annotations

from app.platform.storage.api.public_routes import router as public_router
from app.platform.storage.api.routes import router
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="storage",
    schema_name="platform",
    routers={"shop": router, "public": public_router},
)
