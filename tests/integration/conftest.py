"""Haqiqiy PostgreSQL 16 (testcontainers). Docker bo'lmasa integratsiya testlari o'tkazib yuboriladi."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config

from app.db.bootstrap import bootstrap
from app.db.schemas import SCHEMAS

if TYPE_CHECKING:
    from tests.integration.helpers import World

# Ryuk (testcontainers tozalovchi konteyneri) ketma-ket yugurishlarda ba'zan port ololmaydi
# ("Port mapping ... 8080 is not available") va hamma integratsiya testi yiqiladi. Konteynerni
# `with PostgresContainer(...)` o'zi to'xtatadi, shuning uchun Ryuk kerak emas.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

RUNTIME_PASSWORD = "runtime-test"
MIGRATOR_PASSWORD = "migrator-test"


@dataclass(frozen=True)
class PgUrls:
    admin: str
    runtime: str
    migrator: str


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_urls() -> Iterator[PgUrls]:
    if not _docker_available():
        pytest.skip("Docker ishlamayapti — integratsiya testlari o'tkazib yuborildi")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "postgres:16-alpine", username="postgres", password="postgres", dbname="commerce_os"
    ) as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        base = f"{host}:{port}/commerce_os"
        urls = PgUrls(
            admin=f"postgresql://postgres:postgres@{base}",
            runtime=f"postgresql+asyncpg://app_runtime:{RUNTIME_PASSWORD}@{base}",
            migrator=f"postgresql+asyncpg://app_migrator:{MIGRATOR_PASSWORD}@{base}",
        )
        asyncio.run(bootstrap(urls.admin, urls.runtime, urls.migrator))
        yield urls


def alembic_config(schema: str) -> Config:
    return Config("alembic.ini", ini_section=schema)


def migrate_all(urls: PgUrls, revision: str = "head", *, down: bool = False) -> None:
    os.environ["ALEMBIC_DATABASE_URL"] = urls.migrator
    try:
        for schema in reversed(SCHEMAS) if down else SCHEMAS:
            (command.downgrade if down else command.upgrade)(alembic_config(schema), revision)
    finally:
        os.environ.pop("ALEMBIC_DATABASE_URL", None)


@pytest.fixture(scope="session")
def migrated(pg_urls: PgUrls) -> PgUrls:
    migrate_all(pg_urls)
    return pg_urls


@pytest.fixture
def world(migrated: PgUrls) -> Iterator[World]:
    """Yangi ilova + CLI orqali yaratilgan platforma admini (tokeni bilan). Shop va xodimlar — World'da."""
    # helpers.py shu fayldagi PgUrls'ni import qiladi — aylanma importni oldini olish uchun shu yerda
    from fastapi.testclient import TestClient

    from app.config.settings import Settings
    from app.main import create_app
    from app.platform.staff.cli import create_platform_admin
    from tests.conftest import FAST_TEST_SETTINGS
    from tests.integration.helpers import ADMIN_PASSWORD, World, _phone

    settings = Settings(**{**FAST_TEST_SETTINGS, "database_url": migrated.runtime})  # type: ignore[arg-type]
    admin_phone = _phone()
    asyncio.run(
        create_platform_admin(settings, admin_phone, "Platforma Admin", ADMIN_PASSWORD, "PLATFORM_ADMIN")
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"phone": admin_phone, "password": ADMIN_PASSWORD, "audience": "platform"},
        )
        assert response.status_code == 200, response.text
        yield World(client, migrated, settings, response.json()["access_token"], admin_phone)
