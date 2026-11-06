"""5a: outbox, worker, rejali ishlar, xodim vazifalari va xabarnomalari — haqiqiy PostgreSQL'da.

Redis o'rniga `RecordingQueue` (arq vazifalari ro'yxatga yoziladi, test o'zi bajaradi) va API ilovasining
xotiradagi keshi va realtime broker'i — worker va API bir xil servislarni ko'radi.

Qabul mezonlari (5a vazifasi): outbox atomarligi, retry va dead-letter, idempotent tinglovchi (TC-022), narx
o'zgarsa sayt keshi eskiradi, kutubxona modeli tasdiqlansa SKU bog'lanadi, 24/72 soat vazifalari va ularning
o'zi yopilishi, kechki solishtiruv (avtomatik tuzatmaydi), TD-01, TD-02, payload'da PII yo'q.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.platform.notifications.models.orm import Notification
from app.shared.db.session import Database
from app.shared.events.models import OUTBOX_SCHEMAS, outbox_table
from app.shared.events.outbox import write_outbox
from app.shared.events.pii import forbidden_keys
from app.shared.events.registry import EventContext, Subscriber, SubscriberRegistry
from app.shared.types.actor import ActorContext
from app.workers.dispatch import MAX_ATTEMPTS, deliver
from app.workers.outbox_worker import dispatch_pending
from app.workers.queue import RecordingQueue
from app.workers.runtime import WorkerRuntime, build_runtime
from app.workers.scheduler import run_job
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_catalog import _approve, _create, _platform_member, _sku, _spec
from tests.integration.test_commerce import PHONE, Shop, _admin_sql, _ok, _post

pytestmark = pytest.mark.integration


# ------------------------------------------------------------------ yordamchilar
@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> Iterator[None]:
    """Oldingi test fayllari qoldirgan PENDING event'lar shu testning navbatiga aralashmasin."""
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )
    yield


def _run[T](world: World, queue: RecordingQueue, fn: Callable[[WorkerRuntime], Awaitable[T]]) -> T:
    """Worker holati API ilovasining servislari bilan; baza ulanishi shu `asyncio.run` ichida ochiladi."""

    async def go() -> T:
        rt = build_runtime(world.settings, queue, services=world.client.app.state)
        try:
            return await fn(rt)
        finally:
            await rt.database.dispose()

    return asyncio.run(go())


async def _drain(rt: WorkerRuntime, queue: RecordingQueue, rounds: int = 10) -> None:
    """outbox → vazifalar → bajarish, yangi event qolmaguncha."""
    for _ in range(rounds):
        seen = await dispatch_pending(rt)
        jobs = queue.take()
        for function, job_id, kwargs in jobs:
            if function == "dispatch_event":
                await deliver(rt, kwargs["schema"], UUID(kwargs["event_id"]), kwargs["consumer"], 1)
            queue.forget(job_id)
        if not seen and not jobs:
            return


def _drain_now(world: World, queue: RecordingQueue | None = None) -> RecordingQueue:
    queue = queue or RecordingQueue()
    _run(world, queue, lambda rt: _drain(rt, queue))
    return queue


def _job(world: World, name: str) -> Any:
    def find(rt: WorkerRuntime) -> Any:
        return next(j for j in rt.jobs if j.name == name)

    async def go(rt: WorkerRuntime) -> Any:
        return await run_job(rt, find(rt))

    return _run(world, RecordingQueue(), go)


def _events(world: World, schema: str, shop_id: UUID) -> list[dict[str, Any]]:
    rows = _admin_sql(
        world,
        f"SELECT event_type, status, envelope FROM {schema}.outbox_events "
        "WHERE shop_id = $1 ORDER BY created_at",
        shop_id,
    )
    return [
        {"type": r["event_type"], "status": r["status"], "envelope": json.loads(r["envelope"])} for r in rows
    ]


def _tasks(world: World, token: str, status: str = "OPEN") -> list[dict[str, Any]]:
    return list(_ok(world.client.get(f"/api/v1/shop/tasks?status={status}", headers=_bearer(token)))["items"])


def _notifications(world: World, token: str) -> dict[str, Any]:
    return _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(token)))


