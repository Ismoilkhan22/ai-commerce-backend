"""VersionMixin: version avtomatik oshadi, parallel o'zgarish StaleDataError beradi (12 §4)."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import MetaData, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError

from app.shared.db.mixins import IdMixin, VersionMixin
from app.shared.db.session import Database, DatabaseConfig
from tests.integration.conftest import PgUrls

pytestmark = pytest.mark.integration

TABLE = f"zz_version_{uuid4().hex[:8]}"


class _TestBase(DeclarativeBase):  # ilova metadata'siga aralashmasligi uchun alohida base
    metadata = MetaData()


class Versioned(IdMixin, VersionMixin, _TestBase):
    __tablename__ = TABLE
    __table_args__ = ({"schema": "platform"},)
    note: Mapped[str] = mapped_column(Text)


@pytest.fixture
async def db(migrated: PgUrls) -> Database:
    conn = await asyncpg.connect(migrated.migrator.replace("postgresql+asyncpg://", "postgresql://"))
    await conn.execute(
        f"CREATE TABLE IF NOT EXISTS platform.{TABLE} "
        "(id uuid PRIMARY KEY, version bigint NOT NULL, note text NOT NULL)"
    )
    await conn.close()
    database = Database(DatabaseConfig(url=migrated.runtime))
    yield database  # type: ignore[misc]
    await database.dispose()


async def test_version_increments_automatically(db: Database) -> None:
    async with db.transaction() as session:
        row = Versioned(note="a")
        session.add(row)
    async with db.transaction() as session:
        loaded = await session.get(Versioned, row.id)
        assert loaded is not None and loaded.version == 1
        loaded.note = "b"
    async with db.transaction() as session:
        again = await session.get(Versioned, row.id)
        assert again is not None and again.version == 2


async def test_concurrent_update_raises_stale_data(db: Database) -> None:
    async with db.transaction() as session:
        row = Versioned(note="a")
        session.add(row)

    with pytest.raises(StaleDataError):
        async with db.transaction() as first:
            stale = await first.get(Versioned, row.id)  # version 1 o'qildi
            async with db.transaction() as second:
                fresh = await second.get(Versioned, row.id)
                assert fresh is not None
                fresh.note = "boshqa xodim"  # version 1 → 2, COMMIT
            assert stale is not None
            stale.note = "eski sahifadan"  # WHERE version = 1 → 0 qator
