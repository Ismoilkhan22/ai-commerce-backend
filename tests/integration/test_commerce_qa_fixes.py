"""3-modul QA tekshiruvi topilmalari (F1–F10, kuzatuvlar) va frontend so'ragan endpoint'lar — regressiya.

Har test bitta topilma: QA hisobotidagi qadamlar qisqartirilgan holda.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from tests import images
from tests.integration import test_commerce as base
from tests.integration.helpers import World, _bearer, _code, _idem

pytestmark = pytest.mark.integration

Shop = base.Shop
_post, _ok, _fields, _hdr, _admin_sql = base._post, base._ok, base._fields, base._hdr, base._admin_sql
MAX_STOCK = 2**31 - 1


def _product(shop: Any, *, publish: bool = True) -> tuple[str, str]:
    """(product_id, sku_id) — so'mda narxli mahsulot."""
    code = f"Q-{uuid4().hex[:10]}"
    body = {
        "category_code": "GPU",
        "title": f"QA GPU {code}",
        "skus": [{"sku_code": code, "price": {"amount_minor": 100_000_00, "currency": "UZS"}}],
    }
    product = _ok(shop.world.client.post("/api/v1/shop/products", json=body, headers=_hdr(shop.owner)), 201)
    if publish:
        _ok(_post(shop.world, shop.owner, f"/products/{product['id']}/publish"))
    return str(product["id"]), str(product["skus"][0]["id"])


def _get(world: World, token: str, path: str) -> Any:
    return world.client.get(f"/api/v1/shop{path}", headers=_bearer(token))


# ------------------------------------------------------------------ F1: to'xtatilgan shop


def test_suspended_shop_blocks_new_sales_but_finishes_existing(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 3)
    existing = shop.pending({sku: 1})
    _admin_sql(world, "UPDATE platform.shops SET status = 'SUSPENDED' WHERE id = $1", shop.id)

    new_order = _post(
        world,
        shop.owner,
        "/orders",
        {"customer_name": "QA", "customer_phone": base.PHONE, "lines": [{"sku_id": sku, "qty": 1}]},
    )
    assert new_order.status_code == 409 and _code(new_order) == "SHOP_NOT_ACTIVE"
    assert new_order.json()["error"]["details"]["shop_status"] == "SUSPENDED"
    sale = _post(
        world, shop.owner, "/quick-sales", {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
    )
    assert _code(sale) == "SHOP_NOT_ACTIVE"
    # Eskilari yakunlanadi (TC-023), ombor ishi davom etadi
    confirmed = shop.step(existing, "confirm")
    assert confirmed["status"] == "CONFIRMED"
    shop.receive(sku, 1)


# ------------------------------------------------------------------ F3: INT chegarasi


def test_stock_above_int_limit_is_a_field_error(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1)
    _admin_sql(
        world,
        "UPDATE commerce.stock_balances SET on_hand = $1 WHERE shop_id = $2",
        MAX_STOCK - 5,
        shop.id,
    )
    receipt = _post(
        world,
        shop.owner,
        "/stock/receipts",
        {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 10}]},
    )
    assert receipt.status_code == 422 and _fields(receipt) == {"lines[0].qty": "max_value"}
    adjust = _post(
        world,
        shop.owner,
        "/stock/adjustments",
        {"branch_id": shop.branch, "sku_id": sku, "kind": "ADJUSTMENT", "delta": 10, "reason": "QA sanoq"},
    )
    assert adjust.status_code == 422 and _fields(adjust) == {"delta": "max_value"}


# ------------------------------------------------------------------ F4: arxiv va qoralama


def test_quick_sale_only_for_published_or_hidden_products(world: World) -> None:
    shop = Shop(world)
    _, draft_sku = _product(shop, publish=False)
    shop.receive(draft_sku, 2)
    refused = _post(
        world,
        shop.owner,
        "/quick-sales",
        {"branch_id": shop.branch, "lines": [{"sku_id": draft_sku, "qty": 1}]},
    )
    assert _code(refused) == "PRODUCT_NOT_AVAILABLE"
    assert refused.json()["error"]["details"]["lines"][0]["product_status"] == "DRAFT"

    hidden_product, hidden_sku = _product(shop)
    _ok(_post(world, shop.owner, f"/products/{hidden_product}/hide"))
    shop.receive(hidden_sku, 1)
    sale = _post(
        world,
        shop.owner,
        "/quick-sales",
        {"branch_id": shop.branch, "lines": [{"sku_id": hidden_sku, "qty": 1}]},
    )
    assert sale.status_code == 201, sale.text  # saytdan yashirilgan — do'konda sotilaveradi


