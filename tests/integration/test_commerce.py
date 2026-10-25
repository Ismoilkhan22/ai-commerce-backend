"""3-modul (savdo): ombor, tez sotuv, buyurtmalar va band qilish — haqiqiy PostgreSQL'da, HTTP orqali.

Qabul mezonlari (vazifa kartasi, 12 §11): oxirgi dona poygasi (TC-002/003, TC-027), bir marta kamayish
(TC-030), narx o'zgarishi (TC-031), deadlock'siz qulf tartibi (TC-CON-10), tuzatish qayta tekshiruvi
(TC-CON-12), daftar o'zgarmasligi, RLS, rollar, PII shifrlanishi, 72 soatlik qarorlar.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.integration.helpers import World, _bearer, _code, _idem, _sql

pytestmark = pytest.mark.integration

PHONE = "+998901234567"


# ------------------------------------------------------------------ yordamchilar


def _hdr(token: str, version: int | None = None) -> dict[str, str]:
    extra = {"If-Match": f'"v{version}"'} if version is not None else {}
    return _bearer(token, **_idem(), **extra)


def _post(world: World, token: str, path: str, body: Any = None, version: int | None = None) -> Any:
    return world.client.post(f"/api/v1/shop{path}", json=body, headers=_hdr(token, version))


def _ok(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    return dict(response.json())


def _fields(response: Any) -> dict[str, str]:
    return {f["field"]: f["code"] for f in response.json()["error"]["details"].get("fields", [])}


class Shop:
    """Shop + ega + ikki filial; mahsulotlar, xodimlar va qoldiq — yordamchilar orqali."""

    def __init__(self, world: World) -> None:
        self.world = world
        created = world.create_shop()
        self.id = UUID(created["shop"]["id"])
        self.owner = created["owner_token"]
        self.branch = world.branch(self.owner, "Chilonzor")["id"]
        self.branch2 = world.branch(self.owner, "Yunusobod")["id"]

    def staff(self, role: str) -> tuple[str, str]:
        """(token, membership_id)"""
        _, member_id, token = self.world.invite(self.owner, role)
        return token, member_id

    def sku(self, amount: int = 480_000_000, currency: str = "UZS", *, publish: bool = True) -> str:
        code = f"C-{uuid4().hex[:10]}"
        body = {
            "category_code": "GPU",
            "title": f"Test GPU {code}",
            "skus": [
                {
                    "sku_code": code,
                    "warranty_months": 24,
                    "price": {"amount_minor": amount, "currency": currency},
                }
            ],
        }
        product = _ok(
            self.world.client.post("/api/v1/shop/products", json=body, headers=_hdr(self.owner)), 201
        )
        if publish:
            _ok(_post(self.world, self.owner, f"/products/{product['id']}/publish"))
        return str(product["skus"][0]["id"])

    def rate(self, rate: str, effective_at: str | None = None) -> None:
        body: dict[str, Any] = {"rate": rate}
        if effective_at:
            body["effective_at"] = effective_at
        _ok(_post(self.world, self.owner, "/exchange-rates", body), 201)

    def receive(
        self, sku: str, qty: int, branch: str | None = None, token: str | None = None
    ) -> dict[str, Any]:
        body = {"branch_id": branch or self.branch, "lines": [{"sku_id": sku, "qty": qty}]}
        return _ok(_post(self.world, token or self.owner, "/stock/receipts", body), 201)

    def order(self, lines: dict[str, int], token: str | None = None, **extra: Any) -> dict[str, Any]:
        body = {
            "customer_name": "Jasur",
            "customer_phone": PHONE,
            "branch_id": self.branch,
            "lines": [{"sku_id": sku, "qty": qty} for sku, qty in lines.items()],
            **extra,
        }
        return _ok(_post(self.world, token or self.owner, "/orders", body), 201)

    def step(self, order: dict[str, Any], *steps: str, token: str | None = None) -> dict[str, Any]:
        for step in steps:
            order = _ok(
                _post(
                    self.world, token or self.owner, f"/orders/{order['id']}/{step}", version=order["version"]
                )
            )
        return order

    def pending(self, lines: dict[str, int], token: str | None = None) -> dict[str, Any]:
        return self.step(self.order(lines, token), "submit", token=token)

    def balance(self, sku: str, branch: str | None = None) -> dict[str, Any]:
        items = _ok(self.world.client.get(f"/api/v1/shop/stock?sku_id={sku}", headers=_bearer(self.owner)))[
            "items"
        ]
        return next(i for i in items if i["branch_id"] == (branch or self.branch))

    def get(self, order_id: str, token: str | None = None) -> dict[str, Any]:
        return _ok(
            self.world.client.get(f"/api/v1/shop/orders/{order_id}", headers=_bearer(token or self.owner))
        )

    def ledger(self, sku: str) -> list[dict[str, Any]]:
        return list(
            _ok(
                self.world.client.get(f"/api/v1/shop/stock/history?sku_id={sku}", headers=_bearer(self.owner))
            )["items"]
        )


def _admin_sql(world: World, query: str, *args: Any) -> list[asyncpg.Record]:
    """Superuser — RLS'siz (tekshiruv va "vaqtni surish" uchun)."""
    return _sql(world.urls.admin, query, *args)


# ------------------------------------------------------------------ ombor: kirim, qoldiq, daftar


