"""Ilova sozlamalari (.env). Majburiy qiymat yo'q bo'lsa jarayon ishga tushmaydi (23 §3)."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.platform.auth.config import AuthConfig
from app.platform.storage.config import S3Config, StorageConfig
from app.shared.db.encryption import PiiKeyring, parse_keys
from app.shared.db.session import DatabaseConfig
from app.shared.i18n.locale import Locale

# Faqat lokal muhit uchun standart qiymatlar (.env.example bilan bir xil).
# deploy/docker-compose.yml portlari (5433, 6380) — dasturchining o'z PostgreSQL/Redis'iga tegmaslik uchun
_LOCAL_DB = "postgresql+asyncpg://{user}:{user}@localhost:5433/commerce_os"

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})  # noqa: S104 — taqiqlash uchun ro'yxat
_WEAK_PASSWORDS = frozenset({"postgres", "password", "admin", "secret", "app_runtime", "app_migrator"})
MIN_DB_PASSWORD_LENGTH = 12
_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"  # noqa: S105 — faqat lokal, prod'da rad etiladi
MIN_JWT_SECRET_LENGTH = 32
# Xaridor telefoni va manzili kalitlari (26 §4). Faqat lokal — staging/production'da rad etiladi
_DEV_PII_KEYS = "dev1:ZGV2LW9ubHktcGlpLWtleS1jaGFuZ2UtbWUtMDAwMDA="
_DEV_PII_HMAC_KEY = "ZGV2LW9ubHktcGlpLWhtYWMta2V5LWNoYW5nZS1tZSE="
# Takroriy so'rov jadvalidagi barmoq izi kaliti (QA M04 F2). Faqat lokal — staging/production'da rad etiladi
_DEV_IDEMPOTENCY_HASH_KEY = "dev-only-idempotency-hash-key-change-me"
MIN_HASH_KEY_LENGTH = 32


def _unsafe_db_url_reason(url: str) -> str | None:
    parsed = make_url(url)
    if (parsed.host or "").strip("[]") in _LOCAL_HOSTS:
        return "lokal manzil"
    password = parsed.password or ""
    if password in _WEAK_PASSWORDS or password == parsed.username or len(password) < MIN_DB_PASSWORD_LENGTH:
        return f"zaif parol (kamida {MIN_DB_PASSWORD_LENGTH} belgi, standart qiymat emas)"
    return None


def make_url_host(url: str) -> str | None:
    return urlsplit(url).hostname


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Kuzatuv (09, S0-05): jarayon nomi (logdagi `service`, Sentry tegi) va reliz (git SHA) — deploy beradi.
    # Sentry faqat DSN bo'lsa yoqiladi; PII tozalash — app/config/observability.py
    service_name: str = "api"
    app_version: str = "dev"
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    default_locale: Locale = "uz"

    # PostgreSQL (07 §9–10). app_runtime — NOBYPASSRLS, faqat DML; app_migrator — DDL.
    database_url: str = _LOCAL_DB.format(user="app_runtime")
    database_read_url: str | None = None
    database_migrator_url: str = _LOCAL_DB.format(user="app_migrator")
    db_pool_size: int = 10
    db_max_overflow: int = 5
    # Fon jarayoni (dev worker: outbox + arq + scheduler + polling bitta jarayonda) API'dan ko'proq
    # ulanish ishlatadi — alohida, kattaroq pool (API pool'i o'zgarmaydi)
    worker_db_pool_size: int = Field(default=20, ge=1)
    worker_db_max_overflow: int = Field(default=10, ge=0)
    db_statement_timeout_ms: int = 5_000

    # Redis: db0 kesh va rate limit (08). Testlarda "memory".
    redis_url: str = "redis://localhost:6380/0"
    rate_limit_backend: Literal["redis", "memory"] = "redis"
    # Limitlar shu songa ko'paytiriladi (Redis va xotira — ikkalasida). Faqat local/test: e2e'da hamma brauzer
    # bitta IP'dan kiradi. Staging/production'da 1 dan katta bo'lsa — ishga tushmaydi (QA 5a, (c)).
    # Eski nomi RATE_LIMIT_MEMORY_SCALE ham o'qiladi
    rate_limit_scale: int = Field(
        default=1, ge=1, le=100, validation_alias=AliasChoices("rate_limit_scale", "rate_limit_memory_scale")
    )
    # Fon ishlari navbati (arq) — db1; realtime (WS ticket, pub/sub) — db2 (06 §4.1, 08 §3).
    # rate_limit_backend="memory" bo'lsa realtime ham xotirada (testlar, bitta jarayon)
    arq_redis_url: str = "redis://localhost:6380/1"
    realtime_redis_url: str = "redis://localhost:6380/2"
    realtime_heartbeat_seconds: float = Field(default=25.0, gt=0, le=120)

    # Platforma boti — xodimga Telegram xabari (DEC-129). Token yo'q — xabar yuborilmaydi (faqat log);
    # webhook siri yo'q — /webhooks/platform-telegram o'chiq (404)
    platform_telegram_bot_token: SecretStr | None = None
    platform_telegram_bot_username: str | None = None
    platform_telegram_webhook_secret: SecretStr | None = None

    # Auth (ADR-023, 10 §5)
    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    invite_ttl_hours: int = 72
    password_reset_ttl_hours: int = 24
    app_public_url: str = "http://localhost:3000"
    platform_app_public_url: str = "http://localhost:3001"  # platforma jamoasi havolalari
    cookie_secure: bool = True
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65_536

    # Fayllar (S0-08, ADR-014). Lokal va testda — disk; production'da S3-mos ombor (S0-10, TD-03).
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "var/storage"
    # S3-mos ombor (STORAGE_BACKEND=s3). Ochiq bucket ixtiyoriy: bo'lmasa hamma fayl yopiq bucket'da
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_private_bucket: str | None = None
    s3_public_bucket: str | None = None
    s3_force_path_style: bool = True
    # Ochiq fayllar (mahsulot rasmi) shu manzildan beriladi; prod'da CDN yoki bucket manzili
    public_files_url: str = "http://localhost:8000/api/v1/public/files"
    signed_url_ttl_seconds: int = 300  # yopiq fayl havolasi 5 daqiqa amal qiladi

    # Shop sayti (4-modul). Manzil — shop slug'i bilan: prod'da https://{slug}.platforma.uz
    storefront_public_url: str = "http://{slug}.localhost:3002"
    # Sayt brauzerdan ommaviy API'ni chaqiradi (o'qish, buyurtma so'rovi) — cookie'siz CORS, shu manzillar
    storefront_cors_origin_regex: str = r"^http://([a-z0-9-]+\.)?localhost:3002$"
    # Sayt serverining o'zi (SSR, xaridor IP'sisiz) uchun alohida o'qish chelagi — shop bo'yicha (08 §5)
    storefront_ssr_read_limit_per_minute: int = Field(default=3000, ge=120, le=100_000)

    # Xaridor ma'lumoti shifrlash (26 §4, §9): "id:base64(32 bayt),id2:...". Yangi kalit — ro'yxat oxiriga,
    # keyin `pii_active_key_id` unga o'tkaziladi; eski kalit eski yozuvlarni o'qish uchun qoladi.
    pii_encryption_keys: SecretStr = SecretStr(_DEV_PII_KEYS)
    pii_active_key_id: str = "dev1"
    pii_hmac_key: SecretStr = SecretStr(_DEV_PII_HMAC_KEY)  # telefon bo'yicha qidirish (base64)
    idempotency_hash_key: SecretStr = SecretStr(_DEV_IDEMPOTENCY_HASH_KEY)

    # Kanallar (5b). Telegram webhook manzili — API'ning ochiq manzili (prod: https://api.platforma.uz).
    # Rejim: bo'sh — lokalda polling (ochiq manzil yo'q, worker getUpdates qiladi), boshqa muhitlarda webhook
    messaging_webhook_base_url: str = "http://localhost:8000"
    telegram_mode: Literal["webhook", "polling"] | None = None
    # Instagram Direct — Meta ruxsati kelguncha o'chiq (DEC-116a, flag channel.instagram_dm)
    feature_channel_instagram_dm: bool = False
    instagram_app_secret: SecretStr | None = None
    instagram_verify_token: SecretStr | None = None

    # Mijoz IP'si (rate limit): X-Forwarded-For faqat shu manzillardan kelsa hisobga olinadi (IP yoki CIDR).
    # Lokalda — o'z kompyuteri (sayt serveri va brauzer shu yerda; XFF'ni soxtalash lokalda ataylab mumkin).
    # Prod'da — Nginx va shop sayti serverining ichki manzili (22 §8)
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    # AI sotuvchi (6b, ai/M06-architecture.md §4). Provayder: fake — testlar va kalitsiz dev demo;
    # gemini — lokal (bepul kalit faqat sintetik ma'lumot bilan, A14); anthropic — production tavsiyasi.
    llm_provider: Literal["gemini", "anthropic", "fake"] = "fake"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_tier: Literal["free", "paid"] = "free"
    anthropic_api_key: SecretStr | None = None
    ai_debounce_seconds: float = 2.5  # xaridor ketma-ket yozsa — oxirgisiga javob (M06 §2.1)
    llm_retry_backoff_seconds: float = 0.5

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def effective_telegram_mode(self) -> str:
        if self.telegram_mode is not None:
            return self.telegram_mode
        return "polling" if self.app_env == "local" else "webhook"

    @model_validator(mode="after")
    def _no_local_defaults_outside_dev(self) -> Self:
        if self.app_env in ("staging", "production"):
            for name in ("database_url", "database_migrator_url"):
                reason = _unsafe_db_url_reason(getattr(self, name))
                if reason:
                    raise ValueError(f"{name} {self.app_env} muhitida ishlatib bo'lmaydi: {reason}")
            secret = self.jwt_secret.get_secret_value()
            if secret == _DEV_JWT_SECRET or len(secret) < MIN_JWT_SECRET_LENGTH:
                raise ValueError(
                    f"jwt_secret {self.app_env} muhitida kamida {MIN_JWT_SECRET_LENGTH} belgi bo'lsin"
                )
            if not self.cookie_secure:
                raise ValueError(f"cookie_secure {self.app_env} muhitida o'chirilmaydi")
            if self.rate_limit_scale != 1:
                raise ValueError(
                    f"rate_limit_scale {self.app_env} muhitida faqat 1 (limitlar kamaytirilmaydi)"
                )
            for name in (
                "app_public_url",
                "platform_app_public_url",
                "public_files_url",
                "messaging_webhook_base_url",
            ):
                if (make_url_host(getattr(self, name)) or "") in _LOCAL_HOSTS:
                    raise ValueError(
                        f"{name} {self.app_env} muhitida lokal manzil bo'lmasin (havolalar ishlamaydi)"
                    )
            if (
                self.pii_encryption_keys.get_secret_value() == _DEV_PII_KEYS
                or self.pii_hmac_key.get_secret_value() == _DEV_PII_HMAC_KEY
            ):
                raise ValueError(f"PII kalitlari {self.app_env} muhitida lokal standart bo'lmasin")
            hash_key = self.idempotency_hash_key.get_secret_value()
            if hash_key == _DEV_IDEMPOTENCY_HASH_KEY or len(hash_key) < MIN_HASH_KEY_LENGTH:
                raise ValueError(
                    f"idempotency_hash_key {self.app_env} muhitida kamida {MIN_HASH_KEY_LENGTH} belgi va "
                    "lokal standart emas"
                )
        if self.is_production:
            # A14: bepul Gemini kaliti bilan Google ma'lumotdan o'rganishi mumkin. `fake` production'da ishga
            # tushadi, lekin AI "sozlanmagan" — rejimni yoqib bo'lmaydi (M06 §10)
            if self.llm_provider == "gemini" and self.gemini_tier != "paid":
                raise ValueError("Gemini production'da faqat pullik tarif bilan (GEMINI_TIER=paid, A14)")
        self.pii_keyring()  # kalit formati noto'g'ri bo'lsa — ishga tushishda xato
        self.proxy_networks()  # noto'g'ri IP/CIDR — ishga tushishda xato
        if self.storage_backend == "s3":
            if not self.s3_private_bucket:
                raise ValueError("STORAGE_BACKEND=s3 uchun S3_PRIVATE_BUCKET kerak")
            if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
                raise ValueError("S3_ACCESS_KEY_ID va S3_SECRET_ACCESS_KEY birga beriladi")
        return self

    def proxy_networks(self) -> tuple[IPv4Network | IPv6Network, ...]:
        try:
            return tuple(
                ip_network(item.strip(), strict=False) for item in self.trusted_proxies if item.strip()
            )
        except ValueError as exc:
            raise ValueError(f"trusted_proxies noto'g'ri: {exc}") from exc

    def pii_keyring(self) -> PiiKeyring:
        return PiiKeyring(
            keys=parse_keys(self.pii_encryption_keys.get_secret_value()),
            active_key_id=self.pii_active_key_id,
            hmac_key=parse_keys(f"hmac:{self.pii_hmac_key.get_secret_value()}")["hmac"],
        )

    def storage_config(self) -> StorageConfig:
        s3 = None
        if self.storage_backend == "s3":
            assert self.s3_private_bucket  # validator tekshirgan
            s3 = S3Config(
                private_bucket=self.s3_private_bucket,
                public_bucket=self.s3_public_bucket or None,
                endpoint_url=self.s3_endpoint_url or None,
                region=self.s3_region,
                access_key_id=self.s3_access_key_id.get_secret_value() if self.s3_access_key_id else None,
                secret_access_key=(
                    self.s3_secret_access_key.get_secret_value() if self.s3_secret_access_key else None
                ),
                force_path_style=self.s3_force_path_style,
            )
        return StorageConfig(backend=self.storage_backend, local_dir=Path(self.storage_local_dir), s3=s3)

    def auth_config(self) -> AuthConfig:
        return AuthConfig(
            jwt_secret=self.jwt_secret.get_secret_value(),
            access_token_ttl=timedelta(minutes=self.access_token_ttl_minutes),
            refresh_token_ttl=timedelta(days=self.refresh_token_ttl_days),
            login_max_failures=self.login_max_failures,
            login_lockout=timedelta(minutes=self.login_lockout_minutes),
            invite_ttl=timedelta(hours=self.invite_ttl_hours),
            password_reset_ttl=timedelta(hours=self.password_reset_ttl_hours),
            app_public_url=self.app_public_url.rstrip("/"),
            platform_app_public_url=self.platform_app_public_url.rstrip("/"),
            cookie_secure=self.cookie_secure,
            argon2_time_cost=self.argon2_time_cost,
            argon2_memory_kib=self.argon2_memory_kib,
        )

    def database_config(self, *, worker: bool = False) -> DatabaseConfig:
        return DatabaseConfig(
            url=self.database_url,
            read_url=self.database_read_url,
            pool_size=self.worker_db_pool_size if worker else self.db_pool_size,
            max_overflow=self.worker_db_max_overflow if worker else self.db_max_overflow,
            statement_timeout_ms=self.db_statement_timeout_ms,
            application_name=f"commerce-os-{self.app_env}",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
