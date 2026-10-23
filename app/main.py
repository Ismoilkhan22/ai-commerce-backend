"""FastAPI ilovasi: lifespan, middleware zanjiri, DomainManifest'lardan router'lar (02 §2).

Biznes logika yo'q. Bu modul composition root — domenlarni import qila oladi.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from app.config.logging import configure_logging
from app.config.settings import Settings, get_settings
from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.passwords import PasswordHasher
from app.platform.auth.services.auth_service import AuthService
from app.platform.shops.services.shop_service import ShopService
from app.platform.staff.permissions import PermissionRegistry
from app.platform.staff.services.staff_service import StaffService
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.db.session import Database
from app.shared.errors.handlers import register_exception_handlers
from app.shared.i18n.middleware import I18nMiddleware
from app.shared.observability.health import router as health_router
from app.shared.ratelimit import MemoryRateLimiter, RedisRateLimiter
from app.shared.tracing.middleware import RequestContextMiddleware
from app.shared.types.manifest import SURFACE_PREFIXES, DomainManifest, Surface

MANIFEST_SOURCES = (("app.platform", "MODULE_MANIFEST"), ("app.domains", "DOMAIN_MANIFEST"))


_PATH_PARAM = re.compile(r"\{[^}]*\}")


class RouteConflictError(RuntimeError):
    """Ikki modul bir xil yo'l + metodni e'lon qildi (TC-API-07)."""


MANIFEST_MODULES = ("manifest", "domain_manifest")


def _manifest_module(package: str) -> Any:
    """Manifest alohida faylda (`manifest.py` / `domain_manifest.py`) — paket __init__ bo'sh qoladi,
    shunda modullar orasida aylanma import bo'lmaydi."""
    for name in MANIFEST_MODULES:
        if importlib.util.find_spec(f"{package}.{name}") is not None:
            return importlib.import_module(f"{package}.{name}")
    return importlib.import_module(package)


def discover_manifests() -> list[DomainManifest]:
    manifests: list[DomainManifest] = []
    for package_name, attribute in MANIFEST_SOURCES:
        package = importlib.import_module(package_name)
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
            if not info.ispkg:
                continue
            module = _manifest_module(f"{package_name}.{info.name}")
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
                # route.path router prefiksini allaqachon o'z ichiga oladi (APIRouter(prefix=...)).
                # Parametr nomi ahamiyatsiz: /orders/{order_id} va /orders/{case_id} — bir xil manzil.
                path = SURFACE_PREFIXES[surface] + route.path
                shape = _PATH_PARAM.sub("{}", path)
                for method in route.methods or ():
                    key = (method, shape)
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
        app.state.readiness_checks = {"postgres": database.ping}
        redis: Redis | None = None
        if settings.rate_limit_backend == "redis":
            redis = Redis.from_url(settings.redis_url)
            app.state.rate_limiter = RedisRateLimiter(redis)
            app.state.readiness_checks["redis"] = redis.ping
        else:
            app.state.rate_limiter = MemoryRateLimiter()
        try:
            yield
        finally:
            await database.dispose()
            if redis is not None:
                await redis.aclose()

    app = FastAPI(
        title="AI Commerce OS API",
        version="0.0.1",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    manifests = discover_manifests() if manifests is None else manifests
    mount_manifests(app, manifests)
    _wire_platform_services(app, settings, manifests)

    # Starlette middleware'larni teskari tartibda o'raydi: oxirgi qo'shilgan — eng tashqi.
    app.add_middleware(I18nMiddleware, default_locale=settings.default_locale)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # refresh cookie
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Request-ID",
            "traceparent",
        ],
        expose_headers=["ETag", "X-Request-ID", "Retry-After"],
    )
    return app


def _wire_platform_services(app: FastAPI, settings: Settings, manifests: Sequence[DomainManifest]) -> None:
    """Platform servislari bir marta yaratiladi (stateless) va app.state'da turadi."""
    auth_config = settings.auth_config()
    audit = AuditService()
    use = UseService(RulesRegistry.from_manifests(manifests), audit)
    hasher = PasswordHasher(
        auth_config.argon2_time_cost, auth_config.argon2_memory_kib, auth_config.argon2_parallelism
    )
    staff = StaffService(use, audit, auth_config)
    app.state.auth_config = auth_config
    app.state.permissions = PermissionRegistry.from_manifests(manifests)
    app.state.use = use
    app.state.auth_service = AuthService(auth_config, hasher, audit, use)
    app.state.staff_service = staff
    app.state.shop_service = ShopService(use, audit, auth_config, staff)


app = create_app()