def test_receipt_updates_balance_and_ledger(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    body = {
        "branch_id": shop.branch,
        "note": "1-partiya",
        "lines": [{"sku_id": sku, "qty": 2}, {"sku_id": sku, "qty": 3}],
    }
    headers = _hdr(shop.owner)
    first = world.client.post("/api/v1/shop/stock/receipts", json=body, headers=headers)
    receipt = _ok(first, 201)
    assert first.headers["Location"] == f"/api/v1/shop/stock/receipts/{receipt['id']}"
    assert [(line["qty"], line["on_hand_after"]) for line in receipt["lines"]] == [
        (5, 5)
    ]  # takrori qo'shildi
    replay = _ok(world.client.post("/api/v1/shop/stock/receipts", json=body, headers=headers), 201)
    assert replay["id"] == receipt["id"]  # ikki marta bosish — bitta kirim
    balance = shop.balance(sku)
    assert (balance["on_hand"], balance["available"], balance["stock_status"]) == (5, 5, "IN_STOCK")
    assert [(e["reason"], e["delta_on_hand"], e["on_hand_after"]) for e in shop.ledger(sku)] == [
        ("RECEIPT", 5, 5)
    ]
    listed = _ok(world.client.get("/api/v1/shop/stock/receipts", headers=_bearer(shop.owner)))["items"]
    assert listed[0]["units"] == 5 and listed[0]["line_count"] == 1
    code = balance["sku_code"]
    found = _ok(world.client.get("/api/v1/shop/stock", params={"q": code[2:]}, headers=_bearer(shop.owner)))
    assert [i["sku_id"] for i in found["items"]] == [sku] and found["items"][0]["title"].endswith(code)
    none = _ok(
        world.client.get("/api/v1/shop/stock", params={"q": "yo'q-mahsulot"}, headers=_bearer(shop.owner))
    )
    assert none["items"] == []
    low = _ok(
        world.client.get("/api/v1/shop/stock", params={"low_only": "true"}, headers=_bearer(shop.owner))
    )
    assert low["items"] == [] and low["low_stock_threshold"] == 2  # 5 ta — "kam qoldi" emas


def test_receipt_rejects_foreign_or_archived_sku_and_closed_branch(world: World) -> None:
    shop, other = Shop(world), Shop(world)
    foreign = other.sku()
    response = _post(
        world,
        shop.owner,
        "/stock/receipts",
        {"branch_id": shop.branch, "lines": [{"sku_id": foreign, "qty": 1}]},
    )
    assert response.status_code == 422 and _fields(response) == {"lines[0].sku_id": "invalid"}
    response = _post(
        world,
        shop.owner,
        "/stock/receipts",
        {"branch_id": other.branch, "lines": [{"sku_id": shop.sku(), "qty": 1}]},
    )
    assert _fields(response) == {"branch_id": "invalid"}  # boshqa shop filiali — xuddi yo'qdek
    branches = world.client.get("/api/v1/shop/branches", headers=_bearer(shop.owner)).json()["items"]
    target = next(b for b in branches if b["id"] == shop.branch2)
    closed = world.client.post(
        f"/api/v1/shop/branches/{shop.branch2}/close", headers=_hdr(shop.owner, target["version"])
    )
    assert closed.status_code == 200, closed.text
    response = _post(
        world,
        shop.owner,
        "/stock/receipts",
        {"branch_id": shop.branch2, "lines": [{"sku_id": shop.sku(), "qty": 1}]},
    )
    assert _code(response) == "BRANCH_CLOSED"


# ------------------------------------------------------------------ tez sotuv (DEC-123, TC-027)


def test_quick_sale_reduces_stock_and_cannot_sell_reserved(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku(amount=39_000_000)
    shop.receive(sku, 2)
    sale = _ok(
        _post(
            world,
            shop.owner,
            "/quick-sales",
            {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]},
        ),
        201,
    )
    assert sale["total_minor"] == 39_000_000 and sale["lines"][0]["warranty_months"] == 24
    assert shop.balance(sku)["on_hand"] == 1
    shop.step(shop.pending({sku: 1}), "confirm")  # oxirgi dona online buyurtmaga band
    blocked = _post(
        world, shop.owner, "/quick-sales", {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
    )
    assert _code(blocked) == "INSUFFICIENT_AVAILABLE_STOCK"
    line = blocked.json()["error"]["details"]["lines"][0]
    assert (line["available"], line["reserved"]) == (
        0,
        1,
    )  # UI: "online buyurtma uchun band qilingan" (BL-109)
    assert [e["reason"] for e in shop.ledger(sku)] == ["RESERVE", "OFFLINE_SALE", "RECEIPT"]


def test_quick_sale_needs_price_and_usd_rate(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()  # so'mda chiqarilgan, keyin narx dollarga o'tadi — shop kursi hali yo'q
    price = world.client.put(
        f"/api/v1/shop/skus/{sku}/price",
        json={"amount_minor": 20_000, "currency": "USD"},
        headers=_hdr(shop.owner, 1),
    )
    assert price.status_code == 200, price.text
    shop.receive(sku, 1)
    response = _post(
        world, shop.owner, "/quick-sales", {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
    )
    assert _code(response) == "PRODUCT_NOT_AVAILABLE"
    assert response.json()["error"]["details"]["lines"][0]["reason"] == "NO_RATE"
    shop.rate("12850")
    sale = _ok(
        _post(
            world,
            shop.owner,
            "/quick-sales",
            {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]},
        ),
        201,
    )
    assert sale["lines"][0]["unit_price_uzs_minor"] == 257_000_000 and sale["lines"][0]["currency"] == "USD"


# ------------------------------------------------------------------ buyurtma: to'liq yo'l va bir martalik


def test_order_lifecycle_moves_stock_exactly_once(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 3)
    order = shop.order({sku: 2})
    assert (order["status"], order["number"], order["total_minor"]) == ("DRAFT", 1, 960_000_000)
    assert order["lines"][0]["reservation"] is None  # qoralama band qilmaydi (DEC-100b)
    assert shop.balance(sku)["reserved"] == 0
    order = shop.step(order, "submit", "confirm")
    assert order["status"] == "CONFIRMED" and order["lines"][0]["reservation"]["status"] == "ACTIVE"
    assert (shop.balance(sku)["reserved"], shop.balance(sku)["available"]) == (2, 1)
    order = shop.step(order, "start-processing")
    assert order["lines"][0]["reservation"]["status"] == "ALLOCATED"
    assert (shop.balance(sku)["reserved"], shop.balance(sku)["allocated"]) == (0, 2)
    ready = shop.step(order, "mark-ready")
    assert ready["status"] == "PROCESSING" and ready["ready_at"] is not None
    done = shop.step(ready, "complete")
    assert done["status"] == "COMPLETED" and done["lines"][0]["reservation"]["status"] == "CONSUMED"
    again = _post(world, shop.owner, f"/orders/{done['id']}/complete", version=done["version"])
    assert _code(again) == "INVALID_STATE_TRANSITION"  # TC-030: ikkinchi "Topshirildi"
    balance = shop.balance(sku)
    assert (balance["on_hand"], balance["allocated"], balance["available"]) == (1, 0, 1)
    assert [e["reason"] for e in shop.ledger(sku)].count("SALE") == 1
    history = _admin_sql(
        world,
        "SELECT command FROM platform.transition_log WHERE entity_id = $1 ORDER BY occurred_at",
        UUID(done["id"]),
    )
    assert [r["command"] for r in history] == [
        "SUBMIT",
        "CONFIRM",
        "START_PROCESSING",
        "MARK_READY",  # holat o'zgarmaydi, lekin kim bosgani tarixda (QA U3)
        "COMPLETE",
    ]


def test_reconciliation_matches_after_mixed_operations(world: World) -> None:
    shop = Shop(world)
    a, b = shop.sku(), shop.sku()
    shop.receive(a, 5)
    shop.receive(b, 2, branch=shop.branch2)
    shop.step(shop.pending({a: 2}), "confirm", "start-processing", "complete")
    cancelled = shop.step(shop.pending({a: 1}), "confirm")
    _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{cancelled['id']}/cancel",
            {"reason": "xaridor fikridan qaytdi"},
            cancelled["version"],
        )
    )
    _ok(
        _post(
            world, shop.owner, "/quick-sales", {"branch_id": shop.branch2, "lines": [{"sku_id": b, "qty": 1}]}
        ),
        201,
    )

    async def reconcile() -> list[Any]:
        from app.shared.db.session import Database

        commerce = world.client.app.state.commerce  # type: ignore[attr-defined]
        database = Database(world.settings.database_config())
        try:
            async with database.transaction(shop.id) as db:
                return list(await commerce.stock.reconcile(db, shop.id))
        finally:
            await database.dispose()

    assert asyncio.run(reconcile()) == []


# ------------------------------------------------------------ poyga: oxirgi dona (TC-002, TC-003, TC-027)


def test_last_unit_race_between_two_confirms_and_quick_sale(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1)
    first, second = shop.pending({sku: 1}), shop.pending({sku: 1})

    def run(task: tuple[str, dict[str, Any] | None]) -> int:
        kind, order = task
        if kind == "sale":
            return int(
                _post(
                    world,
                    shop.owner,
                    "/quick-sales",
                    {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]},
                ).status_code
            )
        assert order is not None
        return int(
            _post(world, shop.owner, f"/orders/{order['id']}/confirm", version=order["version"]).status_code
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        statuses = list(pool.map(run, [("confirm", first), ("confirm", second), ("sale", None)]))
    assert sorted(statuses) in ([200, 409, 409], [201, 409, 409]), statuses  # faqat bittasi o'tadi
    balance = shop.balance(sku)
    assert balance["available"] == 0 and balance["available"] >= 0


def test_same_idempotency_key_confirms_once(world: World) -> None:  # TC-CON-03
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 3)
    order = shop.pending({sku: 1})
    headers = _bearer(shop.owner, **_idem(), **{"If-Match": f'"v{order["version"]}"'})

    def confirm(_: int) -> Any:
        return world.client.post(f"/api/v1/shop/orders/{order['id']}/confirm", headers=headers)

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(confirm, range(5)))
    codes = {r.status_code for r in responses}
    assert 200 in codes and codes <= {200, 409}
    assert all(_code(r) == "REQUEST_IN_PROGRESS" for r in responses if r.status_code == 409)
    replay = world.client.post(f"/api/v1/shop/orders/{order['id']}/confirm", headers=headers)
    assert replay.status_code == 200 and replay.json()["status"] == "CONFIRMED"
    assert shop.balance(sku)["reserved"] == 1
    rows = _admin_sql(
        world, "SELECT count(*) AS n FROM commerce.reservations WHERE order_id = $1", UUID(order["id"])
    )
    assert rows[0]["n"] == 1


