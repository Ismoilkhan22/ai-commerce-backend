"""Ilova sozlamalari (.env). Majburiy qiymat yo'q bo'lsa jarayon ishga tushmaydi (23 §3)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.db.session import DatabaseConfig
from app.shared.i18n.locale import Locale

# Faqat lokal muhit uchun standart qiymatlar (.env.example bilan bir xil).
_LOCAL_DB = "postgresql+asyncpg://{user}:{user}@localhost:5432/commerce_os"


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

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _no_local_defaults_outside_dev(self) -> Self:
        if self.app_env in ("staging", "production"):
            for name in ("database_url", "database_migrator_url"):
                if "@localhost:" in getattr(self, name):
                    raise ValueError(f"{name} {self.app_env} muhitida aniq berilishi kerak")
        return self

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
