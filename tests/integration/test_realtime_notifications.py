"""5a: platforma boti (bog'lash kodi, yetkazish, to'xtatish, bloklash) va realtime WebSocket (08 §6).

Telegram — `FakeTelegramSender`; realtime — API ilovasining xotiradagi broker'i (`MemoryBroker`).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config.settings import Settings
from app.main import create_app
from app.platform.notifications.providers import build_notification_services
from app.platform.notifications.telegram import FakeTelegramSender, TelegramSendError
from app.shared.realtime import MemoryBroker
from tests.conftest import FAST_TEST_SETTINGS
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _ok, _post
from tests.integration.test_jobs_events import _drain_now

pytestmark = pytest.mark.integration

SECRET = "platform-bot-secret"
CHAT_ID, TELEGRAM_USER = 777000, 424242


@pytest.fixture
def bot(world: World) -> FakeTelegramSender:
    """API ilovasi soxta bot bilan (worker ham shu servislarni ishlatadi)."""
    fake = FakeTelegramSender()
    world.client.app.state.notifications = build_notification_services(  # type: ignore[attr-defined]
        fake, bot_username="cos_staff_bot", bot_configured=True, webhook_secret=SECRET
    )
    return fake


def _start(world: World, code: str, secret: str = SECRET, user: int = TELEGRAM_USER) -> Any:
    update = {
        "message": {
            "text": f"/start {code}",
            "chat": {"id": CHAT_ID, "type": "private"},
            "from": {"id": user},
        }
    }
    return world.client.post(
        "/api/v1/webhooks/platform-telegram", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret}
    )


def _link(world: World, token: str) -> None:
    code = _ok(world.client.post("/api/v1/shop/me/telegram-link", headers=_bearer(token)), 201)
    assert code["deep_link"] == f"https://t.me/cos_staff_bot?start={code['code']}"
    assert _ok(_start(world, code["code"])) == {"ok": True}


def _adjustment_request(world: World, shop: Shop, warehouse: str, sku: str) -> dict[str, Any]:
    body = {"branch_id": shop.branch, "sku_id": sku, "delta": -1, "reason": "sanoqda kam"}
    return _ok(_post(world, warehouse, "/stock/adjustments", body), 201)


def _delivery(world: World, shop: Shop, template_key: str) -> list[tuple[str, str | None]]:
    rows = _admin_sql(
        world,
        "SELECT n.status, n.suppressed_reason FROM platform.notifications n "
        "JOIN platform.memberships m ON m.id = n.recipient_membership_id "
        "WHERE n.shop_id = $1 AND n.template_key = $2 AND m.role = 'OWNER' ORDER BY n.created_at",
        shop.id,
        template_key,
    )
    return [(r["status"], r["suppressed_reason"]) for r in rows]


# ------------------------------------------------------------------ platforma boti
def test_staff_links_platform_bot_and_receives_notification_once(
    world: World, bot: FakeTelegramSender
) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 3)
    status = _ok(world.client.get("/api/v1/shop/me/telegram-link", headers=_bearer(shop.owner)))
    assert (status["linked"], status["bot_configured"]) == (False, True)
    assert _start(world, "ANYCODE", secret="wrong").status_code == 404  # sir noto'g'ri — webhook "yo'q"
    assert _ok(_start(world, "NOTACODE12")) == {"ok": True}  # noto'g'ri kod — 200, lekin ulanmaydi
    _link(world, shop.owner)
    assert bot.sent[-1][0] == CHAT_ID and "Ulandi" in bot.sent[-1][1]
    assert (
        _ok(world.client.get("/api/v1/shop/me/telegram-link", headers=_bearer(shop.owner)))["linked"] is True
    )
    settings = _ok(world.client.get("/api/v1/shop/me/notification-settings", headers=_bearer(shop.owner)))
    assert settings["telegram_linked"] is True and settings["version"] == 0

    before = len(bot.sent)
    _adjustment_request(world, shop, warehouse, sku)
    _drain_now(world)
    owner_messages = [text for chat, text in bot.sent[before:] if chat == CHAT_ID]
    assert len(owner_messages) == 1 and "tuzatish" in owner_messages[0].lower()
    assert _delivery(world, shop, "staff.adjustment_approval") == [("SENT", None)]
    _drain_now(world)  # event qayta kelsa ham — ikkinchi xabar yo'q
    assert len([c for c, _ in bot.sent[before:] if c == CHAT_ID]) == 1


def test_muted_staff_is_suppressed_and_blocked_bot_unlinks(world: World, bot: FakeTelegramSender) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 5)
    _link(world, shop.owner)
    headers = _bearer(shop.owner, **{"If-Match": '"v0"'})
    saved = _ok(
        world.client.put(
            "/api/v1/shop/me/notification-settings",
            json={"telegram_enabled": False, "muted_types": []},
            headers=headers,
        )
    )
    assert saved["version"] == 1 and saved["telegram_enabled"] is False
    _adjustment_request(world, shop, warehouse, sku)
    _drain_now(world)
    assert _delivery(world, shop, "staff.adjustment_approval") == [("SUPPRESSED", "MUTED")]

    _ok(
        world.client.put(
            "/api/v1/shop/me/notification-settings",
            json={"telegram_enabled": True},
            headers=_bearer(shop.owner, **{"If-Match": '"v1"'}),
        )
    )
    bot.fail_with = TelegramSendError("BLOCKED", retryable=False)
    _adjustment_request(world, shop, warehouse, sku)
    _drain_now(world)
    assert _delivery(world, shop, "staff.adjustment_approval")[-1] == ("FAILED", None)
    assert (
        _ok(world.client.get("/api/v1/shop/me/telegram-link", headers=_bearer(shop.owner)))["linked"] is False
    )


def test_link_code_is_single_use(world: World, bot: FakeTelegramSender) -> None:
    shop = Shop(world)
    code = _ok(world.client.post("/api/v1/shop/me/telegram-link", headers=_bearer(shop.owner)), 201)["code"]
    _start(world, code)
    other = Shop(world)
    _start(world, code, user=999)  # o'sha kod ikkinchi marta — ishlamaydi
    assert (
        _ok(world.client.get("/api/v1/shop/me/telegram-link", headers=_bearer(other.owner)))["linked"]
        is False
    )
    rows = _admin_sql(
        world, "SELECT telegram_user_id FROM platform.staff_telegram_links WHERE telegram_user_id = 999"
    )
    assert rows == []
    assert (
        world.client.delete("/api/v1/shop/me/telegram-link", headers=_bearer(shop.owner)).status_code == 204
    )
    assert (
        _ok(world.client.get("/api/v1/shop/me/telegram-link", headers=_bearer(shop.owner)))["linked"] is False
    )


# ------------------------------------------------------------------ realtime
def _ticket(client: TestClient, token: str) -> str:
    response = client.post("/api/v1/auth/ws-ticket", headers=_bearer(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] == 30 and body["path"] == "/api/v1/ws"
    return str(body["ticket"])


def _member_id(world: World, shop: Shop) -> UUID:
    [row] = _admin_sql(
        world, "SELECT id FROM platform.memberships WHERE shop_id = $1 AND role = 'OWNER'", shop.id
    )
    return UUID(str(row["id"]))


def _closed_with(ws: Any) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        for _ in range(20):
            ws.receive_json()
    return int(closed.value.code)


def test_ticket_is_single_use_and_required(world: World) -> None:
    shop = Shop(world)
    ticket = _ticket(world.client, shop.owner)
    with world.client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["seq"] == 0
    with world.client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
        assert _closed_with(ws) == 4401  # ikkinchi marta — yo'q
    with world.client.websocket_connect("/api/v1/ws") as ws:
        assert _closed_with(ws) == 4401
    assert world.client.post("/api/v1/auth/ws-ticket").status_code == 401


def test_expired_ticket_is_rejected(world: World) -> None:
    shop = Shop(world)
    broker: MemoryBroker = world.client.app.state.realtime  # type: ignore[attr-defined]
    ticket = _ticket(world.client, shop.owner)
    from app.platform.auth.tokens import hash_token

    data = asyncio.run(broker.take_ticket(hash_token(ticket)))
    assert data is not None
    asyncio.run(broker.put_ticket(hash_token(ticket), data, 0))  # muddati o'tgan
    with world.client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
        assert _closed_with(ws) == 4401


def test_signals_reach_only_their_recipient(world: World) -> None:
    shop, other = Shop(world), Shop(world)
    broker: MemoryBroker = world.client.app.state.realtime  # type: ignore[attr-defined]
    mine, theirs = _member_id(world, shop), _member_id(world, other)
    with world.client.websocket_connect(f"/api/v1/ws?ticket={_ticket(world.client, other.owner)}") as ws:
        assert ws.receive_json()["type"] == "hello"
        asyncio.run(broker.publish(mine, {"type": "order.changed", "resource": {"kind": "order", "id": "a"}}))
        asyncio.run(broker.publish(theirs, {"type": "task.created", "resource": {"kind": "task", "id": "b"}}))
        first = ws.receive_json()
        assert (
            first["type"] == "task.created" and first["resource"]["id"] == "b"
        )  # boshqa shop signali kelmadi


def test_committed_events_become_panel_signals(world: World) -> None:
    shop = Shop(world)
    warehouse, _ = shop.staff("WAREHOUSE")
    sku = shop.sku()
    shop.receive(sku, 3)
    _drain_now(world)  # avvalgi event'lar (qoldiq) — signal ularsiz boshlansin
    with world.client.websocket_connect(f"/api/v1/ws?ticket={_ticket(world.client, shop.owner)}") as ws:
        hello = ws.receive_json()
        _adjustment_request(world, shop, warehouse, sku)
        _drain_now(world)
        received = [ws.receive_json() for _ in range(2)]
        kinds = {m["type"] for m in received}
        assert kinds == {"notification.created", "task.created"}
        assert all(m["seq"] > hello["seq"] for m in received)
        task = next(m for m in received if m["type"] == "task.created")
        assert task["resource"]["kind"] == "task" and "sanoqda" not in str(received)  # matn yo'q


def test_socket_closes_when_session_is_revoked(world: World) -> None:
    shop = Shop(world)
    settings = Settings(
        **{
            **FAST_TEST_SETTINGS,
            "database_url": world.settings.database_url,
            "realtime_heartbeat_seconds": 0.3,
        }
    )  # type: ignore[arg-type]
    with TestClient(create_app(settings)) as fast:
        ticket = _ticket(fast, shop.owner)
        with fast.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["type"] == "ping"  # heartbeat va qayta tekshiruv
            revoked = world.client.post("/api/v1/auth/logout-all", headers=_bearer(shop.owner, **_idem()))
            assert revoked.status_code == 204
            started = time.monotonic()
            assert _closed_with(ws) == 4401
            assert time.monotonic() - started < 5