def test_multi_sku_orders_in_reverse_order_do_not_deadlock(world: World) -> None:  # TC-CON-10
    shop = Shop(world)
    a, b = shop.sku(), shop.sku()
    shop.receive(a, 10)
    shop.receive(b, 10)
    for _ in range(3):
        first = shop.pending({a: 1, b: 1})
        second = shop.order({b: 1})
        second = _ok(
            _post(
                world, shop.owner, f"/orders/{second['id']}/lines", {"sku_id": a, "qty": 1}, second["version"]
            ),
            201,
        )
        second = shop.step(second, "submit")

        def confirm(order: dict[str, Any]) -> int:
            return int(
                _post(
                    world, shop.owner, f"/orders/{order['id']}/confirm", version=order["version"]
                ).status_code
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(confirm, [first, second])) == [200, 200]
    assert shop.balance(a)["reserved"] == shop.balance(b)["reserved"] == 6


# ------------------------------------------------------------------ narx (TC-031, DEC-134, BL-018)


def test_rate_change_gives_price_changed_and_refresh_fixes_it(world: World) -> None:
    shop = Shop(world)
    shop.rate("12800")
    sku = shop.sku(amount=20_000, currency="USD")
    shop.receive(sku, 2)
    order = shop.pending({sku: 1})
    assert order["lines"][0]["unit_price_uzs_minor"] == 256_000_000  # 200 $ × 12 800
    shop.rate("12900")
    response = _post(world, shop.owner, f"/orders/{order['id']}/confirm", version=order["version"])
    assert _code(response) == "PRICE_CHANGED"
    [line] = response.json()["error"]["details"]["lines"]
    assert (line["old"]["amount_minor"], line["new"]["amount_minor"]) == (256_000_000, 258_000_000)
    assert shop.balance(sku)["reserved"] == 0  # hech narsa band qilinmadi
    refreshed = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/refresh-prices",
            {"note": "Xaridor yangi narxga rozi"},
            order["version"],
        )
    )
    assert (
        refreshed["lines"][0]["unit_price_uzs_minor"] == 258_000_000
        and refreshed["total_minor"] == 258_000_000
    )
    assert refreshed["notes"][-1]["kind"] == "CALL_RESULT"
    assert shop.step(refreshed, "confirm")["status"] == "CONFIRMED"


