"""FastAPI ilovasi: lifespan, middleware zanjiri, DomainManifest'lardan router'lar (02 §2).

Biznes logika yo'q. Bu modul composition root — domenlarni import qila oladi.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from app.config.logging import configure_logging
from app.config.settings import Settings, get_settings
from app.dependencies import (
    get_ai_conversations,
    get_catalog_query,
    get_chat_availability,
    get_conversation_lookup,
    get_conversation_orders,
    get_import_stock_results,
    get_import_stock_source,
    get_order_query,
    get_reporting_sources,
    get_sales_drafts,
    get_stock_query,
    get_support_commerce,
)
from app.domains.catalog.providers import build_catalog_services
from app.domains.commerce.providers import build_commerce_services
from app.domains.messaging.common import MessagingConfig
from app.domains.messaging.providers import build_messaging_services
from app.domains.reporting.providers import build_reporting_services
from app.domains.sales_ai.providers import build_sales_ai_services
from app.domains.storefront.providers import build_storefront_services
from app.domains.support.providers import build_support_services
from app.platform.audit.services.audit_service import AuditService
from app.platform.audit.services.denied import DeniedAttemptRecorder
from app.platform.auth.passwords import PasswordHasher
from app.platform.auth.services.auth_service import AuthService
from app.platform.llm.factory import build_router
from app.platform.llm.providers.fake import FakeProvider
from app.platform.llm.router import LlmRouter
from app.platform.notifications.providers import build_notification_services
from app.platform.notifications.telegram import build_sender
from app.platform.shops.services.platform_queries import PlatformQueryService
from app.platform.shops.services.shop_service import ShopService
from app.platform.staff.permissions import PermissionRegistry
from app.platform.staff.services.platform_team_service import PlatformTeamService
from app.platform.staff.services.staff_service import StaffService
from app.platform.storage.config import build_file_storage
from app.platform.storage.services.file_service import FileService
from app.platform.storage.signing import UrlSigner
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.cache import Cache, MemoryCache, RedisCache
from app.shared.db.encryption import configure_pii
from app.shared.db.session import Database
from app.shared.errors.handlers import register_exception_handlers
from app.shared.i18n.middleware import I18nMiddleware
from app.shared.idempotency.helpers import configure_request_hash_key
from app.shared.observability.health import router as health_router
from app.shared.ratelimit import MemoryRateLimiter, RedisRateLimiter
from app.shared.realtime import MemoryBroker, RealtimeBroker, RedisBroker
from app.shared.request_guard import RequestGuardMiddleware
from app.shared.storefront_cors import PanelCorsMiddleware, StorefrontCorsMiddleware
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
    configure_pii(settings.pii_keyring())  # xaridor telefoni va manzili kalitlari (26 §4)
    # Redis (rate limit + kesh) — ulanish birinchi so'rovda ochiladi; testlarda ikkalasi ham xotirada
    redis: Redis | None = (
        Redis.from_url(settings.redis_url) if settings.rate_limit_backend == "redis" else None
    )
    cache: Cache = RedisCache(redis) if redis is not None else MemoryCache()
    # Realtime (WS ticket, signal) — Redis db2 (08 §3); testlarda xotirada, bitta jarayon
    realtime_redis: Redis | None = Redis.from_url(settings.realtime_redis_url) if redis is not None else None
    realtime: RealtimeBroker = RedisBroker(realtime_redis) if realtime_redis is not None else MemoryBroker()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_config())
        app.state.db = database
        app.state.readiness_checks = {"postgres": database.ping}
        if redis is not None:
            app.state.rate_limiter = RedisRateLimiter(redis, scale=settings.rate_limit_scale)
            app.state.readiness_checks["redis"] = redis.ping
        else:
            app.state.rate_limiter = MemoryRateLimiter(scale=settings.rate_limit_scale)
        try:
            yield
        finally:
            await database.dispose()
            queue = getattr(app.state, "task_queue", None)  # dead-letter replay ochgan arq pool (bo'lsa)
            if queue is not None and hasattr(queue, "pool"):
                await queue.pool.aclose()
            if redis is not None:
                await redis.aclose()
            if realtime_redis is not None:
                await realtime_redis.aclose()

    app = FastAPI(
        title="AI Commerce OS API",
        version="0.0.1",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        # Frontend client shu fayldan generatsiya qilinadi (21 §4)
        openapi_url=None if settings.is_production else "/api/v1/openapi.json",
        generate_unique_id_function=_operation_id,
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    manifests = discover_manifests() if manifests is None else manifests
    mount_manifests(app, manifests)
    from app.workers.reconcile import WORKER_JOBS

    app.state.scheduled_jobs = [  # /platform/jobs: hech ishlamagan ish ham ko'rinsin (QA 5a I2)
        (job.name, job.every_seconds, job.cron)
        for job in [*(j for m in manifests for j in m.scheduled_jobs), *WORKER_JOBS]
    ]
    app.state.cache = cache
    app.state.realtime_heartbeat_seconds = settings.realtime_heartbeat_seconds
    app.state.ws_allowed_origins = [o.rstrip("/") for o in settings.cors_origins]  # WS Origin (QA 5a I1)
    # Dead-letter "qayta yuborish" — API'dan darhol navbatga (QA 5a F1); xotira rejimida RecordingQueue
    app.state.arq_redis_url = settings.arq_redis_url if redis is not None else None
    app.state.trusted_proxies = settings.proxy_networks()  # rate limit uchun mijoz IP'si (QA M04 F3)
    app.state.storefront_ssr_read_limit = settings.storefront_ssr_read_limit_per_minute
    configure_request_hash_key(settings.idempotency_hash_key.get_secret_value().encode())
    wire_services(app.state, settings, manifests, cache, realtime)

    # Starlette middleware'larni teskari tartibda o'raydi: oxirgi qo'shilgan — eng tashqi.
    app.add_middleware(RequestGuardMiddleware)  # eng ichkisi: NUL/NaN, JSON chegarasi, deadlock retry
    app.add_middleware(I18nMiddleware, default_locale=settings.default_locale)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        PanelCorsMiddleware,  # cookie bilan; sayt yo'llarida ishlamaydi (QA M04 F1)
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
    # Eng tashqi: shop sayti (subdomenlar) — cookie'siz alohida CORS; panellar CORS'iga ta'sir qilmaydi
    app.add_middleware(StorefrontCorsMiddleware, origin_regex=settings.storefront_cors_origin_regex)
    return app


def _operation_id(route: APIRoute) -> str:
    """OpenAPI operationId (`auth_login`, `staff_invite_member`) — Swagger va frontend client uchun."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


