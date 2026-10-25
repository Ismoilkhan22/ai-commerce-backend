"""3-modul QA 2-tur topilmalari (N1–N5, F5–F7 qoldiqlari, U3, U4, platforma yopish) — regressiya."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests import images
from tests.integration import test_commerce as base
from tests.integration.conftest import PgUrls
from tests.integration.helpers import World, _bearer, _code, _idem

pytestmark = pytest.mark.integration

Shop = base.Shop
_post, _ok, _fields, _hdr, _admin_sql = base._post, base._ok, base._fields, base._hdr, base._admin_sql
FULLWIDTH, ARABIC = "９０９９３０００１", "٩٠١٢٣٤٥٦٧"


# ------------------------------------------------------------------ N1: SQL parametrlari logga chiqmaydi


def test_db_errors_do_not_echo_sql_parameters(migrated: PgUrls) -> None:
    from app.shared.db.session import Database, DatabaseConfig

    secret_phone, secret_name = "+998٩٠٩٩٣٠٠٠١", f"QA Secret {uuid4().hex[:6]}"

    async def run() -> str:
        database = Database(DatabaseConfig(url=migrated.runtime))
        try:
            async with database.transaction() as session:
                await session.execute(
                    text(
                        "INSERT INTO platform.principals (id, phone, full_name, version) "
                        "VALUES (:id, :phone, :name, 1)"
                    ),
                    {"id": uuid4(), "phone": secret_phone, "name": secret_name},
                )
        except DBAPIError as exc:
            return str(exc)
        finally:
            await database.dispose()
        raise AssertionError("CHECK violation expected")

    message = asyncio.run(run())
    assert "ck_principals_phone_e164" in message
    assert secret_phone not in message and secret_name not in message
    assert "hidden" in message.lower()


# ------------------------------------------------------------------ API orqali


def test_non_ascii_digits_in_phones_are_rejected(world: World) -> None:  # N1
    shop = Shop(world)
    invite = world.client.post(
        "/api/v1/shop/members/invites",
        json={"phone": FULLWIDTH, "full_name": "QA Fullwidth", "role": "SALES"},
        headers=_bearer(shop.owner, **_idem()),
    )
    assert invite.status_code == 422 and _fields(invite) == {"phone": "invalid_format"}
    order = _post(world, shop.owner, "/orders", {"customer_name": "QA", "customer_phone": ARABIC})
    assert order.status_code == 422 and _fields(order) == {"customer_phone": "invalid_format"}
    branch = world.client.post(
        "/api/v1/shop/branches",
        json={"name": "QA", "address": "Toshkent", "phone": "٧١٢٠٠٠٠٠٠"},
        headers=_bearer(shop.owner, **_idem()),
    )
    assert branch.status_code == 422 and _fields(branch) == {"phone": "invalid_format"}
    login = world.client.post(
        "/api/v1/auth/login", json={"phone": FULLWIDTH, "password": "x" * 10, "audience": "shop"}
    )
    assert login.status_code == 401


def test_suspended_shop_cannot_grow_existing_orders(world: World) -> None:  # N2
    shop = Shop(world)
    sku, other = shop.sku(), shop.sku()
    shop.receive(sku, 10)
    shop.receive(other, 10)
    draft = shop.order({sku: 2})
    pending = shop.pending({sku: 2})
    _admin_sql(world, "UPDATE platform.shops SET status = 'SUSPENDED' WHERE id = $1", shop.id)

    added = _post(
        world, shop.owner, f"/orders/{draft['id']}/lines", {"sku_id": other, "qty": 1}, draft["version"]
    )
    assert added.status_code == 409 and _code(added) == "SHOP_NOT_ACTIVE"
    line = draft["lines"][0]
    path = f"/api/v1/shop/orders/{draft['id']}/lines/{line['id']}"
    grown = world.client.patch(path, json={"qty": 5}, headers=_hdr(shop.owner, draft["version"]))
    assert grown.status_code == 409 and _code(grown) == "SHOP_NOT_ACTIVE"
    shrunk = _ok(world.client.patch(path, json={"qty": 1}, headers=_hdr(shop.owner, draft["version"])))
    assert shrunk["lines"][0]["qty"] == 1
    submit = _post(world, shop.owner, f"/orders/{draft['id']}/submit", version=shrunk["version"])
    assert submit.status_code == 409 and _code(submit) == "SHOP_NOT_ACTIVE"
    # Yuborilgan buyurtma esa oxiriga yetkaziladi (TC-023)
    confirmed = _ok(_post(world, shop.owner, f"/orders/{pending['id']}/confirm", version=pending["version"]))
    assert confirmed["status"] == "CONFIRMED"


def test_upload_replay_returns_fresh_link_and_stores_only_id(world: World) -> None:  # N4
    shop = Shop(world)
    key = str(uuid4())
    headers = _bearer(shop.owner, **{"Idempotency-Key": key, "Content-Type": "image/png"})
    url = "/api/v1/shop/files?purpose=STOCK_EVIDENCE&filename=dalil.png"
    data = images.png()
    first = _ok(world.client.post(url, content=data, headers=headers), 201)
    stored = _admin_sql(
        world, "SELECT response_body::text AS body FROM platform.idempotency_keys WHERE key = $1", key
    )
    assert stored and "sig=" not in stored[0]["body"] and first["id"] in stored[0]["body"]
    replay = _ok(world.client.post(url, content=data, headers=headers), 201)
    assert replay["id"] == first["id"] and "sig=" in replay["url"]


def test_invisible_characters_are_stripped_from_customer_name(world: World) -> None:  # N5
    shop = Shop(world)
    name = "QA ­͏᠎ Soft⁠﻿"
    order = _ok(
        _post(world, shop.owner, "/orders", {"customer_name": name, "customer_phone": base.PHONE}), 201
    )
    assert order["customer_name"] == "QA Soft"


def test_branch_change_must_stay_in_assignee_scope(world: World) -> None:  # F5
    shop = Shop(world)
    sku = shop.sku()
    _, scoped_id, _ = world.invite(shop.owner, "SALES", branch_scope="SELECTED", branch_ids=[shop.branch])
    order = shop.order({sku: 1}, branch_id=None)
    assigned = _ok(
        _post(
            world, shop.owner, f"/orders/{order['id']}/assign", {"membership_id": scoped_id}, order["version"]
        )
    )
    moved = world.client.patch(
        f"/api/v1/shop/orders/{order['id']}",
        json={"branch_id": shop.branch2},
        headers=_hdr(shop.owner, assigned["version"]),
    )
    assert moved.status_code == 422 and _fields(moved) == {"branch_id": "out_of_scope"}
    inside = world.client.patch(
        f"/api/v1/shop/orders/{order['id']}",
        json={"branch_id": shop.branch},
        headers=_hdr(shop.owner, assigned["version"]),
    )
    assert inside.status_code == 200, inside.text


def test_mark_ready_records_who_and_shows_in_history(world: World) -> None:  # U3
    shop = Shop(world)
    warehouse, warehouse_id = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.step(shop.pending({sku: 1}), "confirm")
    order = shop.step(order, "start-processing", "mark-ready", token=warehouse)
    assert order["ready_by"]["membership_id"] == warehouse_id
    history = _ok(world.client.get(f"/api/v1/shop/orders/{order['id']}/history", headers=_bearer(shop.owner)))
    ready = [item for item in history["items"] if item["command"] == "MARK_READY"]
    assert len(ready) == 1 and ready[0]["actor_name"] and ready[0]["to_status"] == "PROCESSING"
    again = shop.step(order, "mark-ready", token=warehouse)  # ikkinchi bosish — tarixga yozilmaydi
    assert again["ready_at"] == order["ready_at"]
    history = _ok(world.client.get(f"/api/v1/shop/orders/{order['id']}/history", headers=_bearer(shop.owner)))
    assert [i["command"] for i in history["items"]].count("MARK_READY") == 1


def test_warehouse_sees_why_unconfirmed_order_is_hidden(world: World) -> None:  # U4
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    order = shop.order({shop.sku(): 1})
    response = world.client.get(f"/api/v1/shop/orders/{order['id']}", headers=_bearer(warehouse))
    assert response.status_code == 403 and response.json()["error"]["details"]["reason"] == "not_confirmed"
    sales, _ = shop.staff("SALES")
    taken = shop.step(order, "take")  # ega o'ziga oldi
    response = world.client.get(f"/api/v1/shop/orders/{taken['id']}", headers=_bearer(sales))
    assert response.status_code == 403 and response.json()["error"]["details"]["reason"] == "other_operator"


def test_shop_with_open_orders_cannot_be_closed(world: World) -> None:  # TC-023
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 3)
    pending = shop.pending({sku: 1})
    confirmed = shop.step(shop.pending({sku: 1}), "confirm")
    shop.order({sku: 1})  # qoralama — ochiq hisoblanmaydi
    _admin_sql(world, "UPDATE platform.shops SET status = 'ACTIVE' WHERE id = $1", shop.id)
    admin = _bearer(world.admin_token, **_idem())
    close_url = f"/api/v1/platform/shops/{shop.id}/close"
    refused = world.client.post(close_url, json={"reason": "QA yopish"}, headers=admin)
    assert refused.status_code == 409 and _code(refused) == "SHOP_HAS_OPEN_ORDERS"
    details = refused.json()["error"]["details"]
    assert details["open_orders"] == {"PENDING_CONFIRMATION": 1, "CONFIRMED": 1} and details["total"] == 2
    for order in (pending, confirmed):
        current = shop.get(order["id"])
        _ok(
            _post(
                world,
                shop.owner,
                f"/orders/{order['id']}/cancel",
                {"reason": "QA yopiladi"},
                current["version"],
            )
        )
    closed = world.client.post(
        close_url, json={"reason": "QA yopish"}, headers=_bearer(world.admin_token, **_idem())
    )
    assert closed.status_code == 200, closed.text
