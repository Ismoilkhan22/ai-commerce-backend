"""S0-03 qabul mezonlari: rollback, pool, shop konteksti, rollar, migratsiyalar (07 §9–13)."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.checks import cross_schema_foreign_keys
from app.db.schemas import SCHEMAS
from app.shared.db.session import Database, DatabaseConfig
from tests.integration.conftest import PgUrls, alembic_config, migrate_all

pytestmark = pytest.mark.integration


def _db(urls: PgUrls, **overrides: object) -> Database:
    return Database(DatabaseConfig(url=urls.runtime, **overrides))  # type: ignore[arg-type]


def _plain(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def test_every_schema_upgrades_and_downgrades(migrated: PgUrls) -> None:
    migrate_all(migrated, "base", down=True)
    migrate_all(migrated)

    async def versions() -> dict[str, str]:
        conn = await asyncpg.connect(_plain(migrated.migrator))
        try:
            return {s: await conn.fetchval(f"SELECT version_num FROM {s}.alembic_version") for s in SCHEMAS}
        finally:
            await conn.close()

    heads = {s: ScriptDirectory.from_config(alembic_config(s)).get_current_head() for s in SCHEMAS}
    assert asyncio.run(versions()) == heads


@pytest.mark.parametrize("schema", SCHEMAS)
def test_models_match_migrations(migrated: PgUrls, schema: str) -> None:
    """ORM modellari va migratsiyalar bir xil: autogenerate hech narsa taklif qilmasligi kerak.
    Aks holda keyingi `--autogenerate` partition'lar yoki jadvallarni o'chiradigan migratsiya yasaydi."""
    os.environ["ALEMBIC_DATABASE_URL"] = migrated.migrator
    try:
        command.check(alembic_config(schema))
    finally:
        os.environ.pop("ALEMBIC_DATABASE_URL", None)


async def test_no_cross_schema_foreign_keys(migrated: PgUrls) -> None:  # TC-DB-05
    engine = create_async_engine(migrated.migrator, hide_parameters=True)
    async with engine.connect() as conn:
        assert await cross_schema_foreign_keys(conn) == []
    await engine.dispose()


async def test_runtime_role_cannot_bypass_rls_or_run_ddl(migrated: PgUrls) -> None:
    conn = await asyncpg.connect(_plain(migrated.runtime))
    try:
        flags = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        assert (flags["rolsuper"], flags["rolbypassrls"]) == (False, False)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("CREATE TABLE commerce.should_fail (id int)")
    finally:
        await conn.close()


async def test_runtime_role_cannot_touch_migration_state(migrated: PgUrls) -> None:
    conn = await asyncpg.connect(_plain(migrated.runtime))
    try:
        for schema in SCHEMAS:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(f"UPDATE {schema}.alembic_version SET version_num = version_num")
    finally:
        await conn.close()


@pytest.fixture
async def scratch_table(migrated: PgUrls) -> str:
    conn = await asyncpg.connect(_plain(migrated.migrator))
    table = f"platform.s003_{uuid4().hex[:8]}"
    await conn.execute(f"CREATE TABLE {table} (id uuid PRIMARY KEY, note text NOT NULL)")
    await conn.close()
    return table


async def test_transaction_rolls_back_on_error(migrated: PgUrls, scratch_table: str) -> None:
    db = _db(migrated)
    with pytest.raises(RuntimeError):
        async with db.transaction() as session:
            await session.execute(text(f"INSERT INTO {scratch_table} VALUES (:id, 'x')"), {"id": uuid4()})
            raise RuntimeError("domen xatosi")
    async with db.transaction() as session:
        count = (await session.execute(text(f"SELECT count(*) FROM {scratch_table}"))).scalar_one()
    assert count == 0
    await db.dispose()


async def test_shop_context_does_not_leak_between_transactions(migrated: PgUrls) -> None:
    db = _db(migrated, pool_size=1, max_overflow=0)  # bitta ulanish — qayta ishlatilishi kafolatlangan
    shop_id = uuid4()
    query = text("SELECT current_setting('app.shop_id', true)")
    async with db.transaction(shop_id) as session:
        assert (await session.execute(query)).scalar_one() == str(shop_id)
    async with db.transaction() as session:
        assert (await session.execute(query)).scalar_one() in (None, "")
    await db.dispose()


async def test_pool_serves_more_requests_than_connections(migrated: PgUrls) -> None:
    db = _db(migrated, pool_size=2, max_overflow=0, pool_timeout_s=10)

    async def work(i: int) -> int:
        async with db.transaction(uuid4()) as session:
            await session.execute(text("SELECT pg_sleep(0.05)"))
            return i

    assert sorted(await asyncio.gather(*(work(i) for i in range(20)))) == list(range(20))
    await db.dispose()


async def test_session_settings_applied(migrated: PgUrls) -> None:
    db = _db(migrated, statement_timeout_ms=5000)
    async with db.transaction() as session:
        assert (await session.execute(text("SHOW statement_timeout"))).scalar_one() == "5s"
        assert (await session.execute(text("SHOW TimeZone"))).scalar_one() == "UTC"
    await db.dispose()


async def test_read_only_transaction_rejects_writes(migrated: PgUrls, scratch_table: str) -> None:
    db = _db(migrated)
    with pytest.raises(Exception, match="read-only"):
        async with db.transaction(read_only=True) as session:
            await session.execute(text(f"INSERT INTO {scratch_table} VALUES (:id, 'x')"), {"id": uuid4()})
    await db.dispose()
