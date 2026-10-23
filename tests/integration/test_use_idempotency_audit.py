"""S0-07 qabul mezonlari haqiqiy PostgreSQL'da: transition_log, idempotency, audit (append-only)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.platform.audit.services.audit_service import AuditService
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.db.session import Database, DatabaseConfig
from app.shared.errors.base import IdempotencyKeyReusedError
from app.shared.idempotency.store import IdempotencyStore, request_hash
from app.shared.types.actor import ActorContext
from app.shared.types.state import StateMachineRule
from tests.integration.conftest import PgUrls

pytestmark = pytest.mark.integration

CONFIRM = StateMachineRule(
    entity_type="commerce.order",
    command="CONFIRM",
    from_status="PENDING_CONFIRMATION",
    to_status="CONFIRMED",
    actors=frozenset({"STAFF"}),
    business_ref="FSM-08",
)


def _actor(shop_id: object) -> ActorContext:
    return ActorContext(actor_type="STAFF", actor_id=uuid4(), shop_id=shop_id, surface="shop")  # type: ignore[arg-type]


@pytest.fixture
async def db(migrated: PgUrls) -> Database:
    database = Database(DatabaseConfig(url=migrated.runtime, pool_size=5))
    yield database  # type: ignore[misc]
    await database.dispose()


async def test_transition_is_logged_in_monthly_partition(db: Database) -> None:
    use = UseService(RulesRegistry([CONFIRM]))
    shop_id, entity_id = uuid4(), uuid4()
    async with db.transaction(shop_id) as session:
        rule = use.validate_transition(
            "commerce.order", "PENDING_CONFIRMATION", "CONFIRMED", "CONFIRM", _actor(shop_id)
        )
        await use.log_transition(session, entity_id=entity_id, rule=rule, actor=_actor(shop_id))
    async with db.transaction(shop_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT tableoid::regclass::text AS part, command "
                    "FROM platform.transition_log WHERE entity_id = :e"
                ),
                {"e": entity_id},
            )
        ).one()
    assert row.command == "CONFIRM"
    assert row.part.startswith("platform.transition_log_y20"), (
        "yozuv DEFAULT emas, oy partition'iga tushishi kerak"
    )


async def test_transition_log_and_audit_are_append_only(db: Database) -> None:
    for table in ("platform.transition_log", "audit.audit_entries"):
        for statement in (f"UPDATE {table} SET reason = 'x'", f"DELETE FROM {table}"):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with db.transaction() as session:
                    await session.execute(text(statement))


async def test_audit_entry_written_with_trace_and_actor(db: Database) -> None:
    shop_id, order_id = uuid4(), uuid4()
    async with db.transaction(shop_id) as session:
        await AuditService().record(
            session,
            action="commerce.order.confirmed",
            entity_type="commerce.order",
            entity_id=order_id,
            actor=_actor(shop_id),
            entity_version=3,
            diff={"status": {"old": "PENDING_CONFIRMATION", "new": "CONFIRMED"}},
        )
    async with db.transaction(shop_id) as session:
        row = (
            await session.execute(
                text("SELECT shop_id, actor_type, diff FROM audit.audit_entries WHERE entity_id = :e"),
                {"e": order_id},
            )
        ).one()
    assert (row.shop_id, row.actor_type, row.diff["status"]["new"]) == (shop_id, "STAFF", "CONFIRMED")


async def test_idempotency_replays_response_and_rejects_reuse(db: Database) -> None:  # TC-CONV-07
    store, shop_id, key = IdempotencyStore(), uuid4(), f"key-{uuid4()}"
    body_hash = request_hash("POST", "/api/v1/shop/orders/1/confirm", {"x": 1})
    async with db.transaction(shop_id) as session:
        assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None
        await store.complete(session, shop_id, "order.confirm", key, 200, {"status": "CONFIRMED"})

    async with db.transaction(shop_id) as session:
        stored = await store.begin(session, shop_id, "order.confirm", key, body_hash)
    assert stored is not None and (stored.status, stored.body) == (200, {"status": "CONFIRMED"})

    with pytest.raises(IdempotencyKeyReusedError):
        async with db.transaction(shop_id) as session:
            await store.begin(session, shop_id, "order.confirm", key, request_hash("POST", "/x", {"x": 2}))


async def test_idempotency_key_is_scoped_by_shop(db: Database) -> None:  # bir xil kalit — boshqa shop
    store, key, body_hash = IdempotencyStore(), f"key-{uuid4()}", request_hash("POST", "/p", {})
    for shop_id in (uuid4(), uuid4()):
        async with db.transaction(shop_id) as session:
            assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None
            await store.complete(session, shop_id, "order.confirm", key, 200, {})


async def test_rolled_back_request_leaves_no_key(db: Database) -> None:
    store, shop_id, key, body_hash = (
        IdempotencyStore(),
        uuid4(),
        f"key-{uuid4()}",
        request_hash("POST", "/p", {}),
    )
    with pytest.raises(RuntimeError):
        async with db.transaction(shop_id) as session:
            await store.begin(session, shop_id, "order.confirm", key, body_hash)
            raise RuntimeError("biznes xatosi — COMMIT yo'q")
    async with db.transaction(shop_id) as session:
        assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None


async def test_concurrent_same_key_executes_once(db: Database) -> None:
    store, shop_id, key, body_hash = (
        IdempotencyStore(),
        uuid4(),
        f"key-{uuid4()}",
        request_hash("POST", "/p", {}),
    )
    executed = 0

    async def request() -> object:
        nonlocal executed
        async with db.transaction(shop_id) as session:
            stored = await store.begin(session, shop_id, "order.confirm", key, body_hash)
            if stored is not None:
                return stored.body
            executed += 1
            await asyncio.sleep(0.2)  # ikkinchi so'rov unikal indeksda kutadi
            await store.complete(session, shop_id, "order.confirm", key, 200, {"n": 1})
            return {"n": 1}

    results = await asyncio.gather(*(request() for _ in range(5)))
    assert executed == 1
    assert results == [{"n": 1}] * 5
