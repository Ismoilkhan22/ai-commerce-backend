"""S0-07 qabul mezonlari haqiqiy PostgreSQL'da: transition_log, idempotency, audit (append-only)."""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.platform.audit.services.audit_service import AuditService
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.db.partitions import month_starts
from app.shared.db.session import Database, DatabaseConfig
from app.shared.errors.base import IdempotencyKeyReusedError, RequestInProgressError
from app.shared.idempotency.store import (
    HASH_PREFIX,
    IdempotencyStore,
    request_hash,
)
from app.shared.types.actor import ActorContext
from app.shared.types.state import StateMachineRule
from tests.integration.conftest import PgUrls

TEST_HASH_KEY = b"test-idempotency-hash-key"

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
    use = UseService(RulesRegistry([CONFIRM]), AuditService())
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


PARTITIONED_TABLES = ("platform.transition_log", "audit.audit_entries")
MONTHS_AHEAD = 12


@pytest.mark.parametrize("table", PARTITIONED_TABLES)
async def test_partitions_cover_next_months_and_default_is_empty(migrated: PgUrls, table: str) -> None:
    """Joriy oy + keyingi 12 oy uchun partition bo'lishi shart, DEFAULT esa bo'sh.
    Bu test yiqilsa — partition yaratish ishi (TD-01) kechikkan: yozuvlar DEFAULT'ga tushadi va
    keyin o'sha oy uchun partition yaratib bo'lmaydi."""
    schema, name = table.split(".")
    today = date.today()
    needed = {
        f"{name}_y{m.year}m{m.month:02d}"
        for m in month_starts(date(today.year, today.month, 1), MONTHS_AHEAD + 1)
    }
    conn = await asyncpg.connect(migrated.migrator.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        rows = await conn.fetch(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent JOIN pg_namespace n ON n.oid = p.relnamespace "
            "WHERE n.nspname = $1 AND p.relname = $2",
            schema,
            name,
        )
        existing = {r["relname"] for r in rows}
        assert needed <= existing, f"yetishmayotgan partition'lar: {sorted(needed - existing)}"
        assert await conn.fetchval(f"SELECT count(*) FROM {schema}.{name}_default") == 0
    finally:
        await conn.close()


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
    body_hash = request_hash("POST", "/api/v1/shop/orders/1/confirm", {"x": 1}, TEST_HASH_KEY)
    async with db.transaction(shop_id) as session:
        assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None
        await store.complete(session, shop_id, "order.confirm", key, 200, {"status": "CONFIRMED"})

    async with db.transaction(shop_id) as session:
        stored = await store.begin(session, shop_id, "order.confirm", key, body_hash)
    assert stored is not None and (stored.status, stored.body) == (200, {"status": "CONFIRMED"})

    with pytest.raises(IdempotencyKeyReusedError):
        async with db.transaction(shop_id) as session:
            await store.begin(
                session, shop_id, "order.confirm", key, request_hash("POST", "/x", {"x": 2}, TEST_HASH_KEY)
            )


async def test_only_keyed_request_hash_can_be_stored(db: Database) -> None:  # QA M04 F2, 2-tur
    """Kalitsiz (oddiy SHA-256) barmoq izini baza qabul qilmaydi — eski qatorlarni platform_0008 o'chirgan."""
    store, shop_id = IdempotencyStore(), uuid4()
    with pytest.raises(DBAPIError, match="ck_idempotency_keys_request_hash_keyed"):
        async with db.transaction(shop_id) as session:
            await store.begin(session, shop_id, "op", f"key-{uuid4()}", "0" * 64)
    fresh = f"key-{uuid4()}"
    async with db.transaction(shop_id) as session:
        await store.begin(session, shop_id, "op", fresh, request_hash("POST", "op", {}, TEST_HASH_KEY))
        stored_hash = (
            await session.execute(
                text("SELECT request_hash FROM platform.idempotency_keys WHERE key = :k"), {"k": fresh}
            )
        ).scalar_one()
    assert stored_hash.startswith(HASH_PREFIX)


async def test_idempotency_key_is_scoped_by_shop(db: Database) -> None:  # bir xil kalit — boshqa shop
    store, key, body_hash = (
        IdempotencyStore(),
        f"key-{uuid4()}",
        request_hash("POST", "/p", {}, TEST_HASH_KEY),
    )
    for shop_id in (uuid4(), uuid4()):
        async with db.transaction(shop_id) as session:
            assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None
            await store.complete(session, shop_id, "order.confirm", key, 200, {})


async def test_rolled_back_request_leaves_no_key(db: Database) -> None:
    store, shop_id, key, body_hash = (
        IdempotencyStore(),
        uuid4(),
        f"key-{uuid4()}",
        request_hash("POST", "/p", {}, TEST_HASH_KEY),
    )
    with pytest.raises(RuntimeError):
        async with db.transaction(shop_id) as session:
            await store.begin(session, shop_id, "order.confirm", key, body_hash)
            raise RuntimeError("biznes xatosi — COMMIT yo'q")
    async with db.transaction(shop_id) as session:
        assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None


async def test_concurrent_duplicate_gets_request_in_progress(db: Database) -> None:
    """Birinchi so'rov bajarilayotganda dublikat KUTMAYDI — darhol 409 REQUEST_IN_PROGRESS (founder).
    Birinchisi tugagach, qayta so'rov saqlangan javobni oladi. Vaqtga (sleep) emas, event'larga tayanadi."""
    store, shop_id, key = IdempotencyStore(), uuid4(), f"key-{uuid4()}"
    body_hash = request_hash("POST", "/p", {}, TEST_HASH_KEY)
    first_started, release_first = asyncio.Event(), asyncio.Event()

    async def first_request() -> None:
        async with db.transaction(shop_id) as session:
            assert await store.begin(session, shop_id, "order.confirm", key, body_hash) is None
            first_started.set()
            await release_first.wait()  # birinchi so'rov "ishlayapti"
            await store.complete(session, shop_id, "order.confirm", key, 200, {"n": 1})

    first = asyncio.create_task(first_request())
    await first_started.wait()
    for _ in range(3):
        with pytest.raises(RequestInProgressError):
            async with asyncio.timeout(2):  # kutib qolsa — test yiqiladi
                async with db.transaction(shop_id) as session:
                    await store.begin(session, shop_id, "order.confirm", key, body_hash)
    release_first.set()
    await first

    async with db.transaction(shop_id) as session:
        stored = await store.begin(session, shop_id, "order.confirm", key, body_hash)
    assert stored is not None and stored.body == {"n": 1}


async def test_audit_diff_with_decimal_uuid_and_datetime(db: Database) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    shop_id, entity_id = uuid4(), uuid4()
    async with db.transaction(shop_id) as session:
        await AuditService().record(
            session,
            action="shops.policy.updated",
            entity_type="platform.shop_policy",
            entity_id=entity_id,
            actor=_actor(shop_id),
            diff={
                "limit": {"new": Decimal("7.50")},
                "ref": uuid4(),
                "at": datetime(2026, 10, 23, tzinfo=UTC),
            },
        )
    async with db.transaction(shop_id) as session:
        diff = (
            await session.execute(
                text("SELECT diff FROM audit.audit_entries WHERE entity_id = :e"), {"e": entity_id}
            )
        ).scalar_one()
    assert diff["limit"] == {"new": "7.50"} and diff["at"] == "2026-10-23T00:00:00Z"