# ------------------------------------------------------------------ outbox va worker
def test_outbox_row_exists_only_if_business_transaction_commits(world: World) -> None:
    shop = Shop(world)
    actor = ActorContext.system(shop.id)

    async def go() -> None:
        db = Database(world.settings.database_config())
        try:
            with pytest.raises(RuntimeError):
                async with db.transaction(shop.id) as session:
                    await write_outbox(
                        session,
                        schema="platform",
                        event_type="test.rolled_back",
                        actor=actor,
                        shop_id=shop.id,
                        aggregate_type="test",
                        aggregate_id=shop.id,
                        aggregate_version=1,
                        payload={"x": 1},
                    )
                    raise RuntimeError("biznes xatosi")
            async with db.transaction(shop.id) as session:
                await write_outbox(
                    session,
                    schema="platform",
                    event_type="test.committed",
                    actor=actor,
                    shop_id=shop.id,
                    aggregate_type="test",
                    aggregate_id=shop.id,
                    aggregate_version=1,
                    payload={"x": 1},
                )
        finally:
            await db.dispose()

    asyncio.run(go())
    types = [e["type"] for e in _events(world, "platform", shop.id)]
    assert "test.committed" in types and "test.rolled_back" not in types


def test_price_change_invalidates_site_cache_once_per_event(world: World) -> None:  # 08 §4.3
    shop = Shop(world)
    sku = shop.sku()
    events = _events(world, "catalog", shop.id)
    assert [e["type"] for e in events] == [
        "catalog.sku.changed",  # variant yaratildi (QA 5a F3)
        "catalog.price.changed",
        "catalog.product.published",
    ]
    assert all(e["status"] == "PENDING" for e in events)
    cache = world.client.app.state.cache
    key = f"cos:v1:shop:{shop.id}:storefront:index_version"
    before = int(asyncio.run(cache.get(key)) or 0)
    _drain_now(world)
    assert int(asyncio.run(cache.get(key)) or 0) == before + 3  # uchala event — inline tinglovchi
    assert {e["status"] for e in _events(world, "catalog", shop.id)} == {"PUBLISHED"}
    receipts = _admin_sql(
        world,
        "SELECT count(*) AS n FROM storefront.consumer_receipts "
        "WHERE consumer = 'storefront.cache_invalidate'",
    )
    assert receipts[0]["n"] >= 3

    # Narx o'zgarishi → yangi event → yana bir marta
    changed = world.client.put(
        f"/api/v1/shop/skus/{sku}/price",
        json={"amount_minor": 470_000_000, "currency": "UZS"},
        headers=_bearer(shop.owner, **_idem(), **{"If-Match": '"v1"'}),
    )
    assert changed.status_code == 200, changed.text
    _drain_now(world)
    assert int(asyncio.run(cache.get(key)) or 0) == before + 4


def test_redelivered_event_is_applied_once(world: World) -> None:  # TC-022
    shop = Shop(world)
    shop.sku()
    calls: list[UUID] = []

    async def handler(ctx: EventContext) -> None:
        calls.append(ctx.envelope.event_id)

    counting = Subscriber(
        consumer="test.counting",
        event_types=frozenset({"catalog.price.changed"}),
        schema="catalog",
        handler=handler,
    )
    queue = RecordingQueue()

    async def go(rt: WorkerRuntime) -> None:
        rt.registry = SubscriberRegistry([counting])
        await dispatch_pending(rt)
        [(function, _, kwargs)] = [j for j in queue.take() if j[2]["consumer"] == "test.counting"]
        assert function == "dispatch_event"
        for _ in range(3):  # arq bir xil vazifani qayta bersa (worker o'ldi, Redis tiklandi)
            await deliver(rt, kwargs["schema"], UUID(kwargs["event_id"]), kwargs["consumer"], 1)

    _run(world, queue, go)
    assert len(calls) == 1