def wire_services(
    state: Any,
    settings: Settings,
    manifests: Sequence[DomainManifest],
    cache: Cache,
    realtime: RealtimeBroker,
) -> None:
    """Platform va domen servislari bir marta yaratiladi (stateless) va `state` da turadi.

    `state` — API'da `app.state`, fon jarayonlarida `app.workers.runtime` yig'gan holat (bir xil servislar).
    """
    auth_config = settings.auth_config()
    state.cache = cache
    state.realtime = realtime
    bot_token = settings.platform_telegram_bot_token
    state.notifications = build_notification_services(
        build_sender(bot_token.get_secret_value() if bot_token else None),
        bot_username=settings.platform_telegram_bot_username,
        bot_configured=bot_token is not None,
        webhook_secret=(
            settings.platform_telegram_webhook_secret.get_secret_value()
            if settings.platform_telegram_webhook_secret
            else None
        ),
    )
    audit = AuditService()
    state.denied_recorder = DeniedAttemptRecorder(audit)  # 403 → `<resurs>.denied` audit yozuvi (TC-029)
    use = UseService(RulesRegistry.from_manifests(manifests), audit)
    hasher = PasswordHasher(
        auth_config.argon2_time_cost, auth_config.argon2_memory_kib, auth_config.argon2_parallelism
    )
    staff = StaffService(use, audit, auth_config)
    state.auth_config = auth_config
    state.permissions = PermissionRegistry.from_manifests(manifests)
    state.use = use
    state.auth_service = AuthService(auth_config, hasher, audit, use)
    state.staff_service = staff
    state.shop_service = ShopService(use, audit, auth_config, staff, get_order_query())
    state.platform_queries = PlatformQueryService()
    state.platform_team = PlatformTeamService(audit, auth_config)
    files = FileService(
        storage=build_file_storage(settings.storage_config()),
        signer=UrlSigner(auth_config.jwt_secret),
        audit=audit,
        public_base_url=settings.public_files_url,
        signed_ttl=timedelta(seconds=settings.signed_url_ttl_seconds),
    )
    state.file_service = files
    state.catalog = build_catalog_services(use, audit, files, state.permissions, get_import_stock_results())
    storefront = build_storefront_services(
        use,
        audit,
        files,
        cache,
        get_catalog_query(),
        get_stock_query(),
        secret=auth_config.jwt_secret,
        site_url_template=settings.storefront_public_url,
        chat=get_chat_availability(),
    )
    state.storefront = storefront
    state.commerce = build_commerce_services(
        use,
        audit,
        files,
        get_catalog_query(),
        get_stock_query(),
        storefront.gate,
        get_import_stock_source(),
        state.permissions,
        storefront_public_url=settings.storefront_public_url,
        conversations=get_conversation_lookup(),
    )
    # 7b: kafolat murojaatlari — sotuv qatori va ombor yozuvi commerce port'i orqali (DEC-126, DEC-145)
    state.support = build_support_services(
        use,
        audit,
        files,
        get_catalog_query(),
        get_conversation_lookup(),
        get_support_commerce(state.commerce),
    )
    # 7c: hisobot read model'lari — katalog o'lchami va qayta qurish manbasi port'lar orqali
    state.reporting = build_reporting_services(get_catalog_query(), get_reporting_sources())
    # 6b: AI sotuvchi — LLM provayderi sozlamadan (LLM_PROVIDER), suhbat va qoralamalar port'lar orqali
    main_router = llm_router(settings)
    state.sales_ai = build_sales_ai_services(
        main_router,
        audit,
        cache,
        get_catalog_query(),
        get_stock_query(),
        allow_fake=not settings.is_production,
        debounce_s=settings.ai_debounce_seconds,
        eval_routers=eval_router_factory(settings, main_router),
        git_sha=settings.app_version,
        gemini_free=settings.gemini_tier != "paid",
    )
    state.messaging = build_messaging_services(
        use,
        audit,
        files,
        state.notifications.customer_templates,
        get_conversation_orders(state.commerce),
        storefront.gate,
        messaging_config(settings),
        ai_gate=state.sales_ai.gate,
        catalog=get_catalog_query(),
        stock=get_stock_query(),
        llm=main_router,
        ai_budget=state.sales_ai.gate,
    )
    state.sales_ai.connect(get_ai_conversations(state.messaging), get_sales_drafts(state.commerce))


