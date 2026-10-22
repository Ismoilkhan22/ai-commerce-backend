"""Ulanishlar va tranzaksiyalar (07 §9).

- Har so'rov — bitta tranzaksiya; shop konteksti `set_config('app.shop_id', …, true)` bilan faqat
  shu tranzaksiya davomida o'rnatiladi (RLS, 10 §4). Session darajasidagi `SET` — TAQIQ:
  pool'dagi ulanish keyingi so'rovga boshqa shop konteksti bilan o'tib ketmasin.
- `get_read_db()` hozir yozish bilan bir xil DSN; read replica keyin faqat konfiguratsiya.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    read_url: str | None = None
    pool_size: int = 10
    max_overflow: int = 5
    pool_timeout_s: float = 10.0
    statement_timeout_ms: int = 5_000
    idle_in_transaction_timeout_ms: int = 10_000
    application_name: str = "commerce-os"


def _engine(url: str, config: DatabaseConfig) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout_s,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": config.application_name,
                "statement_timeout": str(config.statement_timeout_ms),
                "idle_in_transaction_session_timeout": str(config.idle_in_transaction_timeout_ms),
                "timezone": "UTC",
            }
        },
    )


class Database:
    def __init__(self, config: DatabaseConfig) -> None:
        self.write_engine = _engine(config.url, config)
        self.read_engine = _engine(config.read_url, config) if config.read_url else self.write_engine
        self._write = async_sessionmaker(self.write_engine, expire_on_commit=False)
        self._read = async_sessionmaker(self.read_engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(
        self, shop_id: UUID | None = None, *, read_only: bool = False
    ) -> AsyncIterator[AsyncSession]:
        """Bitta tranzaksiya: muvaffaqiyatda COMMIT, xatoda ROLLBACK."""
        factory = self._read if read_only else self._write
        async with factory() as session, session.begin():
            if read_only:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            if shop_id is not None:
                await set_shop_context(session, shop_id)
            yield session

    async def ping(self) -> None:
        async with self.write_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.write_engine.dispose()
        if self.read_engine is not self.write_engine:
            await self.read_engine.dispose()


async def set_shop_context(session: AsyncSession, shop_id: UUID) -> None:
    await session.execute(text("SELECT set_config('app.shop_id', :shop_id, true)"), {"shop_id": str(shop_id)})


def _request_shop_id(request: Request) -> UUID | None:
    # S0-04: ActorContext autentifikatsiya dependency'sida `request.state.shop_id` ga yoziladi.
    shop_id: UUID | None = getattr(request.state, "shop_id", None)
    return shop_id


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.db
    async with database.transaction(_request_shop_id(request)) as session:
        yield session


async def get_read_db(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.db
    async with database.transaction(_request_shop_id(request), read_only=True) as session:
        yield session
