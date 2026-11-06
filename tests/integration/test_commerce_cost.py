"""7a-modul: tannarx (DEC-146) — o'rtacha tortilgan narx, dollar o'girish, sotuvdagi nusxa, ruxsatlar, RLS."""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import pytest

from app.domains.commerce.inventory.services.cost_service import weighted_average
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _ok, _post

pytestmark = pytest.mark.integration


def _receive_cost(
    shop: Shop, sku: str, qty: int, cost: int | None, *, currency: str = "UZS", token: str | None = None
) -> Any:
    line: dict[str, Any] = {"sku_id": sku, "qty": qty}
    if cost is not None:
        line.update(unit_cost_minor=cost, cost_currency=currency)
    return _post(
        shop.world, token or shop.owner, "/stock/receipts", {"branch_id": shop.branch, "lines": [line]}
    )


def _quick_sale(shop: Shop, sku: str, token: str | None = None) -> dict[str, Any]:
    body = {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
    return _ok(_post(shop.world, token or shop.owner, "/quick-sales", body), 201)


def _cost(shop: Shop, sku: str) -> dict[str, Any]:
    return _ok(shop.world.client.get(f"/api/v1/shop/costs/{sku}", headers=_bearer(shop.owner)))


def test_weighted_average_math() -> None:
    # 3 dona x 4 000 000 so'm + 5 dona x 3 840 000 so'm = 3 900 000 (spec §1), tiyinda
    assert weighted_average(400_000_000, 3, 384_000_000, 5) == 390_000_000
    assert weighted_average(100, 0, 250, 4) == 250  # qoldiq yo'q — yangi narx
    assert weighted_average(100, 1, 101, 1) == 101  # 100.5 -> yuqoriga
    assert weighted_average(100, 3, 101, 1) == 100  # 100.25 -> pastga


def test_receipt_cost_updates_average_in_same_transaction(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    _ok(_receive_cost(shop, sku, 3, 400_000_000), 201)
    first = _cost(shop, sku)
    assert (first["avg_unit_cost_uzs_minor"], first["basis_qty"], first["last_reason"]) == (
        400_000_000,
        3,
        "RECEIPT",
    )
    _ok(_receive_cost(shop, sku, 5, 384_000_000), 201)
    second = _cost(shop, sku)
    assert (second["avg_unit_cost_uzs_minor"], second["basis_qty"], second["cost_version"]) == (
        390_000_000,
        8,
        2,
    )
    # boshqa filialdagi qoldiq ham hisobga kiradi (shop bo'yicha)
    shop.receive(sku, 2, branch=shop.branch2)
    _ok(_receive_cost(shop, sku, 10, 400_000_000), 201)
    assert _cost(shop, sku)["avg_unit_cost_uzs_minor"] == (390_000_000 * 10 + 400_000_000 * 10) // 20
    history = _ok(world.client.get(f"/api/v1/shop/costs/{sku}/history", headers=_bearer(shop.owner)))
    assert [h["reason"] for h in history["items"]] == ["RECEIPT"] * 3
    assert history["items"][1]["avg_before_uzs_minor"] == 400_000_000
    assert history["items"][1]["avg_after_uzs_minor"] == 390_000_000
    rows = _admin_sql(
        world, "SELECT count(*) AS n FROM commerce.stock_receipt_costs WHERE shop_id = $1", shop.id
    )
    assert rows[0]["n"] == 3


def test_failed_receipt_leaves_no_cost(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    bad = _post(
        world,
        shop.owner,
        "/stock/receipts",
        {
            "branch_id": shop.branch,
            "lines": [
                {"sku_id": sku, "qty": 1, "unit_cost_minor": 100_000},
                {"sku_id": "00000000-0000-4000-8000-000000000000", "qty": 1},
            ],
        },
    )
    assert bad.status_code == 422
    assert world.client.get(f"/api/v1/shop/costs/{sku}", headers=_bearer(shop.owner)).status_code == 404


def test_usd_cost_is_converted_with_shop_rate(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    no_rate = _receive_cost(shop, sku, 1, 30_000, currency="USD")
    assert no_rate.status_code == 422
    shop.rate("12800")
    _ok(_receive_cost(shop, sku, 5, 30_000, currency="USD"), 201)  # 300 $ x 12 800 = 3 840 000 so'm
    assert _cost(shop, sku)["avg_unit_cost_uzs_minor"] == 384_000_000
    row = _admin_sql(
        world,
        "SELECT cost_currency, unit_cost_minor, exchange_rate_snapshot, exchange_rate_id "
        "FROM commerce.stock_receipt_costs WHERE shop_id = $1",
        shop.id,
    )[0]
    assert (row["cost_currency"], row["unit_cost_minor"], str(row["exchange_rate_snapshot"])) == (
        "USD",
        30_000,
        "12800.000000",
    )
    assert row["exchange_rate_id"] is not None


def test_cost_unknown_stays_null_and_receipt_without_cost_is_untouched(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 3)  # tannarxsiz kirim
    assert world.client.get(f"/api/v1/shop/costs/{sku}", headers=_bearer(shop.owner)).status_code == 404
    assert _ok(world.client.get("/api/v1/shop/costs", headers=_bearer(shop.owner)))["items"] == []
    sale = _ok(
        _post(
            world,
            shop.owner,
            "/quick-sales",
            {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]},
        ),
        201,
    )
    order = shop.step(shop.order({sku: 1}), "submit", "confirm", "start-processing", "mark-ready", "complete")
    rows = _admin_sql(
        world,
        "SELECT unit_cost_uzs_minor FROM commerce.quick_sale_lines WHERE quick_sale_id = $1 "
        "UNION ALL SELECT unit_cost_uzs_minor FROM commerce.order_lines WHERE order_id = $2",
        __import__("uuid").UUID(sale["id"]),
        __import__("uuid").UUID(order["id"]),
    )
    assert [r["unit_cost_uzs_minor"] for r in rows] == [None, None]


def test_unit_cost_has_a_sanity_cap(world: World) -> None:
    """QA7 F8: dona tannarxi 1e12 minordan oshmaydi (kirim ham, qo'lda ham)."""
    shop = Shop(world)
    sku = shop.sku()
    over = _receive_cost(shop, sku, 1, 10**12 + 1)
    assert over.status_code == 422 and "unit_cost_minor" in over.text
    assert world.client.get(f"/api/v1/shop/costs/{sku}", headers=_bearer(shop.owner)).status_code == 404
    manual = world.client.put(
        f"/api/v1/shop/costs/{sku}",
        json={"avg_unit_cost_uzs_minor": 10**12 + 1, "reason": "juda katta qiymat"},
        headers=_bearer(shop.owner, **_idem()),
    )
    assert manual.status_code == 422
    _ok(_receive_cost(shop, sku, 1, 10**12), 201)  # chegaraning o'zi o'tadi
    assert _cost(shop, sku)["avg_unit_cost_uzs_minor"] == 10**12


def test_manual_set_adjusts_average_with_reason(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 4)  # tizimgacha bo'lgan qoldiq kabi, tannarxsiz
    path = f"/api/v1/shop/costs/{sku}"

    def put(body: dict[str, Any]) -> Any:
        return world.client.put(path, json=body, headers=_bearer(shop.owner, **_idem()))

    assert put({"avg_unit_cost_uzs_minor": 350_000_000}).status_code == 422  # izoh majburiy
    ok = _ok(
        put({"avg_unit_cost_uzs_minor": 350_000_000, "reason": "tizimgacha qoldiq, hisob-faktura bo'yicha"})
    )
    assert (ok["avg_unit_cost_uzs_minor"], ok["last_reason"], ok["basis_qty"]) == (
        350_000_000,
        "MANUAL_SET",
        4,
    )
    again = _ok(put({"avg_unit_cost_uzs_minor": 360_000_000, "reason": "to'g'rilandi"}))
    assert again["cost_version"] == 2
    _ok(_receive_cost(shop, sku, 4, 380_000_000), 201)  # (360 x 4 + 380 x 4) / 8 = 370
    assert _cost(shop, sku)["avg_unit_cost_uzs_minor"] == 370_000_000
    history = _ok(world.client.get(f"{path}/history", headers=_bearer(shop.owner)))["items"]
    assert [h["reason"] for h in history] == ["RECEIPT", "MANUAL_SET", "MANUAL_SET"]
    assert history[1]["note"] == "to'g'rilandi" and history[1]["avg_before_uzs_minor"] == 350_000_000


def test_sales_snapshot_cost_and_freeze_profit(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    _ok(_receive_cost(shop, sku, 6, 390_000_000), 201)
    sale = _ok(
        _post(
            world,
            shop.owner,
            "/quick-sales",
            {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]},
        ),
        201,
    )
    order = shop.step(shop.order({sku: 1}), "submit", "confirm", "start-processing", "mark-ready")
    _ok(_receive_cost(shop, sku, 6, 450_000_000), 201)  # B = 5 (bittasi sotildi), o'rtacha ko'tariladi
    expected = weighted_average(390_000_000, 5, 450_000_000, 6)
    assert expected == 422_727_273
    shop.step(order, "complete")
    quick = _admin_sql(
        world,
        "SELECT unit_cost_uzs_minor FROM commerce.quick_sale_lines WHERE shop_id = $1",
        shop.id,
    )
    assert [r["unit_cost_uzs_minor"] for r in quick] == [390_000_000]
    line = _admin_sql(
        world, "SELECT unit_cost_uzs_minor FROM commerce.order_lines WHERE shop_id = $1", shop.id
    )
    assert [r["unit_cost_uzs_minor"] for r in line] == [expected]  # tugallanish paytidagi o'rtacha
    # keyingi o'zgarish eski sotuv nusxasiga tegmaydi
    _ok(_receive_cost(shop, sku, 100, 900_000_000), 201)
    line = _admin_sql(
        world, "SELECT unit_cost_uzs_minor FROM commerce.order_lines WHERE shop_id = $1", shop.id
    )
    assert [r["unit_cost_uzs_minor"] for r in line] == [expected]
    assert sale["id"]


def test_only_owner_sees_or_enters_cost(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    _ok(_receive_cost(shop, sku, 2, 100_000_000), 201)
    warehouse, _ = shop.staff("WAREHOUSE")
    manager, _ = shop.staff("MANAGER")
    sales, _ = shop.staff("SALES")
    for token in (warehouse, manager, sales):
        assert world.client.get("/api/v1/shop/costs", headers=_bearer(token)).status_code == 403
        assert world.client.get(f"/api/v1/shop/costs/{sku}", headers=_bearer(token)).status_code == 403
        assert (
            world.client.get(f"/api/v1/shop/costs/{sku}/history", headers=_bearer(token)).status_code == 403
        )
    for token in (warehouse, manager):
        assert _receive_cost(shop, sku, 1, 90_000_000, token=token).status_code == 403
        # tannarxsiz kirim ularda avvalgidek ishlaydi
        _ok(_receive_cost(shop, sku, 1, None, token=token), 201)
    assert (
        _cost(shop, sku)["avg_unit_cost_uzs_minor"] == 100_000_000
    )  # rad etilgan kirim o'rtachani o'zgartirmadi

    # javoblarda tannarx maydoni yo'q (ega uchun ham: tannarx faqat /costs da)
    receipt = _ok(_receive_cost(shop, sku, 1, 100_000_000), 201)
    sale = _ok(
        _post(
            shop.world,
            manager,
            "/quick-sales",
            {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]},
        ),
        201,
    )
    order = shop.step(shop.order({sku: 1}), "submit", "confirm", "start-processing", "mark-ready", "complete")
    bodies = [
        receipt,
        sale,
        order,
        _ok(world.client.get("/api/v1/shop/stock", headers=_bearer(warehouse))),
        _ok(world.client.get(f"/api/v1/shop/stock/receipts/{receipt['id']}", headers=_bearer(warehouse))),
        _ok(world.client.get("/api/v1/shop/stock/receipts", headers=_bearer(warehouse))),
        _ok(
            world.client.get("/api/v1/shop/stock/history", params={"sku_id": sku}, headers=_bearer(warehouse))
        ),
    ]
    for body in bodies:
        assert "cost" not in str(body).lower()


def test_cost_tables_are_isolated_between_shops(world: World) -> None:
    a, b = Shop(world), Shop(world)
    sku_a, sku_b = a.sku(), b.sku()
    _ok(_receive_cost(a, sku_a, 2, 100_000_000), 201)
    _ok(_receive_cost(b, sku_b, 2, 200_000_000), 201)
    assert [
        i["sku_id"] for i in _ok(world.client.get("/api/v1/shop/costs", headers=_bearer(a.owner)))["items"]
    ] == [sku_a]
    assert world.client.get(f"/api/v1/shop/costs/{sku_b}", headers=_bearer(a.owner)).status_code == 404
    put = world.client.put(
        f"/api/v1/shop/costs/{sku_b}",
        json={"avg_unit_cost_uzs_minor": 1, "reason": "hujum"},
        headers=_bearer(a.owner, **_idem()),
    )
    assert put.status_code == 404
    runtime = world.urls.runtime.replace("postgresql+asyncpg://", "postgresql://")

    async def visible(table: str, shop_id: Any) -> int:
        conn = await asyncpg.connect(runtime)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", str(shop_id))
                return int(await conn.fetchval(f"SELECT count(*) FROM commerce.{table}"))
        finally:
            await conn.close()

    for table in ("sku_costs", "sku_cost_changes", "stock_receipt_costs"):
        assert asyncio.run(visible(table, a.id)) == 1 and asyncio.run(visible(table, b.id)) == 1
        assert asyncio.run(visible(table, "00000000-0000-4000-8000-000000000000")) == 0


def test_shortage_adjustment_copies_current_cost(world: World) -> None:
    shop = Shop(world)
    known, unknown = shop.sku(), shop.sku()
    _ok(_receive_cost(shop, known, 3, 250_000_000), 201)
    shop.receive(unknown, 3)
    for sku in (known, unknown):
        body = {
            "branch_id": shop.branch,
            "sku_id": sku,
            "kind": "ADJUSTMENT",
            "delta": -1,
            "reason": "buzilgan",
        }
        _ok(_post(world, shop.owner, "/stock/adjustments", body), 201)
    rows = _admin_sql(
        world,
        "SELECT sku_id::text AS sku, unit_cost_uzs_minor AS cost "
        "FROM commerce.stock_adjustments WHERE shop_id = $1",
        shop.id,
    )
    assert {r["sku"]: r["cost"] for r in rows} == {known: 250_000_000, unknown: None}
