"""Stage 2/3 mustaqil QA topilmalari uchun regressiya testlari (QA #1, #3, #4, #6, #10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.shared.clock import utcnow
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok
from tests.integration.test_jobs_events import _drain_now, _run
from tests.integration.test_network import _activate, _product, _publish, clean_outbox  # noqa: F401
from tests.integration.test_partner_api import KEYS, _key

pytestmark = pytest.mark.integration
API = "/api/v1/public/marketplace"


def test_platform_suspended_offer_cannot_be_revived_by_owner(world: World) -> None:  # QA #1, #2
    shop = Shop(world)
    _activate(world, shop)
    word = f"qa{uuid4().hex[:8]}"
    sku = _product(shop, f"{word} GPU", "MSI", f"Q{uuid4().hex[:7].upper()}")
    _ok(_publish(world, shop.owner, sku))
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    offer_id = item["offer"]["offer_id"]
    _ok(
        world.client.post(f"/api/v1/shop/network/offers/{sku}/withdraw", headers=_bearer(shop.owner))
    )  # ega yopdi
    _admin_sql(
        world,
        "UPDATE network.public_offers SET status = 'ACTIVE', withdraw_reason = NULL WHERE id = $1",
        offer_id,
    )
    assert world.client.post(f"{API}/offers/{offer_id}/report", json={"reason": "FRAUD"}).status_code == 202
    admin = _bearer(world.admin_token)
    report = next(
        r
        for r in _ok(world.client.get("/api/v1/platform/network/reports", headers=admin))["items"]
        if r["offer_id"] == offer_id
    )
    resolved = world.client.post(
        f"/api/v1/platform/network/reports/{report['id']}/resolve",
        json={"action": "SUSPEND_OFFER", "resolution": "Firibgarlik"},
        headers=admin,
    )
    assert resolved.status_code == 204
    withdrawn = _ok(
        world.client.post(f"/api/v1/shop/network/offers/{sku}/withdraw", headers=_bearer(shop.owner))
    )
    assert withdrawn["withdraw_reason"] == "PLATFORM_REPORT"  # sabab almashtirilmadi
    assert _publish(world, shop.owner, sku).status_code == 422


def test_pos_stock_naive_and_future_times(world: World) -> None:  # QA #3
    from tests.integration.test_partner_api import API as PARTNER

    shop = Shop(world)
    _activate(world, shop)
    sku = shop.sku()
    shop.receive(sku, 5)
    key = _key(world, shop, ["stock.write"])
    naive = {
        "items": [
            {"sku_id": sku, "branch_id": shop.branch, "on_hand": 4, "observed_at": "2026-11-03T10:00:00"}
        ]
    }
    assert world.client.put(f"{PARTNER}/stock", json=naive, headers=_bearer(key["secret"])).status_code == 422
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    body = {"items": [{"sku_id": sku, "branch_id": shop.branch, "on_hand": 1, "observed_at": future}]}
    report = _ok(world.client.put(f"{PARTNER}/stock", json=body, headers=_bearer(key["secret"])), 202)
    _drain_now(world)
    result = _ok(
        world.client.get(f"{PARTNER}/stock/reports/{report['report_id']}", headers=_bearer(key["secret"]))
    )
    assert result["results"] == {"FUTURE": 1}
    assert KEYS


def _cycle(world: World, shop: Shop, days: int) -> Any:
    from app.workers.queue import RecordingQueue

    async def go(rt: Any) -> Any:
        async with rt.database.transaction(shop.id) as db:
            return await world.client.app.state.billing.cycle(
                db, shop.id, now=utcnow() + timedelta(days=days)
            )

    return _run(world, RecordingQueue(), go)


def test_voided_invoice_is_reissued_and_plan_change_voids_stale_invoice(world: World) -> None:  # QA #4, #6
    shop = Shop(world)
    admin = _bearer(world.admin_token)
    limits = {"branches": 2, "staff": 5, "skus": 1000, "ai_replies": 1000}
    for code, price in (("START", 30_000_000), ("PC_PRO", 60_000_000)):
        _ok(
            world.client.put(
                f"/api/v1/platform/billing/plans/{code}",
                json={"name": code, "monthly_price_uzs_minor": price, "limits": limits},
                headers=admin,
            )
        )
    _ok(
        world.client.post(
            "/api/v1/shop/billing/plan", json={"plan_code": "START"}, headers=_bearer(shop.owner)
        )
    )
    assert _cycle(world, shop, 26) == "INVOICED"
    [first] = _ok(world.client.get("/api/v1/shop/billing", headers=_bearer(shop.owner)))["invoices"]
    # Ega yangi tarif tanladi — eski tarifga chiqqan hisob bekor, yangi tarifga qayta chiqadi
    _ok(
        world.client.post(
            "/api/v1/shop/billing/plan", json={"plan_code": "PC_PRO"}, headers=_bearer(shop.owner)
        )
    )
    assert _cycle(world, shop, 27) == "INVOICED"
    invoices = _ok(world.client.get("/api/v1/shop/billing", headers=_bearer(shop.owner)))["invoices"]
    statuses = {i["id"]: (i["status"], i["plan_code"]) for i in invoices}
    assert statuses[first["id"]] == ("VOID", "START")
    assert ("ISSUED", "PC_PRO") in statuses.values()
    # Admin bekor qilsa ham — yangisi chiqadi
    live = next(i for i in invoices if i["status"] == "ISSUED")
    _ok(
        world.client.post(
            f"/api/v1/platform/billing/invoices/{live['id']}/void", json={"note": "Narx xato"}, headers=admin
        )
    )
    assert _cycle(world, shop, 28) == "INVOICED"
    platform_view = _ok(world.client.get(f"/api/v1/platform/billing/shops/{shop.id}", headers=admin))
    assert platform_view["usage"]["branches"] == 2 and platform_view["usage"]["staff"] >= 1  # QA #5


def test_ad_click_counts_only_for_its_own_offer(world: World) -> None:  # QA #10
    shop = Shop(world)
    _activate(world, shop)
    word = f"adq{uuid4().hex[:6]}"
    sku_ad = _product(shop, f"{word} reklama", "LG", f"R{uuid4().hex[:7].upper()}")
    sku_other = _product(shop, f"{word} boshqa", "LG", f"S{uuid4().hex[:7].upper()}")
    _ok(_publish(world, shop.owner, sku_ad, sku_other))
    now = datetime.now(UTC)
    ad = _ok(
        world.client.post(
            "/api/v1/shop/network/ads",
            json={
                "sku_id": sku_ad,
                "starts_at": (now - timedelta(hours=1)).isoformat(),
                "ends_at": (now + timedelta(days=1)).isoformat(),
            },
            headers=_bearer(shop.owner),
        ),
        201,
    )
    _ok(
        world.client.post(
            f"/api/v1/platform/network/ads/{ad['id']}/approve", headers=_bearer(world.admin_token)
        )
    )
    results = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    other_offer = next(r["offer"]["offer_id"] for r in results if "boshqa" in r["title"])
    _ok(world.client.post(f"{API}/offers/{other_offer}/visit?ad={ad['id']}"))
    assert (
        _ok(world.client.get("/api/v1/shop/network/ads", headers=_bearer(shop.owner)))["items"][0]["clicks"]
        == 0
    )
