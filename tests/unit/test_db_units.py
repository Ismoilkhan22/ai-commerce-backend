"""DB qatlamining DB'siz qismlari: UUIDv7, schemalar ro'yxati, sozlamalar."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.db.schemas import SCHEMAS
from app.shared.db.ids import uuid7


def test_uuid7_version_variant_and_order() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
    assert ids == sorted(ids), "bir jarayonda UUIDv7 o'suvchi bo'lishi kerak"
    assert len(set(ids)) == len(ids)


def test_schemas_sql_matches_schema_list() -> None:
    sql = (Path(__file__).parents[2] / "app/db/schemas.sql").read_text(encoding="utf-8")
    declared = re.findall(r"CREATE SCHEMA IF NOT EXISTS (\w+)", sql)
    assert tuple(declared) == SCHEMAS


def test_migration_env_exists_for_every_schema() -> None:
    root = Path(__file__).parents[2]
    ini = (root / "alembic.ini").read_text(encoding="utf-8")
    for schema in SCHEMAS:
        assert f"[{schema}]" in ini
        assert (root / f"app/db/migrations/{schema}/env.py").exists()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://app_runtime:x@127.0.0.1:5432/cos",
        "postgresql+asyncpg://app_runtime:x@[::1]:5432/cos",
        "postgresql+asyncpg://app_runtime:app_runtime@db.internal:5432/cos",  # standart parol
        "postgresql+asyncpg://app_runtime:postgres@db.internal:5432/cos",
    ],
)
def test_unsafe_db_urls_rejected_in_production(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            database_url=url,
            database_migrator_url="postgresql+asyncpg://app_migrator:s3cret-long@db.internal:5432/cos",
            jwt_secret="x" * 40,
        )


def test_local_db_defaults_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(app_env="production")
    Settings(
        app_env="production",
        database_url="postgresql+asyncpg://app_runtime:r4nd0m-runtime-pw@db.internal:5432/cos",
        database_migrator_url="postgresql+asyncpg://app_migrator:r4nd0m-migrator-pw@db.internal:5432/cos",
        jwt_secret="x" * 40,
    )


def test_production_requires_strong_jwt_secret_and_secure_cookie() -> None:
    urls = {
        "database_url": "postgresql+asyncpg://app_runtime:r4nd0m-runtime-pw@db.internal:5432/cos",
        "database_migrator_url": "postgresql+asyncpg://app_migrator:r4nd0m-migrator-pw@db.internal:5432/cos",
    }
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(app_env="production", **urls)  # standart dev kaliti
    with pytest.raises(ValidationError, match="cookie_secure"):
        Settings(app_env="production", jwt_secret="x" * 40, cookie_secure=False, **urls)