def test_failing_subscriber_retries_then_dead_letters_and_replays(world: World) -> None:  # 05 §7
    shop = Shop(world)

    async def broken(ctx: EventContext) -> None:
        raise ValueError(f"tinglovchi xatosi {PHONE}")  # matn dead-letter'ga tushmasligi kerak

    failing = Subscriber(
        consumer="test.failing", event_types=frozenset({"test.boom"}), schema="platform", handler=broken
    )
    queue = RecordingQueue()

    async def go(rt: WorkerRuntime) -> str:
        rt.registry = SubscriberRegistry([failing])
        async with rt.database.transaction(shop.id) as db:
            envelope = await write_outbox(
                db,
                schema="platform",
                event_type="test.boom",
                actor=ActorContext.system(shop.id),
                shop_id=shop.id,
                aggregate_type="test",
                aggregate_id=shop.id,
                aggregate_version=1,
                payload={"n": 1},
            )
        await dispatch_pending(rt)
        [(_, _, kwargs)] = queue.take()
        for attempt in range(1, MAX_ATTEMPTS):
            with pytest.raises(ValueError):
                await deliver(rt, "platform", envelope.event_id, kwargs["consumer"], attempt)
        assert await deliver(rt, "platform", envelope.event_id, kwargs["consumer"], MAX_ATTEMPTS) == "dead"
        return str(envelope.event_id)

    event_id = _run(world, queue, go)
    [row] = _admin_sql(world, "SELECT * FROM platform.dead_letters WHERE event_id = $1", UUID(event_id))
    assert (row["status"], row["attempts"], row["last_error"]) == ("OPEN", MAX_ATTEMPTS, "ValueError")
    assert PHONE not in row["last_error"]

    admin = _bearer(world.admin_token)
    listed = _ok(world.client.get("/api/v1/platform/dead-letters", headers=admin))
    letter = next(d for d in listed["items"] if d["event_id"] == event_id)
    assert listed["open_count"] >= 1
    replayed = _ok(
        world.client.post(
            f"/api/v1/platform/dead-letters/{letter['id']}/replay",
            json={"note": "xato tuzatildi"},
            headers=admin,
        )
    )
    assert replayed["status"] == "REPLAYED"
    again = world.client.post(
        f"/api/v1/platform/dead-letters/{letter['id']}/ignore", json={"note": "kech"}, headers=admin
    )
    assert again.status_code == 409

    # Rekonsilyatsiya: 10 daqiqadan eski, belgisi yo'q → qayta navbatga (replay belgisi bilan yangi job_id)
    _admin_sql(
        world,
        "UPDATE platform.outbox_events SET published_at = now() - interval '20 minutes' WHERE event_id = $1",
        UUID(event_id),
    )
    queue2 = RecordingQueue()

    async def reconcile(rt: WorkerRuntime) -> None:
        rt.registry = SubscriberRegistry([failing])
        job = next(j for j in rt.jobs if j.name == "outbox_reconcile")
        await run_job(rt, job)

    _run(world, queue2, reconcile)
    requeued = [j for j in queue2.jobs if j[0] == "dispatch_event" and j[2]["event_id"] == event_id]
    assert len(requeued) == 1 and ":replay:" in requeued[0][1]


def test_queue_outage_keeps_event_pending_with_backoff(world: World) -> None:  # 05 §5
    shop = Shop(world)
    shop.sku()
    queue = RecordingQueue(fail=ConnectionError("redis down"))

    async def handler(ctx: EventContext) -> None:  # arq orqali bajariladigan (inline emas) tinglovchi
        return None

    queued = Subscriber(
        consumer="test.queued",
        event_types=frozenset({"catalog.price.changed"}),
        schema="catalog",
        handler=handler,
    )

    async def go(rt: WorkerRuntime) -> int:
        rt.registry = SubscriberRegistry([queued])
        return await dispatch_pending(rt)

    _run(world, queue, go)
    rows = _admin_sql(
        world,
        "SELECT status, attempts, last_error, next_attempt_at > now() AS later FROM catalog.outbox_events "
        "WHERE shop_id = $1 AND event_type = 'catalog.price.changed'",
        shop.id,
    )
    assert [(r["status"], r["attempts"], r["last_error"], r["later"]) for r in rows] == [
        ("PENDING", 1, "ConnectionError", True)
    ]