def test_catalog_price_change_is_detected_at_confirm(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku(amount=480_000_000)
    shop.receive(sku, 1)
    order = shop.pending({sku: 1})
    price = world.client.put(
        f"/api/v1/shop/skus/{sku}/price",
        json={"amount_minor": 470_000_000, "currency": "UZS"},
        headers=_hdr(shop.owner, 1),
    )
    assert price.status_code == 200, price.text
    assert (
        _code(_post(world, shop.owner, f"/orders/{order['id']}/confirm", version=order["version"]))
        == "PRICE_CHANGED"
    )


def test_stale_rate_blocks_confirm_of_usd_order(world: World) -> None:
    shop = Shop(world)
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    shop.rate("12800", effective_at=old)
    sku = shop.sku(amount=20_000, currency="USD")
    shop.receive(sku, 1)
    order = shop.pending({sku: 1})
    response = _post(world, shop.owner, f"/orders/{order['id']}/confirm", version=order["version"])
    assert _code(response) == "EXCHANGE_RATE_STALE"
    assert response.json()["error"]["details"]["max_age_hours"] == 72


# ------------------------------------------------------------------ tuzatish (DEC-134, TC-CON-12)


def test_adjustment_request_approval_rechecks_stock(world: World) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 3)
    request = _ok(
        _post(
            world,
            warehouse,
            "/stock/adjustments",
            {"branch_id": shop.branch, "sku_id": sku, "delta": -2, "reason": "sanoqda kam"},
        ),
        201,
    )
    assert request["status"] == "PENDING" and shop.balance(sku)["on_hand"] == 3  # qoldiq hali o'zgarmagan
    assert (
        _post(
            world, warehouse, f"/stock/adjustments/{request['id']}/approve", version=request["version"]
        ).status_code
        == 403
    )
    shop.step(shop.pending({sku: 2}), "confirm")  # so'rovdan keyin 2 tasi band bo'ldi
    blocked = _post(
        world, shop.owner, f"/stock/adjustments/{request['id']}/approve", version=request["version"]
    )
    assert _code(blocked) == "INSUFFICIENT_AVAILABLE_STOCK"
    no_note = _post(
        world, shop.owner, f"/stock/adjustments/{request['id']}/reject", {"note": "  "}, request["version"]
    )
    assert _fields(no_note) == {"note": "min_length"}
    rejected = _ok(
        _post(
            world,
            shop.owner,
            f"/stock/adjustments/{request['id']}/reject",
            {"note": "qayta sanang"},
            request["version"],
        )
    )
    assert rejected["status"] == "REJECTED" and rejected["decided_by"] is not None
    again = _post(
        world, shop.owner, f"/stock/adjustments/{request['id']}/approve", version=rejected["version"]
    )
    assert _code(again) == "INVALID_STATE_TRANSITION"


def test_owner_adjusts_directly_and_quarantine_flow(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 4)

    def adjust(kind: str, delta: int) -> Any:
        body = {
            "branch_id": shop.branch,
            "sku_id": sku,
            "kind": kind,
            "delta": delta,
            "reason": "qutisi ezilgan",
        }
        return _post(world, shop.owner, "/stock/adjustments", body)

    direct = _ok(adjust("ADJUSTMENT", -1), 201)
    assert (direct["status"], direct["on_hand_before"], direct["on_hand_after"]) == ("APPROVED", 4, 3)
    _ok(adjust("QUARANTINE_IN", 2), 201)
    balance = shop.balance(sku)
    assert (balance["on_hand"], balance["quarantine_qty"], balance["available"]) == (
        1,
        2,
        1,
    )  # sotilmaydi (BR-X11)
    _ok(adjust("RESTOCK", 1), 201)
    assert _code(adjust("WRITE_OFF", 2)) == "INSUFFICIENT_AVAILABLE_STOCK"  # tekshiruvda faqat 1 ta
    _ok(adjust("WRITE_OFF", 1), 201)
    balance = shop.balance(sku)
    assert (balance["on_hand"], balance["quarantine_qty"]) == (2, 0)
    assert _fields(adjust("RESTOCK", -1)) == {"delta": "min_value"}
    assert [e["reason"] for e in shop.ledger(sku)][:4] == [
        "WRITE_OFF",
        "RESTOCK",
        "QUARANTINE_IN",
        "ADJUSTMENT",
    ]


def test_adjustment_evidence_is_private(world: World) -> None:
    from tests import images

    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 1)
    upload = world.client.post(
        "/api/v1/shop/files?purpose=STOCK_EVIDENCE&filename=dalil.png",
        content=images.png(),
        headers=_bearer(warehouse, **_idem(), **{"Content-Type": "image/png"}),
    )
    file = _ok(upload, 201)
    assert file["is_public"] is False and "sig=" in file["url"]
    body = {
        "branch_id": shop.branch,
        "sku_id": sku,
        "delta": -1,
        "reason": "singan",
        "evidence_file_id": file["id"],
    }
    adjustment = _ok(_post(world, warehouse, "/stock/adjustments", body), 201)
    assert adjustment["evidence"]["file_id"] == file["id"] and adjustment["evidence"]["url_expires_at"]


# ------------------------------------------------------------------ DB invariantlari va o'zgarmaslik