def test_archived_sku_stock_can_only_be_written_off(world: World) -> None:
    shop = Shop(world)
    product, sku = _product(shop)
    shop.receive(sku, 3)
    _ok(_post(world, shop.owner, f"/products/{product}/archive", {"reason": "QA eskirdi"}))

    receipt = _post(
        world, shop.owner, "/stock/receipts", {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
    )
    assert _code(receipt) == "PRODUCT_NOT_AVAILABLE"

    def adjust(kind: str, delta: int) -> Any:
        body = {
            "branch_id": shop.branch,
            "sku_id": sku,
            "kind": kind,
            "delta": delta,
            "reason": "QA hisobdan",
        }
        return _post(world, shop.owner, "/stock/adjustments", body)

    assert _code(adjust("ADJUSTMENT", 1)) == "PRODUCT_NOT_AVAILABLE"
    assert _ok(adjust("ADJUSTMENT", -1), 201)["status"] == "APPROVED"
    assert _ok(adjust("QUARANTINE_IN", 1), 201)["status"] == "APPROVED"
    assert _ok(adjust("WRITE_OFF", 1), 201)["status"] == "APPROVED"
    assert _code(adjust("RESTOCK", 1)) == "PRODUCT_NOT_AVAILABLE"
    assert shop.balance(sku)["on_hand"] == 1


# ------------------------------------------------------------------ F5: biriktirish va filial doirasi


def test_assign_requires_assignee_branch_scope(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1, branch=shop.branch2)
    _, scoped_id, _ = world.invite(shop.owner, "SALES", branch_scope="SELECTED", branch_ids=[shop.branch])
    order = shop.order({sku: 1}, branch_id=shop.branch2)
    refused = _post(
        world, shop.owner, f"/orders/{order['id']}/assign", {"membership_id": scoped_id}, order["version"]
    )
    assert refused.status_code == 422 and _fields(refused) == {"membership_id": "invalid_choice"}


# ------------------------------------------------------------------ F6: telefon


def test_incomplete_customer_phone_is_rejected(world: World) -> None:
    shop = Shop(world)
    for phone in ("+998 99 1234", "+998 33 1234 x", "abc+998901234567def"):
        response = _post(world, shop.owner, "/orders", {"customer_name": "QA", "customer_phone": phone})
        assert response.status_code == 422 and _fields(response) == {"customer_phone": "invalid_format"}


# ------------------------------------------------------------------ F7: dalil havolasi va takroriy so'rov


def test_adjustment_replay_does_not_persist_signed_url(world: World) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 2)
    upload = world.client.post(
        "/api/v1/shop/files?purpose=STOCK_EVIDENCE&filename=dalil.png",
        content=images.png(),
        headers=_bearer(warehouse, **_idem(), **{"Content-Type": "image/png"}),
    )
    file = _ok(upload, 201)
    key = str(uuid4())
    body = {
        "branch_id": shop.branch,
        "sku_id": sku,
        "delta": -1,
        "reason": "QA singan",
        "evidence_file_id": file["id"],
    }
    headers = _bearer(warehouse, **{"Idempotency-Key": key})
    first = _ok(world.client.post("/api/v1/shop/stock/adjustments", json=body, headers=headers), 201)
    stored = _admin_sql(
        world, "SELECT response_body::text AS body FROM platform.idempotency_keys WHERE key = $1", key
    )
    assert stored and "sig=" not in stored[0]["body"] and first["id"] in stored[0]["body"]
    replay = _ok(world.client.post("/api/v1/shop/stock/adjustments", json=body, headers=headers), 201)
    assert replay["id"] == first["id"] and "sig=" in replay["evidence"]["url"]


# ------------------------------------------------------------------ F9, F10


def test_note_location_and_product_status_on_confirm(world: World) -> None:
    shop = Shop(world)
    product, sku = _product(shop)
    shop.receive(sku, 1)
    order = shop.pending({sku: 1})
    note = world.client.post(
        f"/api/v1/shop/orders/{order['id']}/notes", json={"body": "QA izoh"}, headers=_hdr(shop.owner)
    )
    assert note.status_code == 201 and note.headers["Location"] == f"/api/v1/shop/orders/{order['id']}"
    _ok(_post(world, shop.owner, f"/products/{product}/hide"))
    confirm = _post(
        world, shop.owner, f"/orders/{order['id']}/confirm", version=shop.get(order["id"])["version"]
    )
    assert _code(confirm) == "PRODUCT_NOT_AVAILABLE"
    line = confirm.json()["error"]["details"]["lines"][0]
    assert (line["sku_id"], line["product_status"], line["sku_status"]) == (sku, "HIDDEN", "ACTIVE")


