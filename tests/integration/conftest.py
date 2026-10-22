"""Haqiqiy PostgreSQL 16 (testcontainers). Docker bo'lmasa integratsiya testlari o'tkazib yuboriladi."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config

from app.db.bootstrap import bootstrap
from app.db.schemas import SCHEMAS

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
