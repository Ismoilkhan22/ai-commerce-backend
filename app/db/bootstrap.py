"""DB'ni birinchi marta tayyorlash: rollar + schemalar + huquqlar (07 §10–11, 23 §3).

    uv run python -m app.db.bootstrap

Admin ulanishi (`DATABASE_ADMIN_URL`) faqat shu skript uchun. Rol parollari `DATABASE_URL` va
`DATABASE_MIGRATOR_URL` dan olinadi. Production'da rollarni ops yaratadi; skript idempotent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.db.schemas import MIGRATOR_ROLE, RUNTIME_ROLE

SCHEMAS_SQL = Path(__file__).with_name("schemas.sql")

# Ikkala rol ham superuser emas va RLS'ni chetlab o'ta olmaydi (10 §4).
_ROLE_FLAGS = "LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def ensure_role(conn: asyncpg.Connection, role: str, password: str) -> None:
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    verb = "ALTER" if exists else "CREATE"
    await conn.execute(f'{verb} ROLE "{role}" {_ROLE_FLAGS} PASSWORD {_literal(password)}')


async def bootstrap(admin_url: str, runtime_url: str, migrator_url: str) -> None:
    runtime, migrator = make_url(runtime_url), make_url(migrator_url)
    if runtime.username != RUNTIME_ROLE or migrator.username != MIGRATOR_ROLE:
        raise ValueError(
            f"DATABASE_URL foydalanuvchisi {RUNTIME_ROLE}, migrator — {MIGRATOR_ROLE} bo'lishi kerak"
        )
    conn = await asyncpg.connect(make_url(admin_url).set(drivername="postgresql").render_as_string(False))
    try:
        await ensure_role(conn, RUNTIME_ROLE, runtime.password or "")
        await ensure_role(conn, MIGRATOR_ROLE, migrator.password or "")
        database = await conn.fetchval("SELECT current_database()")
        await conn.execute(f'GRANT CONNECT ON DATABASE "{database}" TO "{RUNTIME_ROLE}", "{MIGRATOR_ROLE}"')
        await conn.execute(SCHEMAS_SQL.read_text(encoding="utf-8"))
    finally:
        await conn.close()


class _AdminSettings(BaseSettings):
    """Admin URL ilova sozlamalarida yo'q (runtime unga muhtoj emas), lekin xuddi shu .env'dan o'qiladi."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    database_admin_url: str = "postgresql://postgres:postgres@localhost:5433/commerce_os"


def main() -> None:
    from app.config.settings import Settings

    settings = Settings()
    admin_url = _AdminSettings().database_admin_url
    asyncio.run(bootstrap(admin_url, settings.database_url, settings.database_migrator_url))


if __name__ == "__main__":
    main()