# ------------------------------------------------------------------ rejali ishlar: vazifalar
def test_unconfirmed_order_reminder_task_is_deduplicated_and_resolved(world: World) -> None:  # DEC-104
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    sku = shop.sku()
    shop.receive(sku, 2)
    order = shop.pending({sku: 1})
    _admin_sql(
        world,
        "UPDATE commerce.orders SET submitted_at = now() - interval '25 hours' WHERE id = $1",
        UUID(order["id"]),
    )
    first = _job(world, "order_confirm_reminder")
    assert first is not None and first.affected >= 1
    _job(world, "order_confirm_reminder")  # ikkinchi marta — yangi vazifa yo'q
    tasks = [t for t in _tasks(world, manager) if t["subject_id"] == order["id"]]
    assert len(tasks) == 1
    [task] = tasks
    assert task["type"] == "ORDER_CONFIRM_REMINDER" and task["params"] == {
        "order_number": order["number"],
        "hours": 24,
    }
    assert task["link"] == {"route": "order", "id": order["id"]}
    notes = _notifications(world, manager)
    reminder = next(n for n in notes["items"] if n["aggregate_id"] == order["id"])
    assert (
        reminder["template_key"] == "staff.order_confirm_reminder"
        and str(order["number"]) in reminder["title"]
    )
    assert notes["unread_count"] >= 1
    runs = _admin_sql(
        world,
        "SELECT status FROM platform.job_runs WHERE job_name = 'order_confirm_reminder' ORDER BY started_at",
    )
    assert [r["status"] for r in runs[-2:]] == ["OK", "OK"]

    shop.step(order, "confirm")  # sabab yo'qoldi — vazifa o'zi yopiladi
    resolved = [t for t in _tasks(world, manager, "RESOLVED") if t["subject_id"] == order["id"]]
    assert [t["type"] for t in resolved] == ["ORDER_CONFIRM_REMINDER"]


def test_reservation_review_task_closes_on_wait_decision(world: World) -> None:
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.step(shop.pending({sku: 1}), "confirm")
    _admin_sql(
        world,
        "UPDATE commerce.reservations SET review_at = now() - interval '1 hour' WHERE order_id = $1",
        UUID(order["id"]),
    )
    _job(world, "reservation_review")
    [task] = [t for t in _tasks(world, manager) if t["subject_id"] == order["id"]]
    assert task["type"] == "RESERVATION_REVIEW" and task["due_at"] is not None
    detail = shop.get(order["id"], manager)
    _ok(
        _post(
            world, manager, f"/orders/{order['id']}/review-decision", {"decision": "WAIT"}, detail["version"]
        )
    )
    assert not [t for t in _tasks(world, manager) if t["subject_id"] == order["id"]]
    _job(world, "reservation_review")  # muddat surildi — yangi vazifa yo'q
    assert not [t for t in _tasks(world, manager) if t["subject_id"] == order["id"]]


def test_adjustment_request_opens_task_for_managers_and_approval_closes_it(world: World) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 3)
    request = _ok(
        _post(
            world,
            warehouse,
            "/stock/adjustments",
            {"branch_id": shop.branch, "sku_id": sku, "delta": -1, "reason": "sanoqda kam"},
        ),
        201,
    )
    [task] = [t for t in _tasks(world, shop.owner) if t["subject_id"] == request["id"]]
    assert task["type"] == "ADJUSTMENT_APPROVAL" and task["link"] == {
        "route": "adjustment",
        "id": request["id"],
    }
    assert not [t for t in _tasks(world, warehouse) if t["subject_id"] == request["id"]]  # omborchiga emas
    _ok(_post(world, shop.owner, f"/stock/adjustments/{request['id']}/approve", version=request["version"]))
    assert not [t for t in _tasks(world, shop.owner) if t["subject_id"] == request["id"]]


def test_stock_reconcile_alerts_but_never_fixes(world: World) -> None:  # DEC-138, 5-qaror
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 5)
    _admin_sql(
        world,
        "UPDATE commerce.stock_balances SET on_hand = 7 WHERE shop_id = $1 AND sku_id = $2",
        shop.id,
        UUID(sku),
    )
    result = _job(world, "stock_reconcile")
    assert result is not None and result.details["shops_with_mismatch"] >= 1
    [task] = [t for t in _tasks(world, shop.owner) if t["type"] == "STOCK_RECONCILE_MISMATCH"]
    assert task["priority"] == "HIGH" and task["params"]["count"] == 1
    assert shop.balance(sku)["on_hand"] == 7  # avtomatik tuzatilmadi
    _job(world, "stock_reconcile")
    assert len([t for t in _tasks(world, shop.owner) if t["type"] == "STOCK_RECONCILE_MISMATCH"]) == 1


