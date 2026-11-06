"""M30 (Stage 2): hamkor API kalitlari (BL-089) — faqat ega yaratadi; sir bir marta; ruxsat doirasi; narx
yozish oddiy versiya bilan; bekor qilingan kalit darhol 401; boshqa shop SKU'siga tegib bo'lmaydi.
"""

from __future__ import annotations

import pytest

from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok
from tests.integration.test_network import _activate, _product, clean_outbox  # noqa: F401

pytestmark = pytest.mark.integration
KEYS = "/api/v1/shop/network/api-keys"
API = "/api/v1/partner"


def _key(world: World, shop: Shop, scopes: list[str]) -> dict[str, str]:
    return _ok(
        world.client.post(KEYS, json={"name": "1C kassa", "scopes": scopes}, headers=_bearer(shop.owner)), 201
    )


def test_partner_key_scopes_price_write_and_revoke(world: World) -> None:
    shop, other = Shop(world), Shop(world)
    _activate(world, shop)
    _activate(world, other)
    sku = _product(shop, "Kingston Fury 16GB", "Kingston", "KF556C40BB-16")
    foreign = _product(other, "Begona SKU", "MSI", "X1")
    manager, _ = shop.staff("MANAGER")
    assert (
        world.client.post(
            KEYS, json={"name": "x", "scopes": ["catalog.read"]}, headers=_bearer(manager)
        ).status_code
        == 403
    )

    reader = _key(world, shop, ["catalog.read"])
    assert reader["secret"].startswith(f"cos_{reader['prefix']}_")
    listed = _ok(world.client.get(KEYS, headers=_bearer(shop.owner)))["items"]
    assert "secret" not in listed[0]  # sir faqat yaratilganda
    raw = _admin_sql(world, "SELECT key_hash FROM network.api_keys WHERE id = $1", reader["id"])
    assert reader["secret"] not in raw[0]["key_hash"]

    headers = _bearer(reader["secret"])
    items = _ok(world.client.get(f"{API}/skus", headers=headers))["items"]
    assert [i["sku_id"] for i in items] == [sku] and items[0]["availability"] is None  # stock.read yo'q
    denied = world.client.put(
        f"{API}/skus/{sku}/price", json={"amount_minor": 1, "currency": "UZS"}, headers=headers
    )
    assert denied.status_code == 403

    writer = _key(world, shop, ["catalog.read", "prices.write"])
    w = _bearer(writer["secret"])
    changed = _ok(
        world.client.put(
            f"{API}/skus/{sku}/price", json={"amount_minor": 99_000_000, "currency": "UZS"}, headers=w
        )
    )
    assert changed["changed"] is True
    same = _ok(
        world.client.put(
            f"{API}/skus/{sku}/price", json={"amount_minor": 99_000_000, "currency": "UZS"}, headers=w
        )
    )
    assert same["changed"] is False
    history = _ok(world.client.get(f"/api/v1/shop/skus/{sku}/price-history", headers=_bearer(shop.owner)))
    assert (
        history["items"][0]["amount_minor"] == 99_000_000
        and history["items"][0]["reason"] == "Hamkor API: 1C kassa"
    )
    cross = world.client.put(
        f"{API}/skus/{foreign}/price", json={"amount_minor": 5, "currency": "UZS"}, headers=w
    )
    assert cross.status_code == 404  # boshqa shop SKU'si

    _ok(
        world.client.post(
            f"{KEYS}/{writer['id']}/revoke", json={"reason": "Sizib chiqdi"}, headers=_bearer(shop.owner)
        )
    )
    assert world.client.get(f"{API}/skus", headers=w).status_code == 401
    assert world.client.get(f"{API}/skus", headers=_bearer("cos_000000000000_soxta")).status_code == 401


def test_pos_stock_sync_conflicts_and_auto_apply(world: World) -> None:
    """M22 (BR-X12, TC-019): eski qoldiq ustidan yozilmaydi; standartda farq tasdiqqa tushadi."""
    from datetime import UTC, datetime, timedelta

    from tests.integration.test_jobs_events import _drain_now

    shop = Shop(world)
    _activate(world, shop)
    sku = shop.sku()
    shop.receive(sku, 10)
    review = _key(world, shop, ["stock.write"])
    auto = _ok(
        world.client.post(
            KEYS,
            json={"name": "ERP", "scopes": ["stock.write"], "stock_auto_apply": True},
            headers=_bearer(shop.owner),
        ),
        201,
    )
    now = datetime.now(UTC)

    def push(secret: str, on_hand: int, observed: datetime) -> str:
        body = {
            "items": [
                {
                    "sku_id": sku,
                    "branch_id": shop.branch,
                    "on_hand": on_hand,
                    "observed_at": observed.isoformat(),
                }
            ]
        }
        return str(
            _ok(world.client.put(f"{API}/stock", json=body, headers=_bearer(secret)), 202)["report_id"]
        )

    def result(secret: str, report_id: str) -> dict[str, int]:
        _drain_now(world)
        report = _ok(world.client.get(f"{API}/stock/reports/{report_id}", headers=_bearer(secret)))
        assert report["status"] == "PROCESSED", report
        return dict(report["results"])

    def on_hand() -> int:
        rows = _ok(world.client.get(f"/api/v1/shop/stock?sku_id={sku}", headers=_bearer(shop.owner)))["items"]
        return next(r["on_hand"] for r in rows if r["branch_id"] == shop.branch)

    # Eski (kirimdan oldin sanalgan) — ustidan yozilmaydi
    assert result(review["secret"], push(review["secret"], 3, now - timedelta(days=1))) == {"STALE": 1}
    # Yangi, lekin avtomatik emas — tasdiqqa (qoldiq o'zgarmaydi)
    assert result(review["secret"], push(review["secret"], 7, now + timedelta(seconds=1))) == {
        "PENDING_APPROVAL": 1
    }
    assert on_hand() == 10
    # Avtomatik kalit — darhol qo'llanadi
    assert result(auto["secret"], push(auto["secret"], 8, datetime.now(UTC) + timedelta(seconds=2))) == {
        "APPLIED": 1
    }
    assert on_hand() == 8
    # Teng — o'zgarishsiz
    assert result(auto["secret"], push(auto["secret"], 8, datetime.now(UTC) + timedelta(seconds=3))) == {
        "UNCHANGED": 1
    }
    reader = _key(world, shop, ["catalog.read"])
    denied = world.client.put(f"{API}/stock", json={"items": []}, headers=_bearer(reader["secret"]))
    assert denied.status_code in (403, 422)