def test_ledger_is_append_only_and_balance_check_holds(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1)
    runtime = world.urls.runtime.replace("postgresql+asyncpg://", "postgresql://")

    async def attempt(sql: str) -> None:
        conn = await asyncpg.connect(runtime)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", str(shop.id))
                await conn.execute(sql)
        finally:
            await conn.close()

    for sql in (
        "UPDATE commerce.stock_ledger SET delta_on_hand = 99",
        "DELETE FROM commerce.stock_ledger",
        "DELETE FROM commerce.stock_receipts",
        "DELETE FROM commerce.orders",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            asyncio.run(attempt(sql))
    with pytest.raises(asyncpg.CheckViolationError):  # sotuvga mavjud hech qachon manfiy emas (BL-019)
        asyncio.run(attempt("UPDATE commerce.stock_balances SET reserved = on_hand + 1"))


# ------------------------------------------------------------------ RLS va boshqa shop (TC-001, 10 §4)


def test_shops_cannot_see_each_others_commerce_data(world: World) -> None:
    a, b = Shop(world), Shop(world)
    sku = a.sku()
    a.receive(sku, 2)
    order = a.step(a.pending({sku: 1}), "confirm")
    sale = _ok(
        _post(world, a.owner, "/quick-sales", {"branch_id": a.branch, "lines": [{"sku_id": sku, "qty": 1}]}),
        201,
    )
    receipt_id = _ok(world.client.get("/api/v1/shop/stock/receipts", headers=_bearer(a.owner)))["items"][0][
        "id"
    ]
    adjustment = _ok(
        _post(
            world,
            a.owner,
            "/stock/adjustments",
            {"branch_id": a.branch, "sku_id": sku, "delta": 1, "reason": "topildi"},
        ),
        201,
    )
    for path in (
        f"/orders/{order['id']}",
        f"/quick-sales/{sale['id']}",
        f"/stock/receipts/{receipt_id}",
        f"/stock/adjustments/{adjustment['id']}",
    ):
        assert world.client.get(f"/api/v1/shop{path}", headers=_bearer(b.owner)).status_code == 404, path
    assert (
        _code(_post(world, b.owner, f"/orders/{order['id']}/cancel", {"reason": "begona"}, order["version"]))
        == "NOT_FOUND"
    )
    assert _ok(world.client.get("/api/v1/shop/stock", headers=_bearer(b.owner)))["items"] == []
    assert _ok(world.client.get("/api/v1/shop/orders", headers=_bearer(b.owner)))["items"] == []
    foreign_line = _post(world, b.owner, "/orders", {"lines": [{"sku_id": sku, "qty": 1}]})
    assert _fields(foreign_line) == {"lines[0].sku_id": "invalid"}

    runtime = world.urls.runtime.replace("postgresql+asyncpg://", "postgresql://")
    tables = (
        "stock_balances",
        "stock_ledger",
        "stock_receipts",
        "stock_adjustments",
        "quick_sales",
        "quick_sale_lines",
        "orders",
        "order_lines",
        "order_notes",
        "reservations",
    )

    async def counts(shop_id: UUID) -> dict[str, int]:
        conn = await asyncpg.connect(runtime)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", str(shop_id))
                return {t: await conn.fetchval(f"SELECT count(*) FROM commerce.{t}") for t in tables}
        finally:
            await conn.close()

    assert all(n > 0 for t, n in asyncio.run(counts(a.id)).items() if t != "order_notes")
    assert set(asyncio.run(counts(b.id)).values()) == {0}  # FORCE RLS: boshqa shop qatorlari ko'rinmaydi


# ------------------------------------------------------------------ rollar va "own" (10 §6.3, DEC-108)


def test_permission_matrix_and_ownership(world: World) -> None:
    shop = Shop(world)
    sales, sales_id = shop.staff("SALES")
    sales2, sales2_id = shop.staff("SALES")
    warehouse, _ = shop.staff("WAREHOUSE")
    manager, _ = shop.staff("MANAGER")
    sku = shop.sku()
    shop.receive(sku, 5)

    assert (
        _post(
            world, sales, "/stock/receipts", {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
        ).status_code
        == 403
    )
    assert _post(world, warehouse, "/orders", {"lines": []}).status_code == 403
    assert world.client.get("/api/v1/shop/stock/adjustments", headers=_bearer(sales)).status_code == 403

    mine = shop.pending({sku: 1}, token=sales)
    assert mine["assigned"]["membership_id"] == sales_id
    assert world.client.get(f"/api/v1/shop/orders/{mine['id']}", headers=_bearer(sales2)).status_code == 403
    assert _post(world, sales2, f"/orders/{mine['id']}/confirm", version=mine["version"]).status_code == 403
    assert (
        _post(
            world, sales, f"/orders/{mine['id']}/cancel", {"reason": "kerak emas"}, mine["version"]
        ).status_code
        == 403
    )
    assert (
        world.client.get(f"/api/v1/shop/orders/{mine['id']}", headers=_bearer(warehouse)).status_code == 403
    )  # hali tasdiqlanmagan

    unassigned = shop.pending({sku: 1})
    unassigned = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{unassigned['id']}/assign",
            {"membership_id": None},
            unassigned["version"],
        )
    )
    assert unassigned["assigned"] is None
    queue = _ok(world.client.get("/api/v1/shop/orders?assigned=unassigned", headers=_bearer(sales2)))["items"]
    assert [o["id"] for o in queue] == [unassigned["id"]]
    assert (
        _post(world, sales2, f"/orders/{unassigned['id']}/confirm", version=unassigned["version"]).status_code
        == 403
    )
    taken = _ok(_post(world, sales2, f"/orders/{unassigned['id']}/take", version=unassigned["version"]))
    assert taken["assigned"]["membership_id"] == sales2_id
    assert _code(_post(world, sales, f"/orders/{taken['id']}/take", version=taken["version"])) in (
        "FORBIDDEN",
        "INVALID_STATE_TRANSITION",
    )
    confirmed = shop.step(taken, "confirm", token=sales2)
    processing = shop.step(confirmed, "start-processing", token=warehouse)  # omborchi tayyorlaydi
    assert (
        _post(
            world, warehouse, f"/orders/{processing['id']}/complete", version=processing["version"]
        ).status_code
        == 403
    )
    assert shop.step(processing, "complete", token=sales2)["status"] == "COMPLETED"

    reassigned = _ok(
        _post(world, manager, f"/orders/{mine['id']}/assign", {"membership_id": sales2_id}, mine["version"])
    )
    assert reassigned["assigned"]["membership_id"] == sales2_id
    bad = _post(
        world, manager, f"/orders/{mine['id']}/assign", {"membership_id": str(uuid4())}, reassigned["version"]
    )
    assert _fields(bad) == {"membership_id": "invalid_choice"}
    assert (
        _post(
            world, sales, f"/orders/{mine['id']}/assign", {"membership_id": sales_id}, reassigned["version"]
        ).status_code
        == 403
    )
    cancelled = _ok(
        _post(
            world,
            manager,
            f"/orders/{mine['id']}/cancel",
            {"reason": "xaridor rad etdi"},
            reassigned["version"],
        )
    )
    assert cancelled["status"] == "CANCELLED" and cancelled["cancel_reason"] == "xaridor rad etdi"


def test_sales_can_cancel_own_draft_but_reason_needed_after_submit(world: World) -> None:
    shop = Shop(world)
    sales, _ = shop.staff("SALES")
    sku = shop.sku()
    draft = shop.order({sku: 1}, token=sales)
    assert (
        _ok(_post(world, sales, f"/orders/{draft['id']}/cancel", None, draft["version"]))["status"]
        == "CANCELLED"
    )
    pending = shop.pending({sku: 1})
    no_reason = _post(world, shop.owner, f"/orders/{pending['id']}/cancel", None, pending["version"])
    assert _fields(no_reason) == {"reason": "required"}  # BL-049