def test_stale_rate_task_resolves_when_new_rate_is_entered(world: World) -> None:
    shop = Shop(world)
    shop.rate("12800", "2026-01-01T00:00:00Z")
    shop.sku(amount=20_000, currency="USD", publish=False)
    _job(world, "exchange_rate_staleness")
    [task] = [t for t in _tasks(world, shop.owner) if t["type"] == "EXCHANGE_RATE_STALE"]
    assert task["link"] == {"route": "exchange_rates", "id": None}
    shop.rate("12850")
    assert not [t for t in _tasks(world, shop.owner) if t["type"] == "EXCHANGE_RATE_STALE"]


def test_task_done_and_assign_follow_if_match_and_visibility(world: World) -> None:
    shop = Shop(world)
    operator, operator_id = shop.staff("SALES")
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.pending({sku: 1})
    _admin_sql(
        world,
        "UPDATE commerce.orders SET submitted_at = now() - interval '30 hours' WHERE id = $1",
        UUID(order["id"]),
    )
    _job(world, "order_confirm_reminder")
    [task] = [t for t in _tasks(world, shop.owner) if t["subject_id"] == order["id"]]
    assert not [
        t for t in _tasks(world, operator) if t["subject_id"] == order["id"]
    ]  # operatorga biriktirilmagan
    path = f"/api/v1/shop/tasks/{task['id']}"
    stale = world.client.post(
        f"{path}/assign",
        json={"membership_id": operator_id},
        headers=_bearer(shop.owner, **_idem(), **{"If-Match": '"v9"'}),
    )
    assert stale.status_code == 409
    assigned = _ok(
        world.client.post(
            f"{path}/assign",
            json={"membership_id": operator_id},
            headers=_bearer(shop.owner, **_idem(), **{"If-Match": f'"v{task["version"]}"'}),
        )
    )
    assert assigned["assignee_membership_id"] == operator_id
    [mine] = [t for t in _tasks(world, operator) if t["subject_id"] == order["id"]]
    forbidden = world.client.post(
        f"{path}/assign",
        json={"membership_id": operator_id},
        headers=_bearer(operator, **_idem(), **{"If-Match": f'"v{mine["version"]}"'}),
    )
    assert forbidden.status_code == 403
    done = _ok(
        world.client.post(
            f"{path}/done", headers=_bearer(operator, **_idem(), **{"If-Match": f'"v{mine["version"]}"'})
        )
    )
    assert done["status"] == "DONE"


# ------------------------------------------------------------------ kutubxona → SKU qayta bog'lanadi
def test_approved_spec_relinks_waiting_skus_in_shops(world: World) -> None:
    owner = world.create_shop()["owner_token"]
    mpn = f"RELINK-{uuid4().hex[:10].upper()}"
    product = _create(world, owner, skus=[_sku(mpn=mpn)])
    [sku] = product["skus"]
    assert sku["spec_link"] is None
    editor = _platform_member(world)
    spec = _spec(world, world.admin_token, mpn=mpn)
    approved = _approve(world, editor, spec["id"])
    assert approved.status_code == 200, approved.text
    _drain_now(world)  # catalog.hardware_spec.updated → har shop (tranzaksiyasiz tinglovchi)
    detail = _ok(world.client.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(owner)))
    link = detail["skus"][0]["spec_link"]
    assert link is not None and link["spec_id"] == spec["id"] and link["method"] == "AUTO_MPN"


# ------------------------------------------------------------------ TD-01, TD-02
def test_partition_function_creates_append_only_partitions(world: World) -> None:  # TD-01
    _job(world, "audit_partition_create")  # joriy + 12 oy allaqachon bor — xatosiz, hech narsa
    created = _admin_sql(world, "SELECT 1")  # admin ulanishi tirik
    assert created

    async def go() -> int:
        db = Database(world.settings.database_config())  # ilova roli — DDL huquqi yo'q, funksiya orqali
        try:
            async with db.transaction() as session:
                return int(await session.scalar(text("SELECT platform.ensure_monthly_partitions(36)")) or 0)
        finally:
            await db.dispose()

    made = asyncio.run(go())
    names = [
        r["relname"]
        for r in _admin_sql(
            world,
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'transition_log'",
        )
    ]
    assert made >= 2 and len(names) >= 36
    newest = max(n for n in names if "_y" in n)
    privileges = _admin_sql(
        world,
        "SELECT has_table_privilege('app_runtime', $1, 'UPDATE') AS can_update",
        f"platform.{newest}",
    )
    assert privileges[0]["can_update"] is False  # jurnal faqat to'ldiriladi


