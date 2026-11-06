"""5b QA tuzatishlari (H1, M1–M5, L1–L8, frontend so'ragan a–d) — haqiqiy PostgreSQL'da."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.domains.messaging.channels.base import ChannelSendError, SendResult
from app.domains.messaging.providers import from_state
from app.shared.events.registry import RetryLater
from app.workers.queue import RecordingQueue
from app.workers.runtime import WorkerRuntime
from tests.images import png
from tests.integration.helpers import World, _bearer, _code, _idem
from tests.integration.test_commerce import _admin_sql, _hdr, _ok, _post
from tests.integration.test_jobs_events import _drain_now, _job, _run
from tests.integration.test_messaging import (
    Chat,
    Inbox,
    _order_from_conversation,
    _outbox,
    _queued_reply,
    clean_outbox,  # noqa: F401 — autouse fixture
)
from tests.integration.test_storefront import Site

pytestmark = pytest.mark.integration

TEMPLATE_URL = "/api/v1/shop/message-templates/{key}/{locale}"


def _put_template(world: World, token: str, key: str, locale: str, body: str) -> Any:
    return world.client.put(
        TEMPLATE_URL.format(key=key, locale=locale), json={"body": body}, headers=_bearer(token)
    )


def _set_hours(world: World, token: str, hours: dict[str, Any] | None) -> Any:
    policy = _ok(world.client.get("/api/v1/shop/policies", headers=_bearer(token)))
    body = {k: v for k, v in policy.items() if k != "version"}
    body["inbox_hours"] = hours
    return world.client.patch("/api/v1/shop/policies", json=body, headers=_hdr(token, policy["version"]))


def _closed_hours() -> dict[str, Any]:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    hour = (datetime.now(UTC).astimezone(ZoneInfo("Asia/Tashkent")).hour + 2) % 24
    return {"days": [1, 2, 3, 4, 5, 6, 7], "start": f"{hour:02d}:00", "end": f"{(hour + 1) % 24:02d}:00"}


def _webchat_site(world: World) -> Site:
    site = Site(world)
    _ok(_post(world, site.owner, "/channels/webchat"), 201)
    return site


def _webchat_conversation(world: World, site: Site) -> dict[str, Any]:
    items = _ok(world.client.get("/api/v1/shop/conversations", headers=_bearer(site.owner)))["items"]
    return next(c for c in items if c["channel"] == "WEB_CHAT")


# ------------------------------------------------------------------ H1: shablon in'ektsiyasi
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("Yopiqmiz :} {hours}", "invalid_braces"),
        ("{0} {hours}", "invalid_placeholder"),
        ("{hours.__class__}", "invalid_placeholder"),
        ("{hours!r}", "invalid_placeholder"),
        ("{hours:>99999}", "invalid_placeholder"),
        ("{} soat", "invalid_placeholder"),
        ("{order_number}", "unknown_variables"),
    ],
)
def test_template_rejects_unsafe_placeholders(world: World, body: str, code: str) -> None:
    site = Site(world)
    response = _put_template(world, site.owner, "customer.handoff_after_hours", "uz", body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["fields"][0]["code"] == code


def test_broken_stored_template_never_loses_inbound_message(world: World) -> None:
    """Eski (tekshiruvsiz) saqlangan buzuq matn: kiruvchi xabar saqlanadi, xaridorga standart matn ketadi."""
    site = _webchat_site(world)
    _ok(_set_hours(world, site.owner, _closed_hours()))
    owner_membership = _admin_sql(
        world, "SELECT id FROM platform.memberships WHERE shop_id = $1 AND role = 'OWNER'", site.shop.id
    )[0]["id"]
    _admin_sql(
        world,
        "INSERT INTO platform.shop_message_templates "
        "(id, shop_id, template_key, locale, version, body, is_active, created_by) "
        "VALUES ($1, $2, 'customer.handoff_after_hours', 'uz', 1, 'Yopiqmiz :} {hours}', true, $3)",
        uuid4(),
        site.shop.id,
        owner_membership,
    )
    chat = Chat(site)
    sent = chat.send("Salom, kimdir bormi?")
    assert sent.status_code == 201, sent.text  # avval 500 edi — xabar yo'qolardi
    conversation = _webchat_conversation(world, site)
    messages = _ok(
        world.client.get(
            f"/api/v1/shop/conversations/{conversation['id']}/messages", headers=_bearer(site.owner)
        )
    )["items"]
    assert [m["body"] for m in messages if m["direction"] == "IN"] == ["Salom, kimdir bormi?"]
    notice = [m for m in messages if m["origin"] == "NOTIFICATION"]
    assert len(notice) == 1 and notice[0]["body"].startswith("Hozir ish vaqtidan tashqari")


def test_telegram_webhook_survives_broken_template(world: World) -> None:
    inbox = Inbox(world)
    _ok(_set_hours(world, inbox.owner, _closed_hours()))
    membership = _admin_sql(
        world, "SELECT id FROM platform.memberships WHERE shop_id = $1 AND role = 'OWNER'", inbox.shop.id
    )[0]["id"]
    _admin_sql(
        world,
        "INSERT INTO platform.shop_message_templates "
        "(id, shop_id, template_key, locale, version, body, is_active, created_by) "
        "VALUES ($1, $2, 'customer.handoff_after_hours', 'uz', 1, '{0} {hours}', true, $3)",
        uuid4(),
        inbox.shop.id,
        membership,
    )
    assert inbox.text().status_code == 200
    assert len(inbox.conversations()) == 1


# ------------------------------------------------------------------ M1: sayt chatida til
def test_webchat_visitor_locale_reaches_order_messages(world: World) -> None:
    site = _webchat_site(world)
    session = world.client.post(f"/api/v1/storefront/{site.slug}/chat/sessions").json()["token"]
    sent = world.client.post(
        f"/api/v1/storefront/{site.slug}/chat/messages",
        json={"client_message_id": uuid4().hex, "body": "Здравствуйте"},
        headers={"X-Chat-Session": session, "X-Customer-Locale": "ru"},
    )
    assert sent.status_code == 201
    contact = world.client.post(
        f"/api/v1/storefront/{site.slug}/chat/contact",
        json={"name": "Иван", "phone": "+998901110033", "consent": True},
        headers={"X-Chat-Session": session},
    )
    assert contact.status_code == 204
    conversation = _webchat_conversation(world, site)
    detail = _ok(
        world.client.get(f"/api/v1/shop/conversations/{conversation['id']}", headers=_bearer(site.owner))
    )
    assert detail["locale"] == "ru"
    inbox = Inbox.__new__(Inbox)  # faqat yordamchi metodlar uchun (Telegram ulanmaydi)
    inbox.world, inbox.shop = world, site.shop
    ref = _order_from_conversation(world, inbox, conversation["id"])
    order = site.shop.get(ref["id"])
    assert order["customer_locale"] == "ru"
    site.shop.step(order, "submit", "confirm")
    _drain_now(world)
    messages = _ok(
        world.client.get(
            f"/api/v1/shop/conversations/{conversation['id']}/messages", headers=_bearer(site.owner)
        )
    )["items"]
    notices = [m["body"] for m in messages if m["origin"] == "NOTIFICATION"]
    assert notices and notices[-1].startswith(f"Заказ #{order['number']} подтверждён")


# ------------------------------------------------------------------ M2: rasm mehmonga yetadi
def test_operator_image_reaches_webchat_visitor(world: World) -> None:
    site = _webchat_site(world)
    chat = Chat(site)
    _ok(chat.send("Rasm yuboring"), 201)
    conversation = _webchat_conversation(world, site)
    upload = world.client.post(
        "/api/v1/shop/files?purpose=CHAT_ATTACHMENT&filename=a.png",
        content=png(),
        headers=_bearer(site.owner, **_idem(), **{"Content-Type": "application/octet-stream"}),
    )
    file_id = _ok(upload, 201)["id"]
    reply = _post(
        world,
        site.owner,
        f"/conversations/{conversation['id']}/messages",
        {"attachment_file_id": file_id, "body": "Mana"},
    )
    assert reply.status_code == 201, reply.text
    items = _ok(chat.poll(after=1))["items"]
    image = next(m for m in items if m["kind"] == "IMAGE")
    assert image["body"] == "Mana" and image["image_url"] and "sig=" in image["image_url"]
    assert image["image_url_expires_at"] is not None


# ------------------------------------------------------------------ M3: buyurtmani qayta bog'lash
def test_linking_order_from_other_conversation_needs_explicit_relink(world: World) -> None:
    inbox = Inbox(world)
    inbox.text(user_id=7001)
    inbox.text(user_id=7002)
    c1, c2 = sorted(inbox.conversations(), key=lambda c: c["last_message_at"])
    ref = _order_from_conversation(world, inbox, c1["id"])
    moved = _post(world, inbox.owner, f"/conversations/{c2['id']}/orders/link", {"order_id": ref["id"]})
    assert moved.status_code == 409 and _code(moved) == "ORDER_LINKED_ELSEWHERE"
    order = inbox.shop.get(ref["id"])
    no_version = _post(
        world, inbox.owner, f"/conversations/{c2['id']}/orders/link", {"order_id": ref["id"], "relink": True}
    )
    assert no_version.status_code == 422
    relinked = _post(
        world,
        inbox.owner,
        f"/conversations/{c2['id']}/orders/link",
        {"order_id": ref["id"], "relink": True, "expected_version": order["version"]},
    )
    assert relinked.status_code == 200, relinked.text
    assert inbox.conversation(c2["id"])["last_order_id"] == ref["id"]
    assert inbox.conversation(c1["id"])["last_order_id"] is None  # eski suhbatda "oxirgi buyurtma" qolmadi
    missing_key = world.client.post(
        f"/api/v1/shop/conversations/{c2['id']}/orders/link",
        json={"order_id": ref["id"]},
        headers=_bearer(inbox.owner),
    )
    assert missing_key.status_code == 400  # Idempotency-Key majburiy


def test_orders_filter_by_exact_number(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    ref = _order_from_conversation(world, inbox, inbox.conversations()[0]["id"])
    found = _ok(world.client.get(f"/api/v1/shop/orders?number={ref['number']}", headers=_bearer(inbox.owner)))
    assert [o["id"] for o in found["items"]] == [ref["id"]]
    none = _ok(world.client.get("/api/v1/shop/orders?number=999999", headers=_bearer(inbox.owner)))
    assert none["items"] == []


# ------------------------------------------------------------------ M4: ish vaqti oralig'i
def test_inbox_hours_rejects_empty_window_and_normalises_days(world: World) -> None:
    site = Site(world)
    same = _set_hours(world, site.owner, {"days": [1, 2], "start": "09:00", "end": "09:00"})
    assert same.status_code == 422
    assert same.json()["error"]["details"]["fields"][0]["field"] == "inbox_hours.end"
    saved = _ok(_set_hours(world, site.owner, {"days": [3, 1, 1, 3], "start": "22:00", "end": "06:00"}))
    assert saved["inbox_hours"]["days"] == [1, 3]  # takrorlar olib tashlandi; tungi smena ruxsat


# ------------------------------------------------------------------ M5: osilib qolgan yuborish
def test_stuck_detection_uses_sending_start_and_late_success_is_sent(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    # Eski xabar, lekin hozirgina yuborilmoqda — UNKNOWN bo'lmaydi
    _admin_sql(
        world,
        "UPDATE messaging.messages SET delivery_status = 'SENDING', created_at = now() - interval '1 hour', "
        "sending_started_at = now() WHERE conversation_id = $1 AND direction = 'OUT'",
        UUID(conversation_id),
    )
    _job(world, "messaging_stuck_sending")
    assert inbox.messages(conversation_id)[-1]["delivery_status"] == "SENDING"
    # Rejali ish UNKNOWN qilgan, keyin kanal "qabul qildi" deb javob qaytardi — SENT
    _admin_sql(
        world,
        "UPDATE messaging.messages SET delivery_status = 'UNKNOWN', last_error_code = 'STUCK' "
        "WHERE conversation_id = $1 AND direction = 'OUT'",
        UUID(conversation_id),
    )
    message_id = UUID(inbox.messages(conversation_id)[-1]["id"])

    async def finish(rt: WorkerRuntime) -> None:
        async with rt.database.transaction(inbox.shop.id) as db:
            await from_state(rt.services).sending._sent(
                db, inbox.shop.id, message_id, SendResult(provider_message_id="42")
            )

    _run(world, RecordingQueue(), finish)
    assert inbox.messages(conversation_id)[-1]["delivery_status"] == "SENT"


# ------------------------------------------------------------------ L1: buzuq update
def test_webhook_ignores_malformed_update_fields(world: World) -> None:
    inbox = Inbox(world)
    for update in (
        {"update_id": 501, "callback_query": {"from": {"id": 9, "username": {"x": 1}}}},
        {"update_id": 502, "callback_query": {"from": {"id": 9, "username": 7}, "data": ["buy"]}},
        {
            "update_id": 503,
            "message": {
                "message_id": 1,
                "chat": {"id": 9, "type": "private"},
                "from": {"id": 9, "first_name": {"a": 1}},
                "photo": [{"file_id": "p", "file_size": "big"}],
            },
        },
    ):
        response = world.client.post(
            f"/api/v1/webhooks/telegram/{inbox.ref}",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": inbox.secret},
        )
        assert response.status_code == 200, response.text


# ------------------------------------------------------------------ L2: navbatdan olinganda signal
def test_take_marks_left_queue_for_operators(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    _ok(inbox.action(conversation_id, "take"))
    taken = [e for e in _outbox(world, inbox.shop.id) if e["type"] == "messaging.conversation.taken"]
    assert taken and taken[-1]["envelope"]["payload"]["left_queue"] is True


# ------------------------------------------------------------------ L4: sayt chatini qayta yoqish
def test_reenabled_webchat_keeps_old_conversations_working(world: World) -> None:
    site = _webchat_site(world)
    chat = Chat(site)
    _ok(chat.send("Salom"), 201)
    conversation = _webchat_conversation(world, site)
    channels = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(site.owner)))["items"]
    webchat = next(c for c in channels if c["channel"] == "WEB_CHAT" and c["status"] == "CONNECTED")
    _ok(_post(world, site.owner, f"/channels/{webchat['id']}/disconnect", None, webchat["version"]))
    _ok(_post(world, site.owner, "/channels/webchat"), 201)
    reply = _post(
        world, site.owner, f"/conversations/{conversation['id']}/messages", {"body": "Shu yerdaman"}
    )
    assert reply.status_code == 201, reply.text
    assert [m["body"] for m in _ok(chat.poll(after=1))["items"]] == ["Shu yerdaman"]


# ------------------------------------------------------------------ L5 va (b): mehmon kontakti
def test_contact_consent_stores_notice_version_and_signals_operator(world: World) -> None:
    site = _webchat_site(world)
    chat = Chat(site)
    _ok(chat.send("Salom"), 201)
    empty = world.client.post(
        f"/api/v1/storefront/{site.slug}/chat/contact",
        json={"consent": True},
        headers={"X-Chat-Session": chat.token},
    )
    assert empty.status_code == 422
    saved = world.client.post(
        f"/api/v1/storefront/{site.slug}/chat/contact",
        json={"name": "Aziz", "consent": True},
        headers={"X-Chat-Session": chat.token},
    )
    assert saved.status_code == 204
    row = _admin_sql(
        world,
        "SELECT notice_version FROM messaging.customer_identities "
        "WHERE shop_id = $1 AND display_name = 'Aziz'",
        site.shop.id,
    )[0]
    assert row["notice_version"]
    changed = [
        e for e in _outbox(world, site.shop.id) if e["type"] == "messaging.conversation.contact_updated"
    ]
    assert len(changed) == 1
    assert "Aziz" not in json.dumps(changed[0]["envelope"])  # event'da ism yo'q


# ------------------------------------------------------------------ L6/L7: ism va SYSTEM belgisi
def test_conversation_list_has_assignee_name_and_author_type(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    _ok(inbox.reply(conversation_id, "Salom"), 201)
    item = inbox.conversations()[0]
    assert item["assignee_name"] and item["last_message"]["author_type"] == "STAFF"
    assert inbox.conversation(conversation_id)["assignee_name"] == item["assignee_name"]


# ------------------------------------------------------------------ L8: bo'laklab yuborish davomi
def test_split_send_resumes_from_failed_part(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    long_text = ("Juda uzun javob. " * 300).strip()  # > 4096 — ikki bo'lak
    _ok(inbox.reply(conversation_id, long_text[:4000]), 201)  # operator chegarasi 4000
    _drain_now(world)
    inbox.fake.sent.clear()
    # Tizim matni uzun bo'lsa: birinchi bo'lak ketdi, ikkinchisida 429 — qayta urinish 2-bo'lakdan
    message_id = UUID(inbox.messages(conversation_id)[-1]["id"])
    _admin_sql(
        world,
        "UPDATE messaging.messages SET body = $2, delivery_status = 'QUEUED', parts_sent = 0 WHERE id = $1",
        message_id,
        long_text,
    )
    original = inbox.fake.send_message
    calls = {"n": 0}

    async def flaky(token: str, chat_id: int, text: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ChannelSendError("RATE_LIMITED", retryable=True, retry_after=1)
        return await original(token, chat_id, text)

    inbox.fake.send_message = flaky  # type: ignore[method-assign]

    async def send_twice(rt: WorkerRuntime) -> None:
        sending = from_state(rt.services).sending
        with pytest.raises(RetryLater):
            await sending.send(rt.database, inbox.shop.id, message_id)
        assert await sending.send(rt.database, inbox.shop.id, message_id) == "sent"

    _run(world, RecordingQueue(), send_twice)
    parts = [text for _, _, text in inbox.fake.sent]
    assert len(parts) == 2 and parts[0] != parts[1]  # birinchi bo'lak ikki marta ketmadi
    last = inbox.messages(conversation_id)[-1]
    assert last["delivery_status"] == "SENT"


# ------------------------------------------------------------------ (a) va (c)
def test_public_site_reports_chat_enabled(world: World) -> None:
    site = Site(world)
    assert world.client.get(f"/api/v1/storefront/{site.slug}/site").json()["chat_enabled"] is False
    _ok(_post(world, site.owner, "/channels/webchat"), 201)
    assert world.client.get(f"/api/v1/storefront/{site.slug}/site").json()["chat_enabled"] is True


def test_test_telegram_token_connects_fake_bot_in_test_env(world: World) -> None:
    site = Site(world)
    token = f"{900000000 + uuid4().int % 99999999}:TEST{uuid4().hex}"
    connected = _ok(_post(world, site.owner, "/channels/telegram", {"token": token}), 201)
    assert connected["status"] == "CONNECTED" and connected["is_fake"] is True
    assert connected["display_name"].startswith("@cos_test_")