# ------------------------------------------------------------------ tahrir, validatsiya, If-Match


def test_confirmed_order_is_not_editable_and_if_match_is_checked(world: World) -> None:
    shop = Shop(world)
    sku, other = shop.sku(), shop.sku()
    shop.receive(sku, 2)
    order = shop.pending({sku: 1})
    stale = _post(world, shop.owner, f"/orders/{order['id']}/confirm", version=order["version"] - 1)
    assert _code(stale) == "VERSION_CONFLICT"
    confirmed = shop.step(order, "confirm")
    for response in (
        world.client.patch(
            f"/api/v1/shop/orders/{order['id']}",
            json={"customer_name": "X"},
            headers=_hdr(shop.owner, confirmed["version"]),
        ),
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/lines",
            {"sku_id": other, "qty": 1},
            confirmed["version"],
        ),
    ):
        assert _code(response) == "INVALID_STATE_TRANSITION"  # DEC-134: bekor qilib yangisi


def test_order_validation_rules(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    hidden = shop.sku(publish=False)
    order = _ok(_post(world, shop.owner, "/orders", {"lines": [{"sku_id": sku, "qty": 1}]}), 201)
    incomplete = _post(world, shop.owner, f"/orders/{order['id']}/submit", version=order["version"])
    assert _fields(incomplete) == {"customer_name": "required", "customer_phone": "required"}
    delivery = shop.order({sku: 1}, fulfillment_method="DELIVERY")
    assert _fields(
        _post(world, shop.owner, f"/orders/{delivery['id']}/submit", version=delivery["version"])
    ) == {"delivery_address": "required"}
    unpublished = _post(world, shop.owner, "/orders", {"lines": [{"sku_id": hidden, "qty": 1}]})
    assert _code(unpublished) == "PRODUCT_NOT_AVAILABLE"
    duplicate = _post(
        world, shop.owner, "/orders", {"lines": [{"sku_id": sku, "qty": 1}, {"sku_id": sku, "qty": 2}]}
    )
    assert _fields(duplicate) == {"lines[1].sku_id": "not_unique"}
    bad_phone = _post(world, shop.owner, "/orders", {"customer_phone": "12345", "lines": []})
    assert _fields(bad_phone) == {"customer_phone": "invalid_format"}
    no_branch = _ok(
        _post(
            world,
            shop.owner,
            "/orders",
            {"customer_name": "A", "customer_phone": PHONE, "lines": [{"sku_id": sku, "qty": 1}]},
        ),
        201,
    )
    no_branch = shop.step(no_branch, "submit")
    assert _fields(
        _post(world, shop.owner, f"/orders/{no_branch['id']}/confirm", version=no_branch["version"])
    ) == {"branch_id": "required"}
    shop.receive(sku, 1)
    short = shop.pending({sku: 2})
    insufficient = _post(world, shop.owner, f"/orders/{short['id']}/confirm", version=short["version"])
    assert _code(insufficient) == "INSUFFICIENT_AVAILABLE_STOCK"
    assert insufficient.json()["error"]["details"]["lines"][0]["requested"] == 2


def test_lines_edit_recomputes_total_and_bumps_version(world: World) -> None:
    shop = Shop(world)
    a, b = shop.sku(amount=100_000_000), shop.sku(amount=50_000_000)
    order = shop.order({a: 1})
    added = _ok(
        _post(world, shop.owner, f"/orders/{order['id']}/lines", {"sku_id": b, "qty": 2}, order["version"]),
        201,
    )
    assert added["total_minor"] == 200_000_000 and added["version"] > order["version"]
    line_b = next(line for line in added["lines"] if line["sku_id"] == b)
    patched = world.client.patch(
        f"/api/v1/shop/orders/{order['id']}/lines/{line_b['id']}",
        json={"qty": 1},
        headers=_hdr(shop.owner, added["version"]),
    )
    assert (
        _ok(patched)["total_minor"] == 150_000_000
        and patched.headers["ETag"] == f'"v{patched.json()["version"]}"'
    )
    removed = world.client.delete(
        f"/api/v1/shop/orders/{order['id']}/lines/{line_b['id']}",
        headers=_hdr(shop.owner, patched.json()["version"]),
    )
    assert _ok(removed)["total_minor"] == 100_000_000 and len(removed.json()["lines"]) == 1


def test_create_order_is_idempotent_and_numbers_are_sequential(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    body = {"customer_name": "Jasur", "customer_phone": PHONE, "lines": [{"sku_id": sku, "qty": 1}]}
    headers = _hdr(shop.owner)
    first = world.client.post("/api/v1/shop/orders", json=body, headers=headers)
    replay = world.client.post("/api/v1/shop/orders", json=body, headers=headers)
    assert first.status_code == 201 and replay.json()["id"] == first.json()["id"]
    assert first.headers["Location"] == f"/api/v1/shop/orders/{first.json()['id']}"
    assert shop.order({sku: 1})["number"] == 2  # takror raqam yemadi
    other = Shop(world)
    assert other.order({other.sku(): 1})["number"] == 1  # har shopning raqamlari alohida


# ------------------------------------------------------------------ chegirma (DEC-110)


def test_discount_request_and_approval_limits(world: World) -> None:
    shop = Shop(world)
    sales, _ = shop.staff("SALES")
    manager, _ = shop.staff("MANAGER")
    sku = shop.sku(amount=100_000_000)
    shop.receive(sku, 1)
    order = shop.order({sku: 2}, token=sales)
    line = order["lines"][0]
    requested = _ok(
        world.client.put(
            f"/api/v1/shop/orders/{order['id']}/lines/{line['id']}/discount",
            json={"discount_pct": "8"},
            headers=_hdr(sales, order["version"]),
        )
    )
    assert requested["lines"][0]["discount_status"] == "PENDING" and requested["total_minor"] == 200_000_000
    requested = shop.step(requested, "submit", token=sales)
    blocked = _post(world, sales, f"/orders/{order['id']}/confirm", version=requested["version"])
    assert (
        _code(blocked) == "APPROVAL_REQUIRED" and blocked.json()["error"]["details"]["reason"] == "DISCOUNT"
    )
    over = _post(
        world,
        manager,
        f"/orders/{order['id']}/lines/{line['id']}/discount/approve",
        version=requested["version"],
    )
    assert (
        _code(over) == "DISCOUNT_LIMIT_EXCEEDED"
        and over.json()["error"]["details"]["approver_role"] == "OWNER"
    )
    approved = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/lines/{line['id']}/discount/approve",
            version=requested["version"],
        )
    )
    assert approved["lines"][0]["discount_status"] == "APPROVED" and approved["total_minor"] == 184_000_000
    direct = _ok(
        world.client.put(
            f"/api/v1/shop/orders/{order['id']}/lines/{line['id']}/discount",
            json={"discount_pct": "5"},
            headers=_hdr(manager, approved["version"]),
        )
    )
    assert direct["lines"][0]["discount_status"] == "APPROVED" and direct["total_minor"] == 190_000_000


