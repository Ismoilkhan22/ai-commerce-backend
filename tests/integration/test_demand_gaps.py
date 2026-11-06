"""DEC-149, 4-qism: "So'rashdi, lekin bizda yo'q" hisoboti va omborda yo'q tovar uchun "buyurtma asosida".

AI — `FakeProvider` demo rejimi (`catalog_search` → javob), Telegram — `FakeTelegramClient`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.platform.llm.providers.fake import FakeProvider
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import _ok
from tests.integration.test_jobs_events import _drain_now, _job
from tests.integration.test_messaging import Inbox, clean_outbox  # noqa: F401 (autouse)
from tests.integration.test_sales_ai import _enable, _patch_settings, _product

pytestmark = pytest.mark.integration


@pytest.fixture
def fake(world: World) -> Iterator[FakeProvider]:
    provider: FakeProvider = world.client.app.state.sales_ai.router.provider
    provider.script.clear()
    provider.requests.clear()
    yield provider
    provider.script.clear()


def test_demand_gaps_report_and_weekly_notification(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    _product(inbox.shop)  # chiqarilgan, lekin omborda yo'q
    _enable(world, inbox, "SUGGEST")
    inbox.text("RTX 4060 bormi?", user_id=7001)
    inbox.text("RTX 5090 bormi?", user_id=7002)
    _drain_now(world)
    report = _ok(world.client.get("/api/v1/shop/ai/demand-gaps?days=7", headers=_bearer(inbox.owner)))
    kinds = {item["query"]: item["kind"] for item in report["items"]}
    assert kinds.get("rtx 4060") == "OUT_OF_STOCK", report
    assert kinds.get("rtx 5090") == "NOT_FOUND", report
    assert all(item["times"] >= 1 and item["conversations"] == 1 for item in report["items"])
    sales = inbox.shop.staff("SALES")[0]
    assert world.client.get("/api/v1/shop/ai/demand-gaps", headers=_bearer(sales)).status_code == 403

    _job(world, "sales_ai_demand_gaps_weekly")
    _job(world, "sales_ai_demand_gaps_weekly")  # shu hafta ikkinchi marta — takror yo'q
    feed = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(inbox.owner)))["items"]
    weekly = [n for n in feed if n["template_key"] == "staff.demand_gaps_weekly"]
    assert len(weekly) == 1 and weekly[0]["link"] == {"route": "demand_gaps", "id": None}


def test_special_order_policy_reaches_the_prompt(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    settings = _ok(
        _patch_settings(world, inbox.owner, {"special_order": {"enabled": True, "lead_time": " 2–5 kun "}})
    )
    assert settings["special_order"] == {"enabled": True, "lead_time": "2–5 kun"}
    _enable(world, inbox, "SUGGEST")
    inbox.text("RTX 5090 bormi?")
    _drain_now(world)
    system = "\n".join(block.text for block in fake.requests[0].system)
    assert "CAN bring a product" in system and "2–5 kun" in system
    _ok(_patch_settings(world, inbox.owner, {"special_order": {"enabled": False}}))
    inbox.text("RTX 5080 bormi?", user_id=7100)
    _drain_now(world)
    system = "\n".join(block.text for block in fake.requests[-1].system)
    assert "special orders are not offered" in system and "2–5 kun" not in system