def test_expired_idempotency_keys_are_purged(world: World) -> None:  # TD-02
    _admin_sql(
        world,
        "INSERT INTO platform.idempotency_keys (shop_id, operation, key, request_hash, expires_at) VALUES "
        "('00000000-0000-0000-0000-000000000000', 'test.op', 'old-key', 'h1:x', now() - interval '1 hour'), "
        "('00000000-0000-0000-0000-000000000000', 'test.op', 'fresh-key', 'h1:y', now() + interval '1 hour')",
    )
    result = _job(world, "idempotency_cleanup")
    assert result is not None and result.affected >= 1
    keys = {
        r["key"]
        for r in _admin_sql(world, "SELECT key FROM platform.idempotency_keys WHERE operation = 'test.op'")
    }
    assert keys == {"fresh-key"}


# ------------------------------------------------------------------ xabarnomalar: ruxsat va RLS
def test_notifications_are_private_per_member_and_shop(world: World) -> None:
    shop, other = Shop(world), Shop(world)
    manager, _ = shop.staff("MANAGER")
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 2)
    _ok(
        _post(
            world,
            warehouse,
            "/stock/adjustments",
            {"branch_id": shop.branch, "sku_id": sku, "delta": -1, "reason": "kam"},
        ),
        201,
    )
    owner_notes = _notifications(world, shop.owner)
    [note] = [n for n in owner_notes["items"] if n["template_key"] == "staff.adjustment_approval"]
    assert note["link"]["route"] == "adjustment" and note["read_at"] is None
    assert not [
        n
        for n in _notifications(world, warehouse)["items"]
        if n["template_key"] == "staff.adjustment_approval"
    ]
    # Boshqa xodim boshqa odamning xabarini o'qiy olmaydi
    assert (
        world.client.post(
            f"/api/v1/shop/notifications/{note['id']}/read", headers=_bearer(manager)
        ).status_code
        == 404
    )
    assert (
        world.client.post(
            f"/api/v1/shop/notifications/{note['id']}/read", headers=_bearer(other.owner)
        ).status_code
        == 404
    )
    read = _ok(
        world.client.post(f"/api/v1/shop/notifications/{note['id']}/read", headers=_bearer(shop.owner))
    )
    assert read["read_at"] is not None
    _ok(world.client.post("/api/v1/shop/notifications/read-all", headers=_bearer(manager)))
    assert (
        _ok(world.client.get("/api/v1/shop/notifications/unread-count", headers=_bearer(manager)))[
            "unread_count"
        ]
        == 0
    )

    async def rls() -> tuple[int, int]:
        db = Database(world.settings.database_config())
        try:
            async with db.transaction(other.id) as session:  # boshqa shop konteksti
                foreign = len(
                    (await session.execute(select(Notification).where(Notification.shop_id == shop.id))).all()
                )
            async with db.transaction() as session:  # kontekstsiz
                none = len((await session.execute(select(Notification))).all())
            return foreign, none
        finally:
            await db.dispose()

    assert asyncio.run(rls()) == (0, 0)


def test_event_payloads_contain_no_customer_data(world: World) -> None:  # 05 §11, 7-test
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 2)
    order = shop.step(shop.pending({sku: 1}), "confirm", "start-processing", "complete")
    assert order["status"] == "COMPLETED"
    all_events = [e for schema in OUTBOX_SCHEMAS for e in _events(world, schema, shop.id)]
    types = {e["type"] for e in all_events}
    assert {"commerce.order.drafted", "commerce.order.confirmed", "commerce.order.completed"} <= types
    assert {"commerce.reservation.created", "commerce.stock.changed"} <= types
    dump = json.dumps([e["envelope"] for e in all_events])
    assert PHONE not in dump and "Jasur" not in dump  # xaridor telefoni va ismi
    for event in all_events:
        assert forbidden_keys(event["envelope"]["payload"]) == [], event["type"]
    for row in _admin_sql(world, "SELECT envelope FROM platform.outbox_events WHERE shop_id = $1", shop.id):
        assert forbidden_keys(json.loads(row["envelope"])["payload"]) == []


def test_outbox_tables_exist_in_every_outbox_schema(world: World) -> None:
    for schema in OUTBOX_SCHEMAS:
        assert outbox_table(schema).schema == schema
        assert _admin_sql(world, f"SELECT count(*) AS n FROM {schema}.consumer_receipts")[0]["n"] >= 0
