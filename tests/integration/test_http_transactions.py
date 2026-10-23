"""HTTP darajasida tranzaksiya va idempotency (kod tekshiruvi, 2026-10-23).

- COMMIT javob yuborilishidan OLDIN bo'lishi kerak: COMMIT paytidagi xato klientga yetib borsin.
- TC-CONV-07: bir xil Idempotency-Key — saqlangan javob; boshqa tana — 409.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config.settings import Settings
from app.main import create_app
from app.shared.db.mixins import IdMixin, VersionMixin
from app.shared.db.session import Database, DbSession
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.store import IdempotencyStore, request_hash
from app.shared.types.manifest import DomainManifest
from tests.integration.conftest import PgUrls

pytestmark = pytest.mark.integration

TABLE = f"zz_http_{uuid4().hex[:8]}"


class _Base(DeclarativeBase):
    metadata = MetaData()


class Note(IdMixin, VersionMixin, _Base):
    __tablename__ = TABLE
    __table_args__ = ({"schema": "platform"},)
    body: Mapped[str] = mapped_column(Text)


router = APIRouter()


@router.patch("/notes/{note_id}")
async def update_note(note_id: UUID, request: Request, db: DbSession) -> dict[str, str]:
    note = await db.get(Note, note_id)
    assert note is not None
    # Shu orada boshqa xodim xuddi shu yozuvni saqlab qo'ydi (alohida tranzaksiya, COMMIT)
    database: Database = request.app.state.db
    async with database.transaction() as other:
        fresh = await other.get(Note, note_id)
        assert fresh is not None
        fresh.body = "boshqa xodim"
    note.body = "eski sahifadan"  # flush yo'q — UPDATE COMMIT paytida ketadi
    return {"status": "saved"}


store = IdempotencyStore()


@router.post("/payments-like")
async def idempotent_action(
    body: dict[str, Any], key: Annotated[str, Depends(get_idempotency_key)], db: DbSession
) -> Any:
    req_hash = request_hash("POST", "/payments-like", body)
    stored = await store.begin(db, None, "test.action", key, req_hash)
    if stored is not None:
        return stored.body
    result = {"id": uuid4(), "amount": Decimal("12.50"), "echo": body}  # odatiy javob: UUID, Decimal
    await store.complete(db, None, "test.action", key, 200, result)
    return result


@pytest.fixture
def app(migrated: PgUrls) -> Iterator[FastAPI]:
    async def create_table() -> None:
        conn = await asyncpg.connect(migrated.migrator.replace("postgresql+asyncpg://", "postgresql://"))
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS platform.{TABLE} "
            "(id uuid PRIMARY KEY, version bigint NOT NULL, body text NOT NULL)"
        )
        await conn.close()

    import asyncio

    asyncio.run(create_table())
    settings = Settings(app_env="test", log_level="WARNING", database_url=migrated.runtime)
    yield create_app(settings, manifests=[DomainManifest(name="t", routers={"shop": router})])


def _insert_note(client: TestClient) -> UUID:
    database: Database = client.app.state.db  # type: ignore[attr-defined]
    note_id = uuid4()

    async def insert() -> None:
        async with database.transaction() as session:
            session.add(Note(id=note_id, body="asl"))

    client.portal.call(insert)  # type: ignore[union-attr]
    return note_id


def _read_body(client: TestClient, note_id: UUID) -> str:
    database: Database = client.app.state.db  # type: ignore[attr-defined]

    async def read() -> str:
        async with database.transaction() as session:
            return str(
                (
                    await session.execute(
                        text(f"SELECT body FROM platform.{TABLE} WHERE id = :i"), {"i": note_id}
                    )
                ).scalar_one()
            )

    return client.portal.call(read)  # type: ignore[union-attr,no-any-return]


def test_commit_conflict_reaches_client_as_409(app: FastAPI) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        note_id = _insert_note(client)
        response = client.patch(f"/api/v1/shop/notes/{note_id}")
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "VERSION_CONFLICT"
        assert _read_body(client, note_id) == "boshqa xodim"


def test_idempotent_endpoint_over_http(app: FastAPI) -> None:  # TC-CONV-07
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = {"Idempotency-Key": f"key-{uuid4()}"}
        first = client.post("/api/v1/shop/payments-like", json={"x": 1}, headers=headers)
        assert first.status_code == 200, first.text
        second = client.post("/api/v1/shop/payments-like", json={"x": 1}, headers=headers)
        assert second.json() == first.json()  # bajarilmadi, saqlangan javob qaytdi
        reused = client.post("/api/v1/shop/payments-like", json={"x": 2}, headers=headers)
        assert reused.status_code == 409
        assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
