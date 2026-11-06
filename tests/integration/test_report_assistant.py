"""Hisobot yordamchisi (19 §10): UAT-M18, TC-013 (ruxsatsiz metrika rad etiladi va yoziladi), TC-014 ("0").

LLM — `FakeProvider` (`light` navbati): faqat {metrika, davr} JSON qaytaradi; raqamlarni backend qo'yadi.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from app.platform.llm.providers.fake import FakeProvider, FakeText
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok

pytestmark = pytest.mark.integration
API = "/api/v1/shop/reporting/assistant"


@pytest.fixture
def llm(world: World) -> Iterator[FakeProvider]:
    provider: FakeProvider = world.client.app.state.sales_ai.router.provider
    provider.light_script.clear()
    provider.light_requests.clear()
    yield provider
    provider.light_script.clear()


def _plan(metric: str, period: str = "YESTERDAY") -> FakeText:
    return FakeText(json.dumps({"metric": metric, "period": period, "from": None, "to": None}))


def test_assistant_numbers_zero_forbidden_and_unmapped(world: World, llm: FakeProvider) -> None:
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    llm.push_light(_plan("orders_completed"))
    zero = _ok(
        world.client.post(
            API, json={"question": "Kecha nechta buyurtma topshirildi?"}, headers=_bearer(shop.owner)
        )
    )
    assert zero["metric"] == "orders_completed" and "\n0 — 0 so'm" in zero["answer"]  # TC-014: "0"
    assert zero["period"]["date_from"] == zero["period"]["date_to"]

    llm.push_light(_plan("gross_profit", "THIS_MONTH"))
    profit = _ok(world.client.post(API, json={"question": "Foydam qancha?"}, headers=_bearer(shop.owner)))
    assert "tannarx ma'lumoti yo'q" in profit["answer"]  # UAT-M18 salbiy holat

    llm.push_light(_plan("gross_profit"))
    denied = _ok(world.client.post(API, json={"question": "Foyda qancha bo'ldi?"}, headers=_bearer(manager)))
    assert denied["forbidden"] is True and "so'm" not in denied["answer"]  # TC-013: qiymat oshkor emas
    rows = _admin_sql(
        world,
        "SELECT count(*) AS n FROM audit.audit_entries "
        "WHERE shop_id = $1 AND action = 'reporting.assistant.forbidden'",
        shop.id,
    )
    assert rows[0]["n"] == 1

    llm.push_light(FakeText('{"metric": "UNKNOWN", "period": "TODAY"}'))
    unknown = _ok(world.client.post(API, json={"question": "Ob-havo qanday?"}, headers=_bearer(shop.owner)))
    assert unknown["unmapped"] is True and "Jami sotuv" in unknown["answer"]
    sales, _ = shop.staff("SALES")
    assert world.client.post(API, json={"question": "Sotuv?"}, headers=_bearer(sales)).status_code == 403
