"""M26 (Stage 2): tariflar va hisob-fakturalar — DEC-100 (to'lov tizimdan tashqarida), BL-083.

Yangi shop — TRIAL (PILOT); tarif keyingi davrdan; narxsiz tarifga hisob chiqmaydi; hisob davr tugashidan
5 kun oldin; to'langan hisob yangi davrni ochadi; to'lanmasa 7 kundan keyin PAST_DUE; avtomatik yechish yo'q.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.shared.clock import utcnow
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok

pytestmark = pytest.mark.integration


def _cycle(world: World, shop: Shop, days: int) -> Any:
    async def go(rt: Any) -> Any:
        async with rt.database.transaction(shop.id) as db:
            return await world.client.app.state.billing.cycle(
                db, shop.id, now=utcnow() + timedelta(days=days)
            )

    from app.workers.queue import RecordingQueue
    from tests.integration.test_jobs_events import _run

    return _run(world, RecordingQueue(), go)


def test_trial_plan_change_invoice_payment_and_past_due(world: World) -> None:
    shop = Shop(world)
    admin = _bearer(world.admin_token)
    billing = _ok(world.client.get("/api/v1/shop/billing", headers=_bearer(shop.owner)))
    assert billing["status"] == "TRIAL" and billing["plan"]["code"] == "PILOT"
    assert billing["usage"]["branches"] == 2 and billing["plan"]["limits"]["branches"] == 2
    manager, _ = shop.staff("MANAGER")
    assert world.client.get("/api/v1/shop/billing", headers=_bearer(manager)).status_code == 403

    # Narxsiz tarifni tanlash mumkin, lekin hisob chiqmaydi; founder narx qo'ygach — chiqadi
    chosen = _ok(
        world.client.post(
            "/api/v1/shop/billing/plan", json={"plan_code": "START"}, headers=_bearer(shop.owner)
        )
    )
    assert chosen["pending_plan_code"] == "START" and chosen["plan"]["code"] == "PILOT"
    assert _cycle(world, shop, 26) is None  # narx yo'q — hisob yo'q
    plan = {
        "name": "Start",
        "monthly_price_uzs_minor": 49_900_000,
        "limits": {"branches": 1, "staff": 3, "skus": 1000, "ai_replies": 2500},
    }
    _ok(world.client.put("/api/v1/platform/billing/plans/START", json=plan, headers=admin))
    assert _cycle(world, shop, 26) == "INVOICED"
    assert _cycle(world, shop, 27) is None  # takror hisob yo'q
    [invoice] = _ok(world.client.get("/api/v1/shop/billing", headers=_bearer(shop.owner)))["invoices"]
    assert invoice["status"] == "ISSUED" and invoice["amount_uzs_minor"] == 49_900_000

    # To'lanmagan: davr tugadi → 7 kun kutadi → PAST_DUE (yechib olinmaydi)
    assert _cycle(world, shop, 31) is None
    assert _cycle(world, shop, 38) == "PAST_DUE"
    paid = _ok(
        world.client.post(
            f"/api/v1/platform/billing/invoices/{invoice['id']}/paid",
            json={"note": "Bank o'tkazmasi 03.11"},
            headers=admin,
        )
    )
    assert paid["status"] == "PAID"
    after = _ok(world.client.get("/api/v1/shop/billing", headers=_bearer(shop.owner)))
    assert (
        after["status"] == "ACTIVE"
        and after["plan"]["code"] == "START"
        and after["pending_plan_code"] is None
    )
    again = world.client.post(
        f"/api/v1/platform/billing/invoices/{invoice['id']}/paid", json={"note": "takror"}, headers=admin
    )
    assert again.status_code == 409
    rows = _admin_sql(world, "SELECT count(*) AS n FROM platform.invoices WHERE shop_id = $1", shop.id)
    assert rows[0]["n"] == 1


def test_pilot_trial_ends_without_plan(world: World) -> None:
    shop = Shop(world)
    assert _cycle(world, shop, 31) == "TRIAL_ENDED"
    billing = _ok(world.client.get("/api/v1/shop/billing", headers=_bearer(shop.owner)))
    assert billing["status"] == "PAST_DUE"
    extended = _ok(
        world.client.put(
            f"/api/v1/platform/billing/shops/{shop.id}",
            json={"extend_days": 30},
            headers=_bearer(world.admin_token),
        )
    )
    assert extended["status"] == "TRIAL"
