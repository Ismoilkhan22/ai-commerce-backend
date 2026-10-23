"""platform/auth moduli: kirish, tokenlar, sessiyalar, parol (ADR-023)."""

from __future__ import annotations

from app.platform.auth.api.routes import router
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(name="auth", schema_name="platform", routers={"auth": router})
