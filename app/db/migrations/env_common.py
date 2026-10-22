"""Barcha schema env'lari uchun umumiy Alembic logikasi (ADR-035, 07 §11).

Har schema o'z `alembic_version` jadvalini o'z schemasida saqlaydi va autogenerate faqat
o'z schemasidagi jadvallarni ko'radi — migratsiya boshqa schemaga tegmaydi.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import load_metadata


def _url() -> str:
    # Testlar va CI uchun aniq URL; aks holda Settings (.env)
    override = os.environ.get("ALEMBIC_DATABASE_URL")
    if override:
        return override
    from app.config.settings import Settings

    return Settings().database_migrator_url


def _include_object(schema: str) -> Any:
    def include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        if type_ == "table":
            return bool(obj.schema == schema)
        return True

    return include


def _configure(schema: str, **kwargs: Any) -> None:
    context.configure(
        target_metadata=load_metadata(schema),
        version_table_schema=schema,
        include_schemas=True,
        include_object=_include_object(schema),
        compare_type=True,
        **kwargs,
    )


def _run_sync(connection: Connection, schema: str) -> None:
    _configure(schema, connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online(schema: str) -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync, schema)
    await engine.dispose()


def run(schema: str) -> None:
    if context.is_offline_mode():
        _configure(schema, url=_url(), literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        asyncio.run(_run_online(schema))
