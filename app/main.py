"""FastAPI ilovasi: lifespan, middleware zanjiri, DomainManifest'lardan router'lar (02 §2).

Biznes logika yo'q. Bu modul composition root — domenlarni import qila oladi.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.config.logging import configure_logging
from app.config.settings import Settings, get_settings
from app.shared.db.session import Database
from app.shared.errors.handlers import register_exception_handlers
from app.shared.i18n.middleware import I18nMiddleware
from app.shared.observability.health import router as health_router
from app.shared.tracing.middleware import RequestContextMiddleware
from app.shared.types.manifest import SURFACE_PREFIXES, DomainManifest, Surface

MANIFEST_SOURCES = (("app.platform", "MODULE_MANIFEST"), ("app.domains", "DOMAIN_MANIFEST"))


class RouteConflictError(RuntimeError):
    """Ikki modul bir xil yo'l + metodni e'lon qildi (TC-API-07)."""


def discover_manifests() -> list[DomainManifest]:
    manifests: list[DomainManifest] = []
    for package_name, attribute in MANIFEST_SOURCES:
        package = importlib.import_module(package_name)
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
            if not info.ispkg:
                continue
            module = importlib.import_module(f"{package_name}.{info.name}")
            manifest = getattr(module, attribute, None)
            if isinstance(manifest, DomainManifest):
                manifests.append(manifest)
    return manifests


def _check_route_conflicts(manifests: Iterable[DomainManifest]) -> None:
    owners: dict[tuple[str, str], str] = {}
    for manifest in manifests:
        for surface, router in manifest.routers.items():
            for route in router.routes:
                if not isinstance(route, APIRoute):
                    continue
                path = SURFACE_PREFIXES[surface] + router.prefix + route.path
                for method in route.methods or ():
                    key = (method, path)
                    if key in owners and owners[key] != manifest.name:
                        raise RouteConflictError(
                            f"{method} {path}: {owners[key]!r} va {manifest.name!r} ikkalasi e'lon qilgan"
                        )
                    owners[key] = manifest.name


def mount_manifests(app: FastAPI, manifests: Sequence[DomainManifest]) -> None:
    _check_route_conflicts(manifests)
    surfaces: dict[Surface, APIRouter] = {}
    for manifest in manifests:
        for surface, router in manifest.routers.items():
            # Surface auth dependency'lari S0-04 da shu yerda qo'shiladi (10 §5)
            surface_router = surfaces.setdefault(surface, APIRouter(prefix=SURFACE_PREFIXES[surface]))
            surface_router.include_router(router)
    for surface_router in surfaces.values():
        app.include_router(surface_router)


def create_app(
    settings: Settings | None = None, manifests: Sequence[DomainManifest] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "local")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_config())
        app.state.db = database
        app.state.readiness_checks = {"postgres": database.ping}  # S0-06: redis
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title="AI Commerce OS API",
        version="0.0.1",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    mount_manifests(app, discover_manifests() if manifests is None else manifests)

    # Starlette middleware'larni teskari tartibda o'raydi: oxirgi qo'shilgan — eng tashqi.
    app.add_middleware(I18nMiddleware, default_locale=settings.default_locale)
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
