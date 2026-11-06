"""M39 global Telegram bot + M36 narx ogohlantirishi (BL-102, BL-103, BL-108).

Qidiruv faqat ommaviy takliflardan; ogohlantirish faqat xaridor yoqadi; narx tushsa — xabar, 24 soatda ko'pi
bilan bir marta; bekor qilish bir bosishda; boshqa chatning ogohlantirishini bekor qilib bo'lmaydi.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from app.domains.network.services.global_bot import FakeGlobalBotClient
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _ok
from tests.integration.test_jobs_events import _drain_now, _job
from tests.integration.test_network import _activate, _product, _publish, clean_outbox  # noqa: F401

pytestmark = pytest.mark.integration
SECRET = "global-bot-secret-123"


@pytest.fixture
def bot(world: World) -> Iterator[FakeGlobalBotClient]:
    state = world.client.app.state
    fake = FakeGlobalBotClient()
    state.network.global_bot.connect(fake)
    saved = state.global_bot_secret
    state.global_bot_secret = SECRET
    yield fake
    state.network.global_bot.connect(None)
    state.global_bot_secret = saved


def _update(world: World, payload: dict[str, Any]) -> Any:
    return world.client.post(
        "/api/v1/webhooks/global-telegram", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET}
    )


def _text(chat_id: int, text: str) -> dict[str, Any]:
    return {
        "message": {"chat": {"id": chat_id, "type": "private"}, "from": {"language_code": "uz"}, "text": text}
    }


def _button(chat_id: int, data: str) -> dict[str, Any]:
    return {
        "callback_query": {
            "from": {"language_code": "uz"},
            "data": data,
            "message": {"chat": {"id": chat_id, "type": "private"}},
        }
    }


def test_bot_search_alert_on_drop_and_cancel(world: World, bot: FakeGlobalBotClient) -> None:
    shop = Shop(world)
    _activate(world, shop)
    word = f"lyra{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} RTX 4060", "MSI", f"L{uuid4().hex[:7].upper()}", amount=400_000_000)
    _ok(_publish(world, shop.owner, sku))
    assert (
        world.client.post("/api/v1/webhooks/global-telegram", json=_text(1, "x")).status_code == 404
    )  # sirsiz

    _ok(_update(world, _text(7001, word)))
    _, line, buttons = bot.sent[-1]
    assert word in line and "4 000 000" in line and buttons is not None
    alert_data = buttons[1][0]["callback_data"]
    canonical = alert_data.removeprefix("alert:")
    _ok(_update(world, _button(7001, alert_data)))
    assert "Yoqildi" in bot.sent[-1][1]

    # Narx tushdi → bir marta xabar; qayta tekshiruvda (24 soat o'tmagan) — yo'q
    history = _ok(world.client.get(f"/api/v1/shop/skus/{sku}/price-history", headers=_bearer(shop.owner)))
    _ok(
        world.client.put(
            f"/api/v1/shop/skus/{sku}/price",
            json={"amount_minor": 380_000_000, "currency": "UZS"},
            headers=_bearer(shop.owner, **_idem(), **{"If-Match": f'"v{len(history["items"])}"'}),
        )
    )
    _drain_now(world)
    before = len(bot.sent)
    _job(world, "price_alerts_check")
    assert len(bot.sent) == before + 1 and "3 800 000" in bot.sent[-1][1]
    _job(world, "price_alerts_check")
    assert len(bot.sent) == before + 1  # BL-103: tez-tez emas

    rows = _admin_sql(world, "SELECT id FROM network.price_alerts WHERE canonical_id = $1", canonical)
    alert_id = str(rows[0]["id"])
    _ok(_update(world, _button(9999, f"cancel:{alert_id}")))  # boshqa chat — bekor qila olmaydi
    assert (
        _admin_sql(world, "SELECT status FROM network.price_alerts WHERE id = $1", rows[0]["id"])[0]["status"]
        == "ACTIVE"
    )
    _ok(_update(world, _button(7001, f"cancel:{alert_id}")))
    assert (
        _admin_sql(world, "SELECT status FROM network.price_alerts WHERE id = $1", rows[0]["id"])[0]["status"]
        == "CANCELLED"
    )
    raw = _admin_sql(world, "SELECT chat_id_enc FROM network.global_bot_chats LIMIT 50")
    assert all(r["chat_id_enc"] not in ("7001", "9999") for r in raw)  # chat raqami shifrlangan
