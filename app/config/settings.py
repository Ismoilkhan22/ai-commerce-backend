"""Ilova sozlamalari (.env). Majburiy qiymat yo'q bo'lsa jarayon ishga tushmaydi (23 §3)."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.platform.auth.config import AuthConfig
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
    default_locale: Locale = "uz"

    # PostgreSQL (07 §9–10). app_runtime — NOBYPASSRLS, faqat DML; app_migrator — DDL.
    database_url: str = _LOCAL_DB.format(user="app_runtime")
    database_read_url: str | None = None
    database_migrator_url: str = _LOCAL_DB.format(user="app_migrator")
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_statement_timeout_ms: int = 5_000

    # Redis: db0 kesh va rate limit (08). Testlarda "memory".
    redis_url: str = "redis://localhost:6380/0"
    rate_limit_backend: Literal["redis", "memory"] = "redis"

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

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

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
            for name in ("app_public_url", "platform_app_public_url"):
                if (make_url_host(getattr(self, name)) or "") in _LOCAL_HOSTS:
                    raise ValueError(
                        f"{name} {self.app_env} muhitida lokal manzil bo'lmasin (havolalar ishlamaydi)"
                    )
        return self

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

    def database_config(self) -> DatabaseConfig:
        return DatabaseConfig(
            url=self.database_url,
            read_url=self.database_read_url,
            pool_size=self.db_pool_size,
            max_overflow=self.db_max_overflow,
            statement_timeout_ms=self.db_statement_timeout_ms,
            application_name=f"commerce-os-{self.app_env}",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
