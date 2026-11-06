"""5b: kanallar, inbox, chiquvchi xabarlar, sayt chati, xaridorga buyurtma holati — haqiqiy PostgreSQL'da.

Tashqi tarmoq yo'q: Telegram — `FakeTelegramClient` (ilova adapteriga qo'yiladi), fon ishlari —
`RecordingQueue`
(test o'zi bajaradi, `_drain`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.domains.messaging.channels.base import ChannelSendError
from app.domains.messaging.channels.telegram import BotInfo, FakeTelegramClient
from app.shared.events.models import OUTBOX_SCHEMAS
from app.shared.events.registry import RetryLater
from app.workers.dispatch import deliver
from app.workers.outbox_worker import dispatch_pending
from app.workers.queue import RecordingQueue
from app.workers.runtime import WorkerRuntime
from tests.images import png
from tests.integration.helpers import World, _bearer, _code, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _hdr, _ok, _post
from tests.integration.test_jobs_events import _drain_now, _job, _run
from tests.integration.test_storefront import Site

pytestmark = pytest.mark.integration

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
BOT = BotInfo(id=777001, username="techpc_test_bot")


def _bot() -> tuple[str, BotInfo]:
    """Har testga alohida bot: bitta bot bir vaqtda faqat bitta shopda (baza testlar orasida umumiy)."""
    bot_id = int(uuid4().int % 10**9) + 10**9
    return f"{bot_id}:AAH{uuid4().hex}", BotInfo(id=bot_id, username=f"bot{bot_id}")


@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> Iterator[None]:
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )
    yield


class Inbox:
    """Shop + ulangan Telegram bot (soxta klient) + webhook manzili va siri."""

    def __init__(self, world: World, shop: Shop | None = None) -> None:
        self.world = world
        self.shop = shop or Shop(world)
        self.token, bot = _bot()
        self.fake = FakeTelegramClient(bots={self.token: bot})
        world.client.app.state.messaging.adapters.telegram = self.fake
        self.account = _ok(_post(world, self.shop.owner, "/channels/telegram", {"token": self.token}), 201)
        url, secret = self.fake.webhooks[self.token]  # type: ignore[misc]
        self.ref, self.secret = url.rsplit("/", 1)[1], secret
        self._update = 1000

    @property
    def owner(self) -> str:
        return self.shop.owner

    def send(
        self, message: dict[str, Any], *, user_id: int = 5001, update_id: int | None = None, **top: Any
    ) -> Any:
        if update_id is None:
            self._update += 1
            update_id = self._update
        base = {
            "message_id": update_id,
            "date": 1_790_000_000,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Jasur", "language_code": "uz"},
        }
        update = {"update_id": update_id, "message": {**base, **message}, **top}
        return self.world.client.post(
            f"/api/v1/webhooks/telegram/{self.ref}",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": self.secret},
        )

    def text(self, text: str = "RTX 4060 bormi?", **kwargs: Any) -> Any:
        return self.send({"text": text}, **kwargs)

    def conversations(self, token: str | None = None, **params: str) -> list[dict[str, Any]]:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return list(
            _ok(
                self.world.client.get(
                    f"/api/v1/shop/conversations?{query}", headers=_bearer(token or self.owner)
                )
            )["items"]
        )

    def conversation(self, conversation_id: str, token: str | None = None) -> dict[str, Any]:
        return _ok(
            self.world.client.get(
                f"/api/v1/shop/conversations/{conversation_id}", headers=_bearer(token or self.owner)
            )
        )

    def messages(self, conversation_id: str, token: str | None = None) -> list[dict[str, Any]]:
        return list(
            _ok(
                self.world.client.get(
                    f"/api/v1/shop/conversations/{conversation_id}/messages",
                    headers=_bearer(token or self.owner),
                )
            )["items"]
        )

    def reply(
        self, conversation_id: str, body: str = "Ha, bor!", token: str | None = None, key: str | None = None
    ) -> Any:
        headers = _bearer(token or self.owner, **({"Idempotency-Key": key} if key else _idem()))
        return self.world.client.post(
            f"/api/v1/shop/conversations/{conversation_id}/messages", json={"body": body}, headers=headers
        )

    def action(self, conversation_id: str, name: str, token: str | None = None, body: Any = None) -> Any:
        version = self.conversation(conversation_id, token)["version"]
        return _post(
            self.world, token or self.owner, f"/conversations/{conversation_id}/{name}", body, version
        )


def _drain_retrying(world: World, max_attempts: int = 8) -> list[str]:
    """Outbox → vazifalar; `RetryLater` bo'lsa arq kabi qayta urinadi (kutmasdan). Natijalar ro'yxati."""
    results: list[str] = []

    async def go(rt: WorkerRuntime) -> None:
        queue: RecordingQueue = rt.queue  # type: ignore[assignment]
        for _ in range(10):
            seen = await dispatch_pending(rt)
            jobs = queue.take()
            for function, job_id, kwargs in jobs:
                if function == "dispatch_event":
                    for attempt in range(1, max_attempts + 1):
                        try:
                            results.append(
                                await deliver(
                                    rt,
                                    kwargs["schema"],
                                    UUID(kwargs["event_id"]),
                                    kwargs["consumer"],
                                    attempt,
                                )
                            )
                            break
                        except RetryLater:
                            results.append("retry")
                queue.forget(job_id)
            if not seen and not jobs:
                return

    _run(world, RecordingQueue(), go)
    return results


def _tasks(world: World, token: str, **params: str) -> list[dict[str, Any]]:
    query = "&".join(f"{k}={v}" for k, v in {"status": "OPEN", **params}.items())
    return list(_ok(world.client.get(f"/api/v1/shop/tasks?{query}", headers=_bearer(token)))["items"])


def _outbox(world: World, shop_id: UUID) -> list[dict[str, Any]]:
    rows = _admin_sql(
        world,
        "SELECT event_type, envelope FROM messaging.outbox_events WHERE shop_id = $1 ORDER BY created_at",
        shop_id,
    )
    return [{"type": r["event_type"], "envelope": json.loads(r["envelope"])} for r in rows]


# ------------------------------------------------------------------ kanal ulash
def test_owner_connects_telegram_token_is_encrypted_and_never_returned(world: World) -> None:
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    token, bot = _bot()
    fake = FakeTelegramClient(bots={token: bot})
    world.client.app.state.messaging.adapters.telegram = fake
    denied = _post(world, manager, "/channels/telegram", {"token": token})
    assert denied.status_code == 403  # faqat ega kanal ulaydi (UAT-M09)
    bad = _post(world, shop.owner, "/channels/telegram", {"token": "123456789:" + "x" * 35})
    assert bad.status_code == 422 and bad.json()["error"]["details"]["fields"][0]["field"] == "token"
    created = _post(world, shop.owner, "/channels/telegram", {"token": token})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "CONNECTED" and body["display_name"] == f"@{bot.username}"
    assert token not in created.text and "token" not in body
    assert created.headers["Location"].endswith(f"/channels/{body['id']}")
    url, secret = fake.webhooks[token]  # type: ignore[misc]
    row = _admin_sql(
        world,
        "SELECT token_enc, webhook_secret_hash, account_ref FROM messaging.channel_accounts WHERE id = $1",
        UUID(body["id"]),
    )[0]
    assert row["token_enc"].startswith("v1.") and token not in row["token_enc"]  # shifrlangan (11-qaror)
    assert url.endswith(f"/api/v1/webhooks/telegram/{row['account_ref']}") and len(row["account_ref"]) >= 32
    assert secret not in (row["webhook_secret_hash"] or "") and len(row["webhook_secret_hash"]) == 64
    listed = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(manager)))
    assert listed["telegram_mode"] == "webhook" and listed["items"][0]["id"] == body["id"]
    audit = _admin_sql(
        world, "SELECT diff::text AS diff FROM audit.audit_entries WHERE entity_id = $1", UUID(body["id"])
    )
    assert audit and all(token not in (r["diff"] or "") for r in audit)


# ------------------------------------------------------------------ webhook
def test_webhook_checks_secret_dedups_and_ignores_groups(world: World) -> None:
    inbox = Inbox(world)
    wrong = world.client.post(
        f"/api/v1/webhooks/telegram/{inbox.ref}",
        json={"update_id": 1, "message": {"text": "x"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert wrong.status_code == 404
    unknown = world.client.post(
        f"/api/v1/webhooks/telegram/{'z' * 43}",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": inbox.secret},
    )
    assert unknown.status_code == 404
    assert inbox.text(update_id=5).status_code == 200
    assert inbox.text(update_id=5).status_code == 200  # Telegram qayta yubordi (TC-010)
    [conversation] = inbox.conversations()
    assert len(inbox.messages(conversation["id"])) == 1
    group = inbox.send({"text": "guruh", "chat": {"id": -100, "type": "group"}}, update_id=6)
    assert group.status_code == 200
    assert len(inbox.messages(conversation["id"])) == 1
    status = _admin_sql(
        world, "SELECT status, error_code FROM messaging.provider_events WHERE provider_event_id = '6'"
    )
    assert status[0]["status"] == "IGNORED" and status[0]["error_code"] == "GROUP_CHAT"


def test_first_message_goes_to_operator_queue_with_task_and_notification(world: World) -> None:
    inbox = Inbox(world)
    sales, _ = inbox.shop.staff("SALES")
    inbox.text("Assalomu alaykum, RTX 4060 bormi?")
    [conversation] = inbox.conversations(sales)
    assert conversation["status"] == "HUMAN_NEEDED" and conversation["speaker_mode"] == "PAUSED"
    assert conversation["unread_count"] == 1 and conversation["customer_name"] == "Jasur"
    detail = inbox.conversation(conversation["id"], sales)
    assert detail["open_handoff"]["reason"] == "AI_UNAVAILABLE"
    assert {"TAKE", "REPLY"} <= set(detail["allowed_actions"])
    [task] = _tasks(world, sales, type="HANDOFF")
    assert task["link"] == {"route": "conversation", "id": conversation["id"]}
    feed = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(sales)))
    assert any(n["template_key"] == "staff.handoff" for n in feed["items"])
    counts = _ok(world.client.get("/api/v1/shop/conversations/counts", headers=_bearer(sales)))
    assert counts["human_needed"] == 1 and counts["unassigned"] == 1 and counts["unread"] == 1


def test_operator_reply_takes_conversation_and_is_sent_by_worker(world: World) -> None:
    inbox = Inbox(world)
    sales, sales_id = inbox.shop.staff("SALES")
    inbox.text()
    [conversation] = inbox.conversations(sales)
    sent = inbox.reply(conversation["id"], "Ha, Chilonzorda bor.", token=sales)
    assert sent.status_code == 201, sent.text
    assert sent.json()["delivery_status"] == "QUEUED" and sent.json()["author_type"] == "STAFF"
    detail = inbox.conversation(conversation["id"], sales)
    assert detail["status"] == "WAITING_CUSTOMER" and detail["speaker_mode"] == "HUMAN"
    assert detail["assignee_membership_id"] == sales_id and detail["open_handoff"] is None
    assert detail["unread_count"] == 0  # javob yozgan — o'qigan
    assert _tasks(world, sales, type="HANDOFF") == []  # vazifa yopildi
    _drain_now(world)
    assert inbox.fake.sent == [(inbox.token, 5001, "Ha, Chilonzorda bor.")]
    last = inbox.messages(conversation["id"])[-1]
    assert last["delivery_status"] == "SENT" and last["attempts"] == 1
    inbox.text("Rahmat, ertaga kelaman")
    assert inbox.conversation(conversation["id"], sales)["status"] == "HUMAN_ACTIVE"


def test_reply_is_idempotent(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    [conversation] = inbox.conversations()
    key = f"k-{uuid4()}"
    first = inbox.reply(conversation["id"], "Bor", key=key)
    again = inbox.reply(conversation["id"], "Bor", key=key)
    assert first.status_code == 201 and again.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    other = inbox.reply(conversation["id"], "Boshqa matn", key=key)
    assert other.status_code == 409 and _code(other) == "IDEMPOTENCY_KEY_REUSED"
    assert len([m for m in inbox.messages(conversation["id"]) if m["direction"] == "OUT"]) == 1


# ------------------------------------------------------------------ yuborish natijalari (TC-011)
def _queued_reply(world: World, inbox: Inbox, text: str = "Javob") -> str:
    inbox.text()
    conversation = inbox.conversations()[0]
    _ok(inbox.reply(conversation["id"], text), 201)
    return str(conversation["id"])


def test_rate_limited_send_is_retried_then_sent(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    inbox.fake.send_errors = [ChannelSendError("RATE_LIMITED", retryable=True, retry_after=3)]
    results = _drain_retrying(world)
    assert "retry" in results
    last = inbox.messages(conversation_id)[-1]
    assert last["delivery_status"] == "SENT" and last["attempts"] == 2
    assert len(inbox.fake.sent) == 1


def test_send_fails_after_five_attempts_and_staff_gets_task(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    inbox.fake.send_errors = [ChannelSendError("HTTP_502", retryable=True) for _ in range(6)]
    _drain_retrying(world)
    last = inbox.messages(conversation_id)[-1]
    assert (
        last["delivery_status"] == "FAILED"
        and last["attempts"] == 5
        and last["last_error_code"] == "HTTP_502"
    )
    [task] = _tasks(world, inbox.owner, type="MESSAGE_FAILED")
    assert task["link"] == {"route": "conversation", "id": conversation_id}
    feed = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(inbox.owner)))
    assert any(n["template_key"] == "staff.message_failed" for n in feed["items"])


def test_timeout_after_send_is_unknown_and_not_resent(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    inbox.fake.send_errors = [ChannelSendError("TIMEOUT", unknown=True)]
    _drain_retrying(world)
    last = inbox.messages(conversation_id)[-1]
    assert last["delivery_status"] == "UNKNOWN" and last["attempts"] == 1
    assert inbox.fake.sent == []  # ko'r-ko'rona qayta yuborilmaydi (06 §4.2)


def test_blocked_customer_marks_failed_and_channel_unavailable(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    inbox.fake.send_errors = [ChannelSendError("BLOCKED")]
    _drain_retrying(world)
    detail = inbox.conversation(conversation_id)
    assert detail["customer"]["blocked"] is True and detail["channel_available"] is False
    refused = inbox.reply(conversation_id, "Yana")
    assert refused.status_code == 409 and _code(refused) == "CHANNEL_UNAVAILABLE"
    inbox.text("Kechirasiz, bloklab qo'ygan ekanman")  # yozdi — demak bloklamagan
    assert inbox.conversation(conversation_id)["customer"]["blocked"] is False


# ------------------------------------------------------------------ FSM-04
def test_resolve_reopen_and_customer_reopens(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    resolved = _ok(inbox.action(conversation_id, "resolve"))
    assert resolved["status"] == "RESOLVED" and "REOPEN" in resolved["allowed_actions"]
    again = inbox.action(conversation_id, "resolve")
    assert again.status_code == 409 and _code(again) == "INVALID_STATE_TRANSITION"
    inbox.text("Yana savolim bor")
    detail = inbox.conversation(conversation_id)
    assert detail["status"] == "HUMAN_NEEDED" and detail["open_handoff"] is not None
    _ok(inbox.action(conversation_id, "resolve"))
    reopened = _ok(inbox.action(conversation_id, "reopen"))
    assert reopened["status"] == "REOPENED"
    history = _admin_sql(
        world,
        "SELECT command FROM platform.transition_log WHERE entity_id = $1 ORDER BY occurred_at, id",
        UUID(conversation_id),
    )
    commands = [r["command"] for r in history]
    assert commands[:2] == ["FIRST_MESSAGE", "REQUEST_HUMAN"]
    assert "CUSTOMER_REPLIED" in commands and commands[-1] == "REOPEN"


def test_reply_to_resolved_conversation_reopens_and_takes_it(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    _ok(inbox.action(conversation_id, "resolve"))
    _ok(inbox.reply(conversation_id, "Buyurtmangiz tayyor"), 201)
    detail = inbox.conversation(conversation_id)
    assert detail["status"] == "WAITING_CUSTOMER" and detail["speaker_mode"] == "HUMAN"


def test_fencing_drops_ai_reply_after_operator_takes_over(world: World) -> None:  # TC-009
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    _admin_sql(
        world,
        "UPDATE messaging.conversations SET status = 'AI_ACTIVE', speaker_mode = 'AI' WHERE id = $1",
        UUID(conversation_id),
    )
    version = inbox.conversation(conversation_id)["speaker_version"]
    services = world.client.app.state.messaging
    shop_id = inbox.shop.id

    async def queue_ai(rt: WorkerRuntime) -> str:
        async with rt.database.transaction(shop_id) as db:
            message = await services.ai.queue(
                db,
                shop_id,
                UUID(conversation_id),
                speaker_version=version,
                body="AI: bor",
                ai_reply_id=uuid4(),
            )
            return str(message.delivery_status)

    assert _run(world, RecordingQueue(), queue_ai) == "QUEUED"
    # AI javobi navbatda turganida operator suhbatni oldi → speaker +1
    _admin_sql(
        world, "UPDATE messaging.conversations SET status = 'AI_ACTIVE' WHERE id = $1", UUID(conversation_id)
    )
    taken = _ok(inbox.action(conversation_id, "take"))
    assert taken["speaker_mode"] == "HUMAN" and taken["speaker_version"] == version + 1
    _drain_now(world)
    assert inbox.fake.sent == []  # AI javobi xaridorga ketmadi
    statuses = [m["delivery_status"] for m in inbox.messages(conversation_id) if m["author_type"] == "AI"]
    assert statuses == ["DISCARDED"]
    # Eski versiya bilan kelgan yangi AI javobi — darhol DISCARDED
    assert _run(world, RecordingQueue(), queue_ai) == "DISCARDED"


# ------------------------------------------------------------------ kiruvchi turlar
def test_contact_photo_and_edit_are_mapped(world: World) -> None:
    inbox = Inbox(world)
    inbox.send({"text": "Salom", "message_id": 77})
    conversation_id = inbox.conversations()[0]["id"]
    # Boshqaning raqami yozilmaydi, o'ziniki — shifrlangan holda xaridor yozuviga
    inbox.send({"contact": {"phone_number": "+998901112299", "user_id": 999}})
    assert inbox.conversation(conversation_id)["customer"]["phone"] is None
    inbox.send({"contact": {"phone_number": "998901112233", "user_id": 5001}})
    customer = inbox.conversation(conversation_id)["customer"]
    assert customer["phone"] == "+998901112233" and customer["phone_masked"] == "+99890 *** ** 33"
    raw = _admin_sql(
        world,
        "SELECT phone_enc, phone_hmac FROM messaging.customer_identities WHERE id = $1",
        UUID(customer["id"]),
    )[0]
    assert raw["phone_enc"].startswith("v1.") and "901112233" not in raw["phone_enc"] and raw["phone_hmac"]
    contact_message = [m for m in inbox.messages(conversation_id) if m["kind"] == "CONTACT"][-1]
    assert contact_message["body"] is None  # raqam matnga yozilmaydi
    found = inbox.conversations(q="+998 90 111 22 33")
    assert [c["id"] for c in found] == [conversation_id]
    # Rasm: webhook ichida yuklanmaydi — PENDING, keyin fon vazifasi yopiq omborga
    inbox.fake.files["photo-big"] = (png(), "image/png")
    inbox.send(
        {
            "photo": [
                {"file_id": "photo-small", "file_size": 10},
                {"file_id": "photo-big", "file_size": 999},
            ],
            "caption": "Shu kerak",
        }
    )
    photo = inbox.messages(conversation_id)[-1]
    assert (
        photo["kind"] == "IMAGE"
        and photo["body"] == "Shu kerak"
        and photo["attachments"][0]["status"] == "PENDING"
    )
    _drain_now(world)
    photo = inbox.messages(conversation_id)[-1]
    attachment = photo["attachments"][0]
    assert attachment["status"] == "STORED" and "sig=" in attachment["url"]  # yopiq — imzoli havola
    # Ovoz — saqlanmaydi (Stage 1), operator Telegram'da ochadi
    inbox.send({"voice": {"file_id": "voice-1", "duration": 5, "mime_type": "audio/ogg"}})
    _drain_now(world)
    voice = inbox.messages(conversation_id)[-1]
    assert voice["kind"] == "VOICE" and voice["attachments"][0]["status"] == "FAILED"
    # Tahrir — matn yangilanadi
    edit = {
        "update_id": 9999,
        "edited_message": {
            "message_id": 77,
            "date": 1_790_000_100,
            "edit_date": 1_790_000_200,
            "chat": {"id": 5001, "type": "private"},
            "from": {"id": 5001, "is_bot": False, "first_name": "Jasur"},
            "text": "Salom (tahrirlandi)",
        },
    }
    world.client.post(
        f"/api/v1/webhooks/telegram/{inbox.ref}",
        json=edit,
        headers={"X-Telegram-Bot-Api-Secret-Token": inbox.secret},
    )
    first = inbox.messages(conversation_id)[0]
    assert first["body"] == "Salom (tahrirlandi)" and first["edited_at"] is not None


def test_operator_request_command_sets_handoff_reason(world: World) -> None:
    inbox = Inbox(world)
    inbox.text("/operator")
    conversation_id = inbox.conversations()[0]["id"]
    assert inbox.conversation(conversation_id)["open_handoff"]["reason"] == "CUSTOMER_REQUEST"
    assert inbox.messages(conversation_id)[0]["intent_hint"] == "OPERATOR_REQUEST"


# ------------------------------------------------------------------ ruxsatlar va doira
def test_operator_scope_assign_and_warehouse_denied(world: World) -> None:
    inbox = Inbox(world)
    sales_a, sales_a_id = inbox.shop.staff("SALES")
    sales_b, _ = inbox.shop.staff("SALES")
    warehouse, warehouse_id = inbox.shop.staff("WAREHOUSE")
    manager, _ = inbox.shop.staff("MANAGER")
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    assert world.client.get("/api/v1/shop/conversations", headers=_bearer(warehouse)).status_code == 403
    # Biriktirilmagan — ikkala operator ham ko'radi; A olgandan keyin B ko'rmaydi
    assert len(inbox.conversations(sales_b)) == 1
    _ok(inbox.action(conversation_id, "take", sales_a))
    assert inbox.conversations(sales_b) == []
    hidden = world.client.get(f"/api/v1/shop/conversations/{conversation_id}", headers=_bearer(sales_b))
    assert hidden.status_code == 403 and hidden.json()["error"]["details"]["reason"] == "other_operator"
    assert inbox.reply(conversation_id, "Men ham", token=sales_b).status_code == 403
    assert (
        world.client.get(
            f"/api/v1/shop/conversations/{conversation_id}/messages", headers=_bearer(sales_b)
        ).status_code
        == 403
    )
    # Operator biriktira olmaydi; menejer biriktiradi; omborchiga — 422
    assert inbox.action(conversation_id, "assign", sales_a, {"membership_id": sales_a_id}).status_code == 403
    wrong = inbox.action(conversation_id, "assign", manager, {"membership_id": warehouse_id})
    assert (
        wrong.status_code == 422 and wrong.json()["error"]["details"]["fields"][0]["field"] == "membership_id"
    )
    moved = _ok(
        inbox.action(conversation_id, "assign", manager, {"membership_id": _member_id(inbox, sales_b)})
    )
    assert moved["assignee_membership_id"] != sales_a_id
    assert len(inbox.conversations(sales_b)) == 1 and inbox.conversations(sales_a) == []
    assert len(inbox.conversations(manager)) == 1  # menejer hammasini ko'radi


def _member_id(inbox: Inbox, token: str) -> str:
    me = _ok(inbox.world.client.get("/api/v1/auth/me", headers=_bearer(token)))
    return str(me["membership_id"])


def test_shops_cannot_see_each_others_conversations(world: World) -> None:
    a, b = Inbox(world), Inbox(world)
    a.text("A shop xaridori")
    conversation_id = a.conversations()[0]["id"]
    assert b.conversations() == []
    for path in ("", "/messages", "/notes", "/orders"):
        response = world.client.get(
            f"/api/v1/shop/conversations/{conversation_id}{path}", headers=_bearer(b.owner)
        )
        assert response.status_code == 404, path
    assert b.reply(conversation_id).status_code == 404
    other_channel = world.client.get(f"/api/v1/shop/channels/{a.account['id']}", headers=_bearer(b.owner))
    assert other_channel.status_code == 404
    # B shop webhook'iga A shop xaridorining update'i — A suhbatiga tushmaydi
    b.text("B ga yozdi", user_id=5001)
    assert len(a.messages(conversation_id)) == 1


def test_notes_tags_and_read(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    inbox.text("ikkinchi")
    conversation_id = inbox.conversations()[0]["id"]
    note = _ok(
        _post(world, inbox.owner, f"/conversations/{conversation_id}/notes", {"body": "Ertaga qo'ng'iroq"}),
        201,
    )
    notes = _ok(
        world.client.get(f"/api/v1/shop/conversations/{conversation_id}/notes", headers=_bearer(inbox.owner))
    )
    assert [n["id"] for n in notes["items"]] == [note["id"]]
    detail = inbox.conversation(conversation_id)
    tagged = world.client.put(
        f"/api/v1/shop/conversations/{conversation_id}/tags",
        json={"tags": ["PC yig'ma", "ulgurji", "PC yig'ma"]},
        headers=_hdr(inbox.owner, detail["version"]),
    )
    assert _ok(tagged)["tags"] == ["PC yig'ma", "ulgurji"]
    assert [c["id"] for c in inbox.conversations(tag="ulgurji")] == [conversation_id]
    assert inbox.conversation(conversation_id)["unread_count"] == 2
    read = _ok(_post(world, inbox.owner, f"/conversations/{conversation_id}/read", {"seq": 1}))
    assert read["unread_count"] == 1
    _ok(_post(world, inbox.owner, f"/conversations/{conversation_id}/read", {"seq": 999}))
    assert inbox.conversations(unread="true") == []


# ------------------------------------------------------------------ Instagram flag (DEC-116a)
def test_instagram_is_hidden_when_flag_is_off(world: World) -> None:
    shop = Shop(world)
    assert _post(world, shop.owner, "/channels/instagram", {"access_token": "x" * 30}).status_code == 404
    verify = world.client.get(
        "/api/v1/webhooks/instagram?hub.mode=subscribe&hub.verify_token=abc&hub.challenge=123"
    )
    assert verify.status_code == 404
    assert world.client.post("/api/v1/webhooks/instagram", json={"entry": []}).status_code == 404
    assert (
        _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(shop.owner)))["instagram_available"]
        is False
    )


# ------------------------------------------------------------------ sayt chati (anonim)
class Chat:
    def __init__(self, site: Site) -> None:
        self.site = site
        self.world = site.world
        response = self.world.client.post(f"/api/v1/storefront/{site.slug}/chat/sessions")
        assert response.status_code == 201, response.text
        self.token = str(response.json()["token"])

    def send(
        self, body: str, client_id: str | None = None, token: str | None = None, slug: str | None = None
    ) -> Any:
        return self.world.client.post(
            f"/api/v1/storefront/{slug or self.site.slug}/chat/messages",
            json={"client_message_id": client_id or uuid4().hex, "body": body},
            headers={"X-Chat-Session": token or self.token},
        )

    def poll(self, after: int = 0, token: str | None = None, slug: str | None = None) -> Any:
        return self.world.client.get(
            f"/api/v1/storefront/{slug or self.site.slug}/chat/messages?after_seq={after}",
            headers={"X-Chat-Session": token or self.token},
        )


def test_webchat_sessions_are_isolated_and_operator_reply_reaches_visitor(world: World) -> None:
    site = Site(world)
    disabled = world.client.post(f"/api/v1/storefront/{site.slug}/chat/sessions")
    assert disabled.status_code == 409 and _code(disabled) == "CHANNEL_UNAVAILABLE"  # sayt chati yoqilmagan
    _ok(_post(world, site.owner, "/channels/webchat"), 201)
    a, b = Chat(site), Chat(site)
    sent = a.send("Salom, noutbuk kerak", client_id="client-0001")
    assert sent.status_code == 201 and sent.json() == {"seq": 1, "duplicate": False}
    duplicate = a.send("Salom, noutbuk kerak", client_id="client-0001")  # tarmoq uzilib qayta yuborildi
    assert duplicate.json() == {"seq": 1, "duplicate": True}
    assert _ok(b.poll())["items"] == []  # boshqa mehmon ko'rmaydi
    polled = _ok(a.poll())
    assert [m["body"] for m in polled["items"]] == ["Salom, noutbuk kerak"]
    assert polled["state"] == "WAITING_OPERATOR"
    # Operator inbox'da ko'radi va javob beradi — sayt chatida tashqi yuborish yo'q, darhol SENT
    [conversation] = [c for c in Inbox_list(world, site.owner) if c["channel"] == "WEB_CHAT"]
    reply = _post(
        world, site.owner, f"/conversations/{conversation['id']}/messages", {"body": "Qaysi narxda?"}
    )
    assert reply.status_code == 201 and reply.json()["delivery_status"] == "SENT"
    after = _ok(a.poll(after=1))
    assert [(m["author"], m["body"]) for m in after["items"]] == [("operator", "Qaysi narxda?")]
    assert after["state"] == "OPERATOR" and after["last_seq"] == 2
    # Boshqa shop slug'i bilan shu token — 404 (TC-CH-06); noto'g'ri token — 404
    other = Site(world)
    _ok(_post(world, other.owner, "/channels/webchat"), 201)
    assert a.poll(slug=other.slug).status_code == 404
    assert a.poll(token="x" * 43).status_code == 404
    # Ism va telefon (rozilik bilan) — shifrlangan, operator kartochkada ko'radi
    saved = world.client.post(
        f"/api/v1/storefront/{site.slug}/chat/contact",
        json={"name": "Jasur", "phone": "+998 90 123 45 67", "consent": True},
        headers={"X-Chat-Session": a.token},
    )
    assert saved.status_code == 204
    customer = _ok(
        world.client.get(f"/api/v1/shop/conversations/{conversation['id']}", headers=_bearer(site.owner))
    )["customer"]
    assert customer["display_name"] == "Jasur" and customer["phone"] == "+998901234567"


def Inbox_list(world: World, token: str) -> list[dict[str, Any]]:
    return list(_ok(world.client.get("/api/v1/shop/conversations", headers=_bearer(token)))["items"])


def test_webchat_needs_live_site_and_is_rate_limited(world: World) -> None:
    hidden = Site(world, live=False)
    _ok(_post(world, hidden.owner, "/channels/webchat"), 201)
    closed = world.client.post(f"/api/v1/storefront/{hidden.slug}/chat/sessions")
    assert closed.status_code == 409 and _code(closed) == "SITE_NOT_AVAILABLE"
    site = Site(world)
    _ok(_post(world, site.owner, "/channels/webchat"), 201)
    chat = Chat(site)
    codes = [chat.send(f"xabar {i}").status_code for i in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429  # sessiya bo'yicha daqiqasiga 10 ta


# ------------------------------------------------------------------ xaridorga buyurtma holati (S4-06)
def _order_from_conversation(world: World, inbox: Inbox, conversation_id: str) -> dict[str, Any]:
    sku = inbox.shop.sku()
    inbox.shop.receive(sku, 3)
    ref = _ok(
        _post(
            world, inbox.owner, f"/conversations/{conversation_id}/orders", {"branch_id": inbox.shop.branch}
        ),
        201,
    )
    _ok(
        _post(
            world,
            inbox.owner,
            f"/orders/{ref['id']}/lines",
            {"sku_id": sku, "qty": 1},
            inbox.shop.get(ref["id"])["version"],
        ),
        201,
    )
    return ref


def test_order_status_messages_go_to_conversation_once_in_customer_locale(world: World) -> None:
    inbox = Inbox(world)
    inbox.send(
        {
            "text": "Здравствуйте",
            "from": {"id": 5001, "is_bot": False, "first_name": "Иван", "language_code": "ru"},
        }
    )
    conversation_id = inbox.conversations()[0]["id"]
    _ok(inbox.reply(conversation_id, "Добрый день"), 201)
    ivan = {"id": 5001, "is_bot": False, "first_name": "Иван", "language_code": "ru"}
    inbox.send(
        {"contact": {"phone_number": "+998901110022", "user_id": 5001}, "from": ivan}
    )  # buyurtmaga ham
    ref = _order_from_conversation(world, inbox, conversation_id)
    order = inbox.shop.get(ref["id"])
    assert order["customer_name"] == "Иван" and order["customer_locale"] == "ru"
    assert order["customer_phone"] == "+998901110022"
    assert inbox.conversation(conversation_id)["last_order_id"] == ref["id"]
    # Shop o'zgartirgan ruscha matn (majburiy {order_number} bilan)
    bad = world.client.put(
        "/api/v1/shop/message-templates/customer.order_confirmed/ru",
        json={"body": "Заказ подтверждён"},
        headers=_bearer(inbox.owner),
    )
    assert (
        bad.status_code == 422 and bad.json()["error"]["details"]["fields"][0]["code"] == "missing_variables"
    )
    _ok(
        world.client.put(
            "/api/v1/shop/message-templates/customer.order_confirmed/ru",
            json={"body": "TechPC: заказ #{order_number} подтверждён, сумма {total}."},
            headers=_bearer(inbox.owner),
        )
    )
    inbox.shop.step(order, "submit", "confirm")
    _drain_now(world)
    notices = [m for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]
    assert len(notices) == 1
    assert notices[0]["body"] == f"TechPC: заказ #{order['number']} подтверждён, сумма 4 800 000 сум."
    assert notices[0]["delivery_status"] == "SENT"
    # Event qayta yetkazilsa ham ikkinchi xabar yo'q (consumer_receipts + intent_key)
    _admin_sql(
        world, "DELETE FROM messaging.consumer_receipts WHERE consumer = 'messaging.order_status_notify'"
    )
    _admin_sql(
        world,
        "UPDATE commerce.outbox_events SET status = 'PENDING' "
        "WHERE shop_id = $1 AND event_type = 'commerce.order.confirmed'",
        inbox.shop.id,
    )
    _drain_now(world)
    assert len([m for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]) == 1
    # Tayyor (olib ketish) va topshirildi — standart matnlar, ruscha
    current = inbox.shop.get(ref["id"])
    current = inbox.shop.step(current, "start-processing", "mark-ready", "complete")
    _drain_now(world)
    bodies = [m["body"] for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]
    assert len(bodies) == 3 and bodies[1].startswith(f"Заказ #{order['number']} готов")
    assert bodies[2] == "Спасибо за покупку! Если будут вопросы, пишите сюда."


def test_storefront_order_without_conversation_gets_no_message_and_link_works(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    sku = inbox.shop.sku()
    inbox.shop.receive(sku, 2)
    plain = inbox.shop.order({sku: 1})
    plain = inbox.shop.step(plain, "submit", "confirm")
    _drain_now(world)
    assert [m for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"] == []
    linked = _ok(
        _post(world, inbox.owner, f"/conversations/{conversation_id}/orders/link", {"order_id": plain["id"]})
    )
    assert linked["number"] == plain["number"]
    orders = _ok(
        world.client.get(f"/api/v1/shop/conversations/{conversation_id}/orders", headers=_bearer(inbox.owner))
    )
    assert [o["id"] for o in orders["items"]] == [plain["id"]]
    # Bog'langandan keyingi o'tish — xabar suhbatga ketadi
    inbox.shop.step(inbox.shop.get(plain["id"]), "start-processing", "mark-ready")
    _drain_now(world)
    notices = [m for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]
    assert len(notices) == 1 and f"#{plain['number']}" in (notices[0]["body"] or "")


def test_message_templates_owner_edits_manager_views(world: World) -> None:
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    listed = _ok(world.client.get("/api/v1/shop/message-templates", headers=_bearer(manager)))
    keys = {(t["template_key"], t["locale"]) for t in listed["items"]}
    assert ("customer.order_confirmed", "uz") in keys and ("customer.order_cancelled", "en") in keys
    assert (
        world.client.put(
            "/api/v1/shop/message-templates/customer.order_confirmed/uz",
            json={"body": "#{order_number}"},
            headers=_bearer(manager),
        ).status_code
        == 403
    )
    unknown = world.client.put(
        "/api/v1/shop/message-templates/customer.order_confirmed/uz",
        json={"body": "#{order_number} {phone}"},
        headers=_bearer(shop.owner),
    )
    assert (
        unknown.status_code == 422
        and unknown.json()["error"]["details"]["fields"][0]["code"] == "unknown_variables"
    )
    first = _ok(
        world.client.put(
            "/api/v1/shop/message-templates/customer.order_confirmed/uz",
            json={"body": "A #{order_number}"},
            headers=_bearer(shop.owner),
        )
    )
    second = _ok(
        world.client.put(
            "/api/v1/shop/message-templates/customer.order_confirmed/uz",
            json={"body": "B #{order_number}"},
            headers=_bearer(shop.owner),
        )
    )
    assert (first["version"], second["version"]) == (1, 2) and second["overridden"] is True
    reset = _ok(
        world.client.delete(
            "/api/v1/shop/message-templates/customer.order_confirmed/uz", headers=_bearer(shop.owner)
        )
    )
    assert reset["overridden"] is False and reset["body"] == reset["default_body"]
    assert (
        world.client.put(
            "/api/v1/shop/message-templates/staff.new_order/uz",
            json={"body": "x"},
            headers=_bearer(shop.owner),
        ).status_code
        == 404
    )


# ------------------------------------------------------------------ maxfiylik
def test_no_message_text_or_phone_in_outbox_audit_or_logs(world: World) -> None:
    inbox = Inbox(world)
    inbox.send({"text": "Mening raqamim +998 90 765 43 21, manzil Chilonzor 5"})
    inbox.send({"contact": {"phone_number": "+998907654321", "user_id": 5001}})
    conversation_id = inbox.conversations()[0]["id"]
    _ok(inbox.reply(conversation_id, "Maxfiy javob matni"), 201)
    _drain_now(world)
    dump = json.dumps([e["envelope"] for e in _outbox(world, inbox.shop.id)])
    for secret in ("90 765 43", "907654321", "Chilonzor", "Maxfiy javob", "Jasur"):  # vaqt va ID ham raqamli
        assert secret not in dump
    audit = _admin_sql(
        world, "SELECT diff::text AS diff FROM audit.audit_entries WHERE shop_id = $1", inbox.shop.id
    )
    assert all("907654321" not in (r["diff"] or "") and inbox.token not in (r["diff"] or "") for r in audit)
    stored = _admin_sql(
        world,
        "SELECT response_body::text AS body, request_hash FROM platform.idempotency_keys WHERE shop_id = $1",
        inbox.shop.id,
    )
    assert all("Maxfiy" not in (r["body"] or "") for r in stored)


# ------------------------------------------------------------------ rejali ishlar
def test_handoff_reminder_is_sent_once_after_policy_minutes(world: World) -> None:
    inbox = Inbox(world)
    sales, _ = inbox.shop.staff("SALES")
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    _job(world, "messaging_handoff_reminders")
    feed = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(sales)))["items"]
    assert not any(n["template_key"] == "staff.handoff_reminder" for n in feed)  # 15 daqiqa o'tmagan
    _admin_sql(
        world,
        "UPDATE messaging.handoffs SET created_at = now() - interval '20 minutes' WHERE conversation_id = $1",
        UUID(conversation_id),
    )
    _job(world, "messaging_handoff_reminders")
    _job(world, "messaging_handoff_reminders")
    feed = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(sales)))["items"]
    assert len([n for n in feed if n["template_key"] == "staff.handoff_reminder"]) == 1


def test_after_hours_customer_notice_once_per_handoff(world: World) -> None:
    inbox = Inbox(world)
    policy = _ok(world.client.get("/api/v1/shop/policies", headers=_bearer(inbox.owner)))
    hour = (datetime_now_tashkent().hour + 2) % 24  # ish vaqti hozir emas
    body = {k: v for k, v in policy.items() if k != "version"}
    body["inbox_hours"] = {
        "days": [1, 2, 3, 4, 5, 6, 7],
        "start": f"{hour:02d}:00",
        "end": f"{(hour + 1) % 24:02d}:00",
    }
    saved = world.client.patch(
        "/api/v1/shop/policies", json=body, headers=_hdr(inbox.owner, policy["version"])
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["inbox_hours"]["start"] == f"{hour:02d}:00"
    inbox.text()
    inbox.text("hali ham kutyapman")
    conversation_id = inbox.conversations()[0]["id"]
    notices = [m for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]
    assert len(notices) == 1 and notices[0]["body"].startswith("Hozir ish vaqtidan tashqari")
    _job(world, "messaging_handoff_reminders")  # ish vaqtidan tashqari — eslatma kutadi
    feed = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(inbox.owner)))["items"]
    assert not any(n["template_key"] == "staff.handoff_reminder" for n in feed)


def datetime_now_tashkent() -> Any:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    return datetime.now(UTC).astimezone(ZoneInfo("Asia/Tashkent"))


def test_retention_and_cleanup_jobs(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    _ok(_post(world, inbox.owner, f"/conversations/{conversation_id}/notes", {"body": "izoh"}), 201)
    fresh = Inbox(world)
    fresh.text()
    _admin_sql(
        world,
        "UPDATE messaging.conversations SET last_message_at = now() - interval '400 days' WHERE id = $1",
        UUID(conversation_id),
    )
    _admin_sql(
        world,
        "UPDATE messaging.provider_events SET received_at = now() - interval '31 days' WHERE shop_id = $1",
        inbox.shop.id,
    )
    _job(world, "messaging_retention")
    _job(world, "messaging_provider_events_cleanup")
    assert inbox.messages(conversation_id) == []  # 12 oy — xabarlar o'chdi, suhbat qatori qoldi
    assert (
        _ok(
            world.client.get(
                f"/api/v1/shop/conversations/{conversation_id}/notes", headers=_bearer(inbox.owner)
            )
        )["items"]
        == []
    )
    assert inbox.conversation(conversation_id)["id"] == conversation_id
    left = _admin_sql(
        world, "SELECT count(*) AS n FROM messaging.provider_events WHERE shop_id = $1", inbox.shop.id
    )
    assert left[0]["n"] == 0
    assert len(fresh.messages(fresh.conversations()[0]["id"])) == 1  # yangisiga tegilmadi
    site = Site(world)
    _ok(_post(world, site.owner, "/channels/webchat"), 201)
    chat = Chat(site)
    _admin_sql(
        world,
        "UPDATE messaging.webchat_sessions SET expires_at = now() - interval '31 days' WHERE shop_id = $1",
        site.shop.id,
    )
    _job(world, "messaging_webchat_sessions_cleanup")
    assert chat.poll().status_code == 404


def test_stuck_sending_becomes_unknown(world: World) -> None:
    inbox = Inbox(world)
    conversation_id = _queued_reply(world, inbox)
    _admin_sql(
        world,
        "UPDATE messaging.messages SET delivery_status = 'SENDING', "
        "created_at = now() - interval '10 minutes' "
        "WHERE conversation_id = $1 AND direction = 'OUT'",
        UUID(conversation_id),
    )
    _job(world, "messaging_stuck_sending")
    last = inbox.messages(conversation_id)[-1]
    assert last["delivery_status"] == "UNKNOWN" and last["last_error_code"] == "STUCK"


# ------------------------------------------------------------------ kanal hayoti
def test_new_bot_replaces_old_and_disconnect_stops_sending(world: World) -> None:
    inbox = Inbox(world)
    inbox.text()
    conversation_id = inbox.conversations()[0]["id"]
    token2, bot2 = _bot()
    inbox.fake.bots[token2] = bot2
    replaced = _ok(_post(world, inbox.owner, "/channels/telegram", {"token": token2}), 201)
    channels = {
        c["id"]: c
        for c in _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(inbox.owner)))["items"]
    }
    assert channels[inbox.account["id"]]["status"] == "DISCONNECTED"
    assert channels[inbox.account["id"]]["disconnect_reason"] == "REPLACED"
    # Eski bot webhook'i endi qabul qilinmaydi
    assert inbox.text().status_code == 404
    assert inbox.conversation(conversation_id)["channel_available"] is False
    version = channels[replaced["id"]]["version"]
    off = _post(world, inbox.owner, f"/channels/{replaced['id']}/disconnect", None, version)
    assert _ok(off)["status"] == "DISCONNECTED"
    assert inbox.fake.webhooks[token2] is None  # webhook o'chirildi


def test_channel_accounts_rls_without_context(world: World) -> None:
    from tests.integration.helpers import _sql

    inbox = Inbox(world)
    inbox.text()
    rows = _sql(
        world.urls.runtime.replace("+asyncpg", ""), "SELECT count(*) AS n FROM messaging.channel_accounts"
    )
    assert rows[0]["n"] == 0  # kontekstsiz — hech narsa (RLS FORCE)
    convs = _sql(
        world.urls.runtime.replace("+asyncpg", ""), "SELECT count(*) AS n FROM messaging.conversations"
    )
    assert convs[0]["n"] == 0


# ------------------------------------------------------------------ lokal polling (getUpdates)
def test_polling_feeds_updates_through_the_same_pipeline(world: World) -> None:
    import dataclasses

    from app.workers.telegram_polling import poll_once

    inbox = Inbox(world)
    services = world.client.app.state.messaging
    world.client.app.state.messaging = dataclasses.replace(
        services, config=dataclasses.replace(services.config, telegram_mode="polling")
    )
    _admin_sql(
        world,
        'UPDATE messaging.channel_accounts SET settings = \'{"mode": "polling"}\'::jsonb WHERE id = $1',
        UUID(inbox.account["id"]),
    )
    inbox.fake.updates[inbox.token] = [
        {
            "update_id": 501,
            "message": {
                "message_id": 1,
                "date": 1_790_000_000,
                "chat": {"id": 6001, "type": "private"},
                "from": {"id": 6001, "is_bot": False, "first_name": "Olim"},
                "text": "Polling orqali salom",
            },
        }
    ]
    try:
        handled = _run(world, RecordingQueue(), poll_once)
        again = _run(world, RecordingQueue(), poll_once)  # offset saqlangan — qayta olinmaydi
    finally:
        world.client.app.state.messaging = services
    assert handled == 1 and again == 0
    [conversation] = inbox.conversations()
    assert conversation["customer_name"] == "Olim"
    settings = _admin_sql(
        world, "SELECT settings FROM messaging.channel_accounts WHERE id = $1", UUID(inbox.account["id"])
    )
    assert json.loads(settings[0]["settings"])["polling_offset"] == 502