# ------------------------------------------------------------------ PII (26 §4) va qidiruv


def test_customer_pii_is_encrypted_and_kept_out_of_audit_and_idempotency(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    order = shop.order(
        {sku: 1}, fulfillment_method="DELIVERY", delivery_address="Toshkent, Chilonzor 9-kvartal, 12"
    )
    assert order["customer_phone"] == PHONE and order["delivery_address"].startswith("Toshkent")
    [row] = _admin_sql(
        world,
        "SELECT customer_phone_enc, customer_phone_hmac, delivery_address_enc "
        "FROM commerce.orders WHERE id = $1",
        UUID(order["id"]),
    )
    assert row["customer_phone_enc"].startswith("v1.") and "901234567" not in row["customer_phone_enc"]
    assert "Chilonzor" not in row["delivery_address_enc"] and "901234567" not in row["customer_phone_hmac"]
    patched = world.client.patch(
        f"/api/v1/shop/orders/{order['id']}",
        json={"customer_phone": "+998 93 555 77 88"},
        headers=_hdr(shop.owner, order["version"]),
    )
    assert _ok(patched)["customer_phone"] == "+998935557788"
    audit = _admin_sql(
        world,
        "SELECT coalesce(diff::text, '') AS d FROM audit.audit_entries WHERE entity_id = $1",
        UUID(order["id"]),
    )
    assert audit and not any("9012" in r["d"] or "5557788" in r["d"] or "Chilonzor" in r["d"] for r in audit)
    assert any("customer_phone" in r["d"] for r in audit)  # faqat maydon nomi
    stored = _admin_sql(
        world,
        "SELECT response_body::text AS b FROM platform.idempotency_keys "
        "WHERE operation = 'commerce.order.create'",
    )
    assert stored and not any("9012" in r["b"] for r in stored)
    for query in ("+998 93 555-77-88", "935557788"):
        found = _ok(
            world.client.get("/api/v1/shop/orders", params={"q": query}, headers=_bearer(shop.owner))
        )["items"]
        assert [o["id"] for o in found] == [order["id"]] and found[0][
            "customer_phone_masked"
        ] == "+998 93 *** ** 88"
    by_number = _ok(
        world.client.get(
            "/api/v1/shop/orders", params={"q": f"#{order['number']}"}, headers=_bearer(shop.owner)
        )
    )
    assert order["id"] in [o["id"] for o in by_number["items"]]


def test_erase_customer_pii(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 2)
    done = shop.step(shop.pending({sku: 1}), "confirm", "start-processing", "complete")
    _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{done['id']}/notes",
            {"kind": "CALL_RESULT", "body": f"{PHONE} ga qo'ng'iroq"},
        ),
        201,
    )
    active = shop.pending({sku: 1})

    async def erase() -> Any:
        from app.shared.db.session import Database
        from app.shared.types.actor import ActorContext

        commerce = world.client.app.state.commerce  # type: ignore[attr-defined]
        actor = ActorContext(actor_type="SYSTEM", actor_id=None, shop_id=shop.id, surface="worker")
        database = Database(world.settings.database_config())
        try:
            async with database.transaction(shop.id) as db:
                return await commerce.privacy.erase_customer(db, actor, "90 123 45 67")
        finally:
            await database.dispose()

    summary = asyncio.run(erase())
    assert (summary.erased, summary.skipped_active) == (1, 1)  # jarayondagi buyurtmaga tegilmaydi
    erased = shop.get(done["id"])
    assert erased["customer_name"] is None and erased["customer_phone"] is None and erased["pii_erased_at"]
    assert erased["notes"][0]["body"] == "[o'chirildi]" and erased["total_minor"] == done["total_minor"]
    assert shop.get(active["id"])["customer_phone"] == PHONE


# ------------------------------------------------ 72 va 24 soatlik "ko'rib chiqish" (DEC-104, DEC-134)


def test_reservation_review_wait_and_cancel(world: World) -> None:
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    sku = shop.sku()
    shop.receive(sku, 1)
    order = shop.step(shop.pending({sku: 1}), "confirm", "start-processing")
    too_early = _post(
        world, manager, f"/orders/{order['id']}/review-decision", {"decision": "WAIT"}, order["version"]
    )
    assert _code(too_early) == "INVALID_STATE_TRANSITION"
    _admin_sql(
        world,
        "UPDATE commerce.reservations SET review_at = now() - interval '1 hour' WHERE order_id = $1",
        UUID(order["id"]),
    )
    queue = _ok(world.client.get("/api/v1/shop/orders/review-queue", headers=_bearer(manager)))
    assert [o["id"] for o in queue["reservations"]] == [order["id"]] and queue[
        "reservation_review_hours"
    ] == 72
    detail = shop.get(order["id"], manager)
    assert (
        detail["review"]["reason"] == "RESERVATION_REVIEW" and "REVIEW_DECISION" in detail["allowed_actions"]
    )
    waited = _ok(
        _post(
            world, manager, f"/orders/{order['id']}/review-decision", {"decision": "WAIT"}, detail["version"]
        )
    )
    assert waited["status"] == "PROCESSING" and waited["review"] is None
    _admin_sql(
        world,
        "UPDATE commerce.reservations SET review_at = now() - interval '1 hour' WHERE order_id = $1",
        UUID(order["id"]),
    )
    no_reason = _post(
        world, manager, f"/orders/{order['id']}/review-decision", {"decision": "CANCEL"}, waited["version"]
    )
    assert _fields(no_reason) == {"reason": "required"}
    cancelled = _ok(
        _post(
            world,
            manager,
            f"/orders/{order['id']}/review-decision",
            {"decision": "CANCEL", "reason": "72 soatda olib ketmadi"},
            waited["version"],
        )
    )
    assert cancelled["status"] == "CANCELLED" and cancelled["lines"][0]["reservation"]["status"] == "EXPIRED"
    balance = shop.balance(sku)
    assert (balance["allocated"], balance["available"]) == (0, 1)  # mahsulot sotuvga qaytdi
    assert [e["reason"] for e in shop.ledger(sku)].count("RELEASE") == 1