def llm_router(settings: Settings) -> LlmRouter:
    gemini, anthropic = settings.gemini_api_key, settings.anthropic_api_key
    return build_router(
        settings.llm_provider,
        gemini_api_key=gemini.get_secret_value() if gemini else None,
        anthropic_api_key=anthropic.get_secret_value() if anthropic else None,
        gemini_model=settings.gemini_model,
        backoff_s=settings.llm_retry_backoff_seconds,
    )


def eval_router_factory(
    settings: Settings, main_router: LlmRouter
) -> Callable[[str, Mapping[str, Sequence[str]] | None], LlmRouter]:
    """6c baholash: provayder/model bo'yicha router (keshlanadi). Asosiy provayder va standart model —
    jonli router o'zi (FakeProvider testlarda skriptlanadi); `fake` — har doim o'sha FakeProvider bilan."""
    gemini, anthropic = settings.gemini_api_key, settings.anthropic_api_key
    shared_fake = main_router.provider if isinstance(main_router.provider, FakeProvider) else None
    cache: dict[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], LlmRouter] = {}

    def build(provider: str, overrides: Mapping[str, Sequence[str]] | None) -> LlmRouter:
        if provider == settings.llm_provider and not overrides:
            return main_router
        key = (provider, tuple(sorted((k, tuple(v)) for k, v in (overrides or {}).items())))
        if key not in cache:
            cache[key] = build_router(
                provider,
                gemini_api_key=gemini.get_secret_value() if gemini else None,
                anthropic_api_key=anthropic.get_secret_value() if anthropic else None,
                gemini_model=settings.gemini_model,
                model_overrides=overrides,
                backoff_s=settings.llm_retry_backoff_seconds,
                fake=shared_fake,
            )
        return cache[key]

    return build


def messaging_config(settings: Settings) -> MessagingConfig:
    secret, verify = settings.instagram_app_secret, settings.instagram_verify_token
    return MessagingConfig(
        webhook_base_url=settings.messaging_webhook_base_url,
        telegram_mode=settings.effective_telegram_mode,
        instagram_enabled=settings.feature_channel_instagram_dm,
        instagram_app_id=settings.instagram_app_id,
        instagram_oauth_config_id=settings.instagram_oauth_config_id,
        oauth_state_key=settings.jwt_secret.get_secret_value(),
        app_public_url=settings.app_public_url,
        instagram_app_secret=secret.get_secret_value() if secret else None,
        instagram_verify_token=verify.get_secret_value() if verify else None,
        storefront_public_url=settings.storefront_public_url,
        telegram_test_tokens=settings.app_env in ("local", "test"),
    )


app = create_app()