# ------------------------------------------------------------------ kuzatuvlar


def test_exception_order_enters_72h_review_and_expires(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.step(shop.pending({sku: 1}), "confirm", "start-processing")
    order = _ok(
        _post(
            world, shop.owner, f"/orders/{order['id']}/exception", {"reason": "QA shikast"}, order["version"]
        )
    )
    _admin_sql(
        world,
        "UPDATE commerce.reservations SET review_at = now() - interval '1 hour' WHERE order_id = $1",
        UUID(order["id"]),
    )
    queue = _ok(_get(world, shop.owner, "/orders/review-queue"))
    assert order["id"] in [o["id"] for o in queue["reservations"]]
    cancelled = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/review-decision",
            {"decision": "CANCEL", "reason": "QA kelmadi"},
            shop.get(order["id"])["version"],
        )
    )
    assert cancelled["status"] == "CANCELLED" and cancelled["lines"][0]["reservation"]["status"] == "EXPIRED"
    assert shop.balance(sku)["available"] == 1


def test_warehouse_sees_masked_phone_and_no_pickup_address(world: World) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.step(shop.pending({sku: 1}), "confirm")
    seen = shop.get(order["id"], warehouse)
    assert seen["customer_phone"] == "+998 90 *** ** 67" and seen["delivery_address"] is None
    assert shop.get(order["id"])["customer_phone"] == base.PHONE  # ega — to'liq


def test_invisible_characters_stripped_from_customer_text(world: World) -> None:
    shop = Shop(world)
    order = _ok(
        _post(
            world,
            shop.owner,
            "/orders",
            {"customer_name": "Ali‮​ Valiyev", "customer_comment": "⁦kechqurun⁩"},
        ),
        201,
    )
    assert (order["customer_name"], order["customer_comment"]) == ("Ali Valiyev", "kechqurun")


# ------------------------------------------------------------------ frontend so'ragan endpoint'lar


def test_branch_options_open_to_every_member_with_scope(world: World) -> None:
    shop = Shop(world)
    _, _, scoped = world.invite(shop.owner, "WAREHOUSE", branch_scope="SELECTED", branch_ids=[shop.branch])
    sales, _ = shop.staff("SALES")
    assert _get(world, scoped, "/branches").status_code == 403  # to'liq ro'yxat — sozlamalar ruxsati
    options = _ok(_get(world, scoped, "/branches/options"))["items"]
    assert [b["id"] for b in options] == [shop.branch]
    assert set(options[0]) == {"id", "name", "status", "is_pickup_point"}
    assert {b["id"] for b in _ok(_get(world, sales, "/branches/options"))["items"]} == {
        shop.branch,
        shop.branch2,
    }


def test_openapi_schema_names_are_clean(world: World) -> None:
    names = world.client.get("/api/v1/openapi.json").json()["components"]["schemas"]
    assert not [n for n in names if n.startswith("app__")]


def test_sku_picker_returns_price_status_and_branch_stock(world: World) -> None:
    shop = Shop(world)
    _, sku = _product(shop)
    _, draft = _product(shop, publish=False)
    shop.receive(sku, 4)
    sales, _ = shop.staff("SALES")
    items = _ok(_get(world, sales, f"/skus?q=QA%20GPU&branch_id={shop.branch}"))["items"]
    by_id = {i["sku_id"]: i for i in items}
    assert by_id[sku]["available"] == 4 and by_id[sku]["orderable"] and by_id[sku]["quick_sellable"]
    assert by_id[sku]["uzs_amount_minor"] == 100_000_00 and by_id[sku]["product_status"] == "PUBLISHED"
    assert by_id[draft]["orderable"] is False and by_id[draft]["quick_sellable"] is False
    assert by_id[draft]["available"] == 0
    assert all(i["available"] is None for i in _ok(_get(world, sales, "/skus?q=QA%20GPU"))["items"])


def test_order_history_lists_who_did_each_step(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.step(shop.pending({sku: 1}), "confirm")
    history = _ok(_get(world, shop.owner, f"/orders/{order['id']}/history"))["items"]
    assert [(h["command"], h["from_status"], h["to_status"]) for h in history] == [
        ("SUBMIT", "DRAFT", "PENDING_CONFIRMATION"),
        ("CONFIRM", "PENDING_CONFIRMATION", "CONFIRMED"),
    ]
    assert all(h["actor_name"] == "Ali Valiyev" and h["actor_type"] == "STAFF" for h in history)
    assert base.PHONE not in str(history)
