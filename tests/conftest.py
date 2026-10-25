from __future__ import annotations

import tempfile

import pytest

from app.config.settings import Settings

# Testlar dasturchining lokal .env fayliga bog'liq bo'lmasin: faqat kodda berilgan qiymatlar
Settings.model_config["env_file"] = None

# Testlarda Argon2 tez ishlashi uchun past parametrlar; rate limit — xotirada
FAST_TEST_SETTINGS = {
    "app_env": "test",
    "log_level": "WARNING",
    "default_locale": "uz",
    "rate_limit_backend": "memory",
    "argon2_time_cost": 1,
    "argon2_memory_kib": 1024,
    "cookie_secure": False,
    # Yuklangan fayllar repo ichidagi var/storage'ga emas, vaqtinchalik papkaga tushadi
    "storage_local_dir": tempfile.mkdtemp(prefix="cos-test-storage-"),
}


@pytest.fixture
def settings() -> Settings:
    return Settings(**FAST_TEST_SETTINGS)  # type: ignore[arg-type]
