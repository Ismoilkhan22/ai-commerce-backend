from __future__ import annotations

import pytest

from app.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", log_level="WARNING", default_locale="uz")
