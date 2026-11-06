"""5a QA tuzatishlari (F1–F11, I1–I7) va frontend so'ragan uchta backend o'zgarishi — regressiya testlari.

Navbat — `RecordingQueue` (API'da `app.state.task_queue`, worker'da test beradi); realtime — xotira broker'i.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
from starlette.websockets import WebSocketDisconnect

from app.platform.staff.infrastructure import guard
from app.shared.events.models import OUTBOX_SCHEMAS
from app.shared.events.outbox import write_outbox
from app.shared.events.registry import EventContext, Subscriber, SubscriberRegistry
from app.shared.queue import RecordingQueue
from app.shared.types.actor import ActorContext
from app.workers.dispatch import dead_letter, load_envelope
from app.workers.runtime import WorkerRuntime
from app.workers.scheduler import run_job
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _fields, _ok, _post
from tests.integration.test_jobs_events import _drain_now, _events, _job, _run, _tasks
from tests.integration.test_realtime_notifications import _closed_with, _ticket

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> None:
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )


async def _never(ctx: EventContext) -> None:  # pragma: no cover — tinglovchi chaqirilmaydi
    raise AssertionError("not called")


FAILING = Subscriber(
    consumer="test.qa_failing", event_types=frozenset({"test.qa_boom"}), schema="platform", handler=_never
)


def _dead_event(world: World, shop: Shop) -> tuple[str, str]:
    """Event + dead-letter (8 urinish tugagan) → (event_id, dead_letter_id)."""

    async def go(rt: WorkerRuntime) -> str:
        async with rt.database.transaction(shop.id) as db:
            envelope = await write_outbox(
                db,
                schema="platform",
                event_type="test.qa_boom",
                actor=ActorContext.system(shop.id),
                shop_id=shop.id,
                aggregate_type="test",
                aggregate_id=shop.id,
                aggregate_version=1,
                payload={"n": 1},
            )
        loaded = await load_envelope(rt, "platform", envelope.event_id)
        await dead_letter(rt, "platform", loaded, envelope.event_id, FAILING.consumer, 8, ValueError("x"))
        return str(envelope.event_id)

    event_id = _run(world, RecordingQueue(), go)
    _admin_sql(
        world,
        "UPDATE platform.outbox_events SET status = 'PUBLISHED', published_at = now() WHERE event_id = $1",
        UUID(event_id),
    )
    [row] = _admin_sql(world, "SELECT id FROM platform.dead_letters WHERE event_id = $1", UUID(event_id))
    return event_id, str(row["id"])


def _replay(world: World, letter_id: str) -> Any:
    return world.client.post(
        f"/api/v1/platform/dead-letters/{letter_id}/replay",
        json={"note": "xato tuzatildi"},
        headers=_bearer(world.admin_token),
    )


# ------------------------------------------------------------------ F1: qayta yuborish
def test_replay_enqueues_now_and_reconcile_picks_up_old_replays(world: World) -> None:
    shop = Shop(world)
    event_id, letter_id = _dead_event(world, shop)
    api_queue = RecordingQueue()
    world.client.app.state.task_queue = api_queue  # type: ignore[attr-defined]
    assert _ok(_replay(world, letter_id))["status"] == "REPLAYED"
    [(function, job_id, kwargs)] = api_queue.take()
    assert function == "dispatch_event" and ":replay:" in job_id
    assert kwargs == {"schema": "platform", "event_id": event_id, "consumer": FAILING.consumer}

    # 3 kun keyin ham (LOOKBACK 1 kundan eski) — rekonsilyatsiya REPLAYED'ni qayta qo'yadi
    _admin_sql(
        world,
        "UPDATE platform.outbox_events SET published_at = now() - interval '3 days' WHERE event_id = $1",
        UUID(event_id),
    )
    worker_queue = RecordingQueue()

    async def reconcile(rt: WorkerRuntime) -> None:
        rt.registry = SubscriberRegistry([FAILING])
        await run_job(rt, next(j for j in rt.jobs if j.name == "outbox_reconcile"))

    _run(world, worker_queue, reconcile)
    assert [j for j in worker_queue.jobs if j[2].get("event_id") == event_id]


def test_replay_of_purged_event_is_refused_and_cleanup_keeps_open_letters(world: World) -> None:
    shop = Shop(world)
    event_id, letter_id = _dead_event(world, shop)
    _admin_sql(
        world,
        "UPDATE platform.outbox_events SET published_at = now() - interval '20 days' WHERE event_id = $1",
        UUID(event_id),
    )
    _job(world, "outbox_cleanup")  # OPEN dead-letter'li event o'chirilmaydi
    assert _admin_sql(world, "SELECT 1 FROM platform.outbox_events WHERE event_id = $1", UUID(event_id))

    _admin_sql(world, "DELETE FROM platform.outbox_events WHERE event_id = $1", UUID(event_id))
    refused = _replay(world, letter_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"]["reason"] == "event_purged"
    [row] = _admin_sql(world, "SELECT status FROM platform.dead_letters WHERE id = $1", UUID(letter_id))
    assert row["status"] == "OPEN"  # soxta REPLAYED yo'q


# ------------------------------------------------------------------ F2: parallel birinchi saqlash
def test_concurrent_first_settings_save_gives_one_200_and_409s(world: World) -> None:
    shop = Shop(world)
    operator, _ = shop.staff("SALES")

    def save(_: int) -> int:
        return world.client.put(
            "/api/v1/shop/me/notification-settings",
            json={"telegram_enabled": False},
            headers=_bearer(operator, **{"If-Match": '"v0"'}),
        ).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(save, range(6)))
    assert codes.count(200) == 1 and set(codes) <= {200, 409}, codes


# ------------------------------------------------------------------ F3: mahsulot matni → sayt keshi
def test_product_content_changes_emit_events_and_bump_site_cache(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    _drain_now(world)
    [product] = _admin_sql(world, "SELECT product_id, version FROM catalog.skus WHERE id = $1", UUID(sku))
    product_id = str(product["product_id"])
    detail = _ok(world.client.get(f"/api/v1/shop/products/{product_id}", headers=_bearer(shop.owner)))
    cache = world.client.app.state.cache  # type: ignore[attr-defined]
    key = f"cos:v1:shop:{shop.id}:storefront:index_version"
    before = int(asyncio.run(cache.get(key)) or 0)
    patched = world.client.patch(
        f"/api/v1/shop/products/{product_id}",
        json={"title": "Yangi nom"},
        headers=_bearer(shop.owner, **{"If-Match": f'"v{detail["version"]}"'}),
    )
    assert patched.status_code == 200, patched.text
    sku_row = next(s for s in patched.json()["skus"] if s["id"] == sku)
    updated = world.client.patch(
        f"/api/v1/shop/skus/{sku}",
        json={"variant_name": "8 GB"},
        headers=_bearer(shop.owner, **{"If-Match": f'"v{sku_row["version"]}"'}),
    )
    assert updated.status_code == 200, updated.text
    types = [e["type"] for e in _events(world, "catalog", shop.id) if e["status"] == "PENDING"]
    assert types == ["catalog.product.updated", "catalog.sku.changed"]
    _drain_now(world)
    assert int(asyncio.run(cache.get(key)) or 0) == before + 2


# ------------------------------------------------------------------ F4, F10: agregat va payload
def test_stock_and_reservation_events_have_their_own_aggregates(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    _drain_now(world)
    shop.receive(sku, 2)
    shop.receive(sku, 2, branch=shop.branch2)
    order = shop.step(shop.pending({sku: 1}), "confirm")
    events = _events(world, "commerce", shop.id)
    stock = [e["envelope"] for e in events if e["type"] == "commerce.stock.changed"]
    keys = {(e["aggregate_id"], e["aggregate_version"]) for e in stock}
    assert len(keys) == len(stock)  # filiallar alohida agregat — versiya to'qnashmaydi
    assert {e["aggregate_type"] for e in stock} == {"commerce.stock_balance"}
    [reservation] = [e["envelope"] for e in events if e["type"] == "commerce.reservation.created"]
    assert reservation["aggregate_type"] == "commerce.reservation"
    assert reservation["payload"]["order_id"] == order["id"] and reservation["payload"]["qty"] == 1
    [confirmed] = [e["envelope"] for e in events if e["type"] == "commerce.order.confirmed"]
    assert confirmed["payload"]["reservation_ids"] == [reservation["payload"]["reservation_id"]]
    order_versions = [
        e["envelope"]["aggregate_version"] for e in events if e["type"].startswith("commerce.order.")
    ]
    assert len(order_versions) == len(set(order_versions))


def test_order_event_payloads_follow_contract(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 5)
    done = shop.step(shop.pending({sku: 2}), "confirm", "start-processing")
    done = _ok(
        _post(world, shop.owner, f"/orders/{done['id']}/paid-mark", {"method": "CASH"}, done["version"])
    )
    shop.step(done, "complete")
    cancelled = shop.step(shop.pending({sku: 1}), "confirm")
    _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{cancelled['id']}/cancel",
            {"reason": "xaridor voz kechdi"},
            cancelled["version"],
        )
    )
    events = {
        (e["type"], e["envelope"]["payload"]["order_id"]): e["envelope"]["payload"]
        for e in _events(world, "commerce", shop.id)
        if e["type"].startswith("commerce.order.")
    }
    completed = events[("commerce.order.completed", done["id"])]
    [line] = completed["lines"]
    assert line["sku_id"] == sku and line["qty"] == 2 and line["unit_price_minor"] == 480_000_000
    assert events[("commerce.order.paid_marked", done["id"])]["marked_by"]
    payload = events[("commerce.order.cancelled", cancelled["id"])]
    assert payload["reason_code"] == "STAFF_CANCELLED" and payload["from_status"] == "CONFIRMED"
    assert "voz" not in json.dumps(payload)  # erkin matn event'ga tushmaydi


# ------------------------------------------------------------------ F5: orqaga sanalgan kurs
def test_backdated_rate_does_not_resolve_stale_task(world: World) -> None:
    shop = Shop(world)
    shop.rate("12800", "2026-01-01T00:00:00Z")
    shop.sku(amount=20_000, currency="USD", publish=False)
    _job(world, "exchange_rate_staleness")
    assert [t for t in _tasks(world, shop.owner) if t["type"] == "EXCHANGE_RATE_STALE"]
    shop.rate("12810", "2026-01-02T00:00:00Z")  # o'zi ham eskirgan — vazifa ochiq qoladi
    assert [t for t in _tasks(world, shop.owner) if t["type"] == "EXCHANGE_RATE_STALE"]
    _job(world, "exchange_rate_staleness")  # yangi davr (oxirgi kurs o'zgardi) — bitta vazifa, dublikatsiz
    assert len([t for t in _tasks(world, shop.owner) if t["type"] == "EXCHANGE_RATE_STALE"]) <= 2
    shop.rate("12850")
    assert not [t for t in _tasks(world, shop.owner) if t["type"] == "EXCHANGE_RATE_STALE"]


# ------------------------------------------------------------------ F7: omborchi ro'yxatidan chiqadi
def test_warehouse_gets_signal_when_confirmed_order_is_cancelled(world: World) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 3)
    order = shop.step(shop.pending({sku: 1}), "confirm")
    _drain_now(world)
    with world.client.websocket_connect(f"/api/v1/ws?ticket={_ticket(world.client, warehouse)}") as ws:
        assert ws.receive_json()["type"] == "hello"
        _ok(_post(world, shop.owner, f"/orders/{order['id']}/cancel", {"reason": "bekor"}, order["version"]))
        _drain_now(world)
        received = [ws.receive_json() for _ in range(2)]
    orders = [m for m in received if m["type"] == "order.changed"]
    assert orders and orders[0]["resource"]["id"] == order["id"]


# ------------------------------------------------------------------ F8, I5: vazifa rollari
def test_approval_task_cannot_go_to_requester_or_wrong_role(world: World) -> None:
    shop = Shop(world)
    warehouse, warehouse_id = shop.staff("WAREHOUSE")
    operator, operator_id = shop.staff("SALES")
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
    path = f"/api/v1/shop/tasks/{task['id']}"
    for member in (warehouse_id, operator_id):  # so'rov egasi va noto'g'ri rol
        refused = world.client.post(
            f"{path}/assign",
            json={"membership_id": member},
            headers=_bearer(shop.owner, **_idem(), **{"If-Match": f'"v{task["version"]}"'}),
        )
        assert refused.status_code == 422 and _fields(refused) == {"membership_id": "invalid_choice"}
    denied = world.client.post(
        f"{path}/assign",
        json={"membership_id": operator_id},
        headers=_bearer(operator, **_idem(), **{"If-Match": f'"v{task["version"]}"'}),
    )
    assert (
        denied.status_code == 403 and denied.json()["error"]["details"]["permission"] == "staff.task.assign"
    )
    extra = world.client.post(
        f"{path}/assign",
        json={"membership_id": operator_id, "x": 1},
        headers=_bearer(shop.owner, **_idem(), **{"If-Match": f'"v{task["version"]}"'}),
    )
    assert extra.status_code == 422  # extra="forbid"
    done = _ok(
        world.client.post(
            f"{path}/done", headers=_bearer(shop.owner, **_idem(), **{"If-Match": f'"v{task["version"]}"'})
        )
    )
    assert done["status"] == "DONE"


# ------------------------------------------------------------------ F9: sozlama tekshiruvi
@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"quiet_form": "23:00"}, "quiet_form"),
        ({"quiet_from": "09:00", "quiet_to": "09:00"}, "quiet_to"),
        ({"quiet_from": "22:00:00+03:00", "quiet_to": "07:00"}, "quiet_from"),
        ({"muted_types": ["staff.unknown"]}, "muted_types"),
        ({"muted_types": ["staff.new_order"]}, "muted_types"),  # HIGH — o'chirilmaydi
    ],
)
def test_notification_settings_reject_bad_input(world: World, body: dict[str, Any], field: str) -> None:
    shop = Shop(world)
    response = world.client.put(
        "/api/v1/shop/me/notification-settings",
        json=body,
        headers=_bearer(shop.owner, **{"If-Match": '"v0"'}),
    )
    assert response.status_code == 422, response.text
    assert field in _fields(response)


# ------------------------------------------------------------------ F11, I1: realtime cheklovlari
def test_ws_ticket_rate_limit_and_socket_cap(world: World) -> None:
    shop = Shop(world)
    operator, _ = shop.staff("SALES")
    tickets = [_ticket(world.client, operator) for _ in range(6)]
    sockets = [world.client.websocket_connect(f"/api/v1/ws?ticket={t}") for t in tickets[:5]]
    try:
        for ws in sockets:
            assert ws.__enter__().receive_json()["type"] == "hello"
        with world.client.websocket_connect(f"/api/v1/ws?ticket={tickets[5]}") as sixth:
            assert _closed_with(sixth) == 4429
    finally:
        for ws in sockets:
            ws.__exit__(None, None, None)
    for _ in range(30 - 6):
        _ticket(world.client, operator)
    limited = world.client.post("/api/v1/auth/ws-ticket", headers=_bearer(operator))
    assert limited.status_code == 429 and limited.headers.get("Retry-After")


def test_ws_handshake_checks_origin(world: World) -> None:
    shop = Shop(world)
    allowed = world.client.app.state.ws_allowed_origins[0]  # type: ignore[attr-defined]
    ticket = _ticket(world.client, shop.owner)
    with pytest.raises(WebSocketDisconnect) as refused:
        with world.client.websocket_connect(
            f"/api/v1/ws?ticket={ticket}", headers={"Origin": "https://evil.example"}
        ):
            pass
    assert refused.value.code == 1008
    good = _ticket(world.client, shop.owner)
    with world.client.websocket_connect(f"/api/v1/ws?ticket={good}", headers={"Origin": allowed}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_shop_surface_rate_limit_per_user(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    shop = Shop(world)
    operator, _ = shop.staff("SALES")  # hali /shop so'rovi qilmagan xodim — hisob noldan
    monkeypatch.setattr(guard, "SHOP_USER_REQUESTS_PER_MINUTE", 3)
    codes = [world.client.get("/api/v1/shop/tasks", headers=_bearer(operator)).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    assert world.client.get("/api/v1/shop/tasks", headers=_bearer(shop.owner)).status_code != 500


# ------------------------------------------------------------------ I2, I7: fon ishlari sahifasi
def test_platform_jobs_lists_every_registered_job_and_alerts(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 5)
    _admin_sql(
        world,
        "UPDATE commerce.stock_balances SET on_hand = 9 WHERE shop_id = $1 AND sku_id = $2",
        shop.id,
        UUID(sku),
    )
    _job(world, "stock_reconcile")
    jobs = {
        j["job_name"]: j
        for j in _ok(world.client.get("/api/v1/platform/jobs", headers=_bearer(world.admin_token)))["items"]
    }
    registered = {name for name, _, _ in world.client.app.state.scheduled_jobs}  # type: ignore[attr-defined]
    assert registered <= set(jobs)
    assert jobs["stock_reconcile"]["alert"] is True and jobs["stock_reconcile"]["schedule"] == "30 3 * * *"
    assert jobs["audit_partition_create"]["interval_seconds"] == 31 * 86400
    never = [j for j in jobs.values() if j["last_started_at"] is None]
    assert all(j["last_status"] is None for j in never)
    _admin_sql(
        world,
        "UPDATE commerce.stock_balances SET on_hand = 5 WHERE shop_id = $1 AND sku_id = $2",
        shop.id,
        UUID(sku),
    )


# ------------------------------------------------------------------ I6: shop holati event'lari
def test_shop_activation_emits_platform_event(world: World) -> None:
    created = world.create_shop()
    world.branch(created["owner_token"])
    _ok(
        world.client.post(
            "/api/v1/shop/profile/submit-for-verification", headers=_bearer(created["owner_token"], **_idem())
        )
    )
    shop_id = created["shop"]["id"]
    _ok(
        world.client.post(
            f"/api/v1/platform/shops/{shop_id}/activate", headers=_bearer(world.admin_token, **_idem())
        )
    )
    [event] = [e for e in _events(world, "platform", UUID(shop_id)) if e["type"] == "platform.shop.activated"]
    assert event["envelope"]["payload"]["from_status"] == "PENDING_VERIFICATION"


# ------------------------------------------------------------------ (a), (b): frontend so'ragani
def test_tasks_assigned_filter_and_me_membership(world: World) -> None:
    shop = Shop(world)
    operator, operator_id = shop.staff("SALES")
    me = _ok(world.client.get("/api/v1/auth/me", headers=_bearer(operator)))
    assert me["membership_id"] == operator_id
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

    def listed(token: str, assigned: str) -> list[str]:
        items = _ok(world.client.get(f"/api/v1/shop/tasks?assigned={assigned}", headers=_bearer(token)))[
            "items"
        ]
        return [t["id"] for t in items]

    first = task["assignee_membership_id"]  # xodim yaratgan buyurtma — yaratganga biriktirilgan
    assert task["id"] in listed(shop.owner, first or "unassigned")
    _ok(
        world.client.post(
            f"/api/v1/shop/tasks/{task['id']}/assign",
            json={"membership_id": operator_id},
            headers=_bearer(shop.owner, **_idem(), **{"If-Match": f'"v{task["version"]}"'}),
        )
    )
    assert task["id"] in listed(operator, "me") and task["id"] in listed(shop.owner, operator_id)
    assert task["id"] not in listed(shop.owner, "unassigned")
    bad = world.client.get("/api/v1/shop/tasks?assigned=nobody", headers=_bearer(shop.owner))
    assert bad.status_code == 422