def test_unconfirmed_orders_show_in_review_queue(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    order = shop.pending({sku: 1})
    assert (
        _ok(world.client.get("/api/v1/shop/orders/review-queue", headers=_bearer(shop.owner)))["unconfirmed"]
        == []
    )
    _admin_sql(
        world,
        "UPDATE commerce.orders SET submitted_at = now() - interval '25 hours' WHERE id = $1",
        UUID(order["id"]),
    )
    queue = _ok(world.client.get("/api/v1/shop/orders/review-queue", headers=_bearer(shop.owner)))
    assert [o["review_reason"] for o in queue["unconfirmed"]] == ["UNCONFIRMED"]
    counts = _ok(world.client.get("/api/v1/shop/orders/counts", headers=_bearer(shop.owner)))
    assert counts["review_unconfirmed"] == 1 and counts["by_status"]["PENDING_CONFIRMATION"] == 1
    flagged = _ok(world.client.get("/api/v1/shop/orders?needs_review=true", headers=_bearer(shop.owner)))[
        "items"
    ]
    assert [o["id"] for o in flagged] == [order["id"]]


# ------------------------------------------------------------------ muammo, bekor qilish, "to'landi", izoh


def test_exception_resolution_and_single_release(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 2)
    order = shop.step(shop.pending({sku: 1}), "confirm", "start-processing")
    problem = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/exception",
            {"reason": "qutisi ochilgan"},
            order["version"],
        )
    )
    assert problem["status"] == "EXCEPTION" and problem["exception_reason"] == "qutisi ochilgan"
    resumed = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/resolve-exception",
            {"resolution": "PROCESSING"},
            problem["version"],
        )
    )
    assert resumed["status"] == "PROCESSING"
    problem = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/exception",
            {"reason": "xaridor rad etdi"},
            resumed["version"],
        )
    )
    no_reason = _post(
        world,
        shop.owner,
        f"/orders/{order['id']}/resolve-exception",
        {"resolution": "CANCELLED"},
        problem["version"],
    )
    assert _fields(no_reason) == {"reason": "required"}
    cancelled = _ok(
        _post(
            world,
            shop.owner,
            f"/orders/{order['id']}/resolve-exception",
            {"resolution": "CANCELLED", "reason": "rad etdi"},
            problem["version"],
        )
    )
    assert cancelled["status"] == "CANCELLED" and cancelled["lines"][0]["reservation"]["status"] == "RELEASED"
    again = _post(
        world, shop.owner, f"/orders/{order['id']}/cancel", {"reason": "yana"}, cancelled["version"]
    )
    assert _code(again) == "INVALID_STATE_TRANSITION"  # BL-021: ikkinchi marta bo'shatilmaydi
    assert shop.balance(sku)["available"] == 2
    assert [e["reason"] for e in shop.ledger(sku)].count("RELEASE") == 1


def test_paid_mark_and_notes(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 1)
    draft = shop.order({sku: 1})
    assert (
        _code(_post(world, shop.owner, f"/orders/{draft['id']}/paid-mark", {"method": "CASH"}))
        == "INVALID_STATE_TRANSITION"
    )
    order = shop.step(draft, "submit", "confirm")
    paid = _ok(_post(world, shop.owner, f"/orders/{order['id']}/paid-mark", {"method": "TRANSFER"}))
    assert paid["paid_mark"]["method"] == "TRANSFER" and "PAID_MARK" not in paid["allowed_actions"]
    assert (
        _code(_post(world, shop.owner, f"/orders/{order['id']}/paid-mark", {"method": "CASH"}))
        == "INVALID_STATE_TRANSITION"
    )
    headers = _hdr(shop.owner)
    body = {"kind": "CALL_RESULT", "body": "Ertaga 18:00 da Chilonzordan oladi"}
    note = _ok(world.client.post(f"/api/v1/shop/orders/{order['id']}/notes", json=body, headers=headers), 201)
    replay = _ok(
        world.client.post(f"/api/v1/shop/orders/{order['id']}/notes", json=body, headers=headers), 201
    )
    assert replay["id"] == note["id"] and note["author"]["full_name"]
    assert [n["kind"] for n in shop.get(order["id"])["notes"]] == ["CALL_RESULT"]


# ------------------------------------------------------------------ StockQueryPort (4-modul uchun)


def test_stock_query_port_reports_published_skus_only(world: World) -> None:
    from app.dependencies import get_stock_query
    from app.shared.db.session import Database

    shop = Shop(world)
    sku, hidden = shop.sku(), shop.sku(publish=False)
    shop.receive(sku, 1)
    shop.receive(sku, 5, branch=shop.branch2)
    shop.receive(hidden, 3)
    shop.step(shop.pending({sku: 1}), "confirm")  # Chilonzordagi 1 ta band

    async def read() -> Any:
        database = Database(world.settings.database_config())
        try:
            async with database.transaction(shop.id, read_only=True) as db:
                port = get_stock_query()
                return await port.availability(db, shop.id, [sku, hidden]), await port.display_policy(
                    db, shop.id
                )
        finally:
            await database.dispose()

    availability, policy = asyncio.run(read())
    assert set(availability) == {UUID(sku)}  # chiqarilmagan mahsulot haqida "bor" deyilmaydi
    info = availability[UUID(sku)]
    assert (info.available, info.status) == (5, "IN_STOCK")
    assert {(str(b.branch_id), b.available, b.status) for b in info.pickup_branches} == {
        (shop.branch, 0, "OUT_OF_STOCK"),
        (shop.branch2, 5, "IN_STOCK"),
    }
    assert policy.stock_display == "STATUS_ONLY" and policy.low_stock_threshold == 2
