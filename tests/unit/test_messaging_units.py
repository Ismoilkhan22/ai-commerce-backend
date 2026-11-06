"""5b: kanal adapterlari, ish vaqti, xaridor matnlari — bazasiz."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

import httpx
import pytest

from app.domains.messaging.channels.instagram import _token_revoked, parse_webhook, verify_signature
from app.domains.messaging.channels.telegram import parse_update, split_text
from app.domains.messaging.common import customer_phone, mask_phone, within_inbox_hours
from app.domains.messaging.services.notify import format_total
from app.platform.notifications.customer_templates import (
    CUSTOMER_TEMPLATES,
    TemplateBodyError,
    check_body,
    render_customer,
)


def _update(**message: object) -> dict[str, object]:
    base = {
        "message_id": 7,
        "date": 1_790_000_000,
        "chat": {"id": 42, "type": "private"},
        "from": {"id": 42, "is_bot": False, "first_name": "Jasur", "last_name": "T", "language_code": "ru"},
    }
    return {"update_id": 100, "message": {**base, **message}}


def test_text_update_maps_user_language_and_operator_command() -> None:
    inbound = parse_update(_update(text="/operator"))
    assert inbound is not None
    assert (inbound.external_user_id, inbound.display_name, inbound.language_code) == ("42", "Jasur T", "ru")
    assert inbound.intent_hint == "OPERATOR_REQUEST" and inbound.provider_event_id == "100"
    assert parse_update(_update(text="Salom")).intent_hint is None  # type: ignore[union-attr]


def test_group_bot_and_garbage_updates() -> None:
    group = parse_update(_update(text="x", chat={"id": -5, "type": "supergroup"}))
    assert group is not None and group.ignore_reason == "GROUP_CHAT"
    bot = parse_update(_update(text="x", **{"from": {"id": 1, "is_bot": True}}))
    assert bot is not None and bot.ignore_reason == "BOT_AUTHOR"
    assert parse_update({"update_id": True}) is None  # bool — ID emas
    assert parse_update({"update_id": 2**70}) is None
    assert parse_update({"update_id": 1}) is None


def test_contact_only_own_number_and_photo_largest_size() -> None:
    other = parse_update(_update(contact={"phone_number": "+998901112233", "user_id": 99}))
    assert other is not None and other.kind == "CONTACT" and other.contact_phone is None
    own = parse_update(_update(contact={"phone_number": "+998901112233", "user_id": 42}))
    assert own is not None and own.contact_phone == "+998901112233" and own.body is None
    photo = parse_update(
        _update(photo=[{"file_id": "s", "file_size": 1}, {"file_id": "l", "file_size": 50}], caption="shu")
    )
    assert photo is not None and photo.kind == "IMAGE" and photo.body == "shu"
    assert photo.attachments[0].provider_file_ref == "l"


def test_long_text_is_split_within_limit() -> None:
    parts = split_text(("so'z " * 2000).strip(), limit=4096)
    assert len(parts) == 3 and all(len(p) <= 4096 for p in parts)
    assert split_text("qisqa") == ["qisqa"]


def test_instagram_signature_and_parsing() -> None:
    body = b'{"entry": []}'
    good = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    assert verify_signature("app-secret", body, good)
    assert not verify_signature("app-secret", body, "sha256=00")
    assert not verify_signature("app-secret", body, None)
    payload = {
        "entry": [
            {
                "id": "17841400000",
                "messaging": [
                    {
                        "sender": {"id": "IGSID1"},
                        "timestamp": 1_790_000_000_000,
                        "message": {"mid": "m1", "text": "Narxi?"},
                    },
                    {
                        "sender": {"id": "IGSID1"},
                        "message": {"mid": "m2", "is_echo": True, "text": "o'zimiz"},
                    },
                ],
            }
        ]
    }
    [(account, inbound)] = parse_webhook(payload)
    assert account == "17841400000" and inbound.body == "Narxi?" and inbound.provider_event_id == "m1"


def test_inbox_hours_day_window_and_night_shift() -> None:
    hours = {"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}
    monday_noon = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)  # Toshkent 12:00, dushanba
    sunday_noon = datetime(2026, 10, 25, 7, 0, tzinfo=UTC)
    assert within_inbox_hours(hours, "Asia/Tashkent", monday_noon)
    assert not within_inbox_hours(hours, "Asia/Tashkent", sunday_noon)
    assert not within_inbox_hours(hours, "Asia/Tashkent", datetime(2026, 10, 26, 14, 0, tzinfo=UTC))  # 19:00
    night = {"days": [1], "start": "22:00", "end": "06:00"}
    assert within_inbox_hours(
        night, "Asia/Tashkent", datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    )  # dush. 23:00
    assert within_inbox_hours(
        night, "Asia/Tashkent", datetime(2026, 10, 26, 22, 0, tzinfo=UTC)
    )  # sesh. 03:00
    assert within_inbox_hours(None, "Asia/Tashkent", sunday_noon)
    assert within_inbox_hours({"days": [1], "start": "bad"}, "Asia/Tashkent", sunday_noon)  # buzilgan — ochiq


def test_customer_templates_variables_and_render() -> None:
    check_body("customer.order_confirmed", "#{order_number} — {total}")
    with pytest.raises(TemplateBodyError) as missing:
        check_body("customer.order_confirmed", "Tasdiqlandi")
    assert missing.value.code == "missing_variables" and missing.value.variables == ["order_number"]
    with pytest.raises(TemplateBodyError) as unknown:
        check_body("customer.order_confirmed", "#{order_number} {phone}")
    assert unknown.value.code == "unknown_variables"
    text = render_customer(CUSTOMER_TEMPLATES["customer.order_ready_pickup"].body["uz"], {"order_number": 12})
    assert text == "Buyurtma #12 tayyor. Manzil: ."  # telefon yo'q — "Tel: ." chiqmaydi (QA 5b L7)
    for template in CUSTOMER_TEMPLATES.values():
        assert set(template.body) == {"uz", "ru", "en"}
        for body in template.body.values():
            check_body(next(k for k, v in CUSTOMER_TEMPLATES.items() if v is template), body)


def test_money_and_phone_helpers() -> None:
    assert format_total(480_000_000, "uz") == "4 800 000 so'm"
    assert format_total(480_000_000, "ru") == "4 800 000 сум"
    assert format_total(480_000_000, "en") == "UZS 4,800,000"
    assert customer_phone("998901234567") == "+998901234567"
    assert customer_phone("+44 20 7946 0958") == "+442079460958"  # chet el raqami
    assert customer_phone("12") is None
    assert mask_phone("+998901234567") == "+99890 *** ** 67"


@pytest.mark.parametrize(
    ("status", "body", "revoked"),
    [
        (401, {}, True),
        (403, {}, True),
        (400, {"error": {"type": "OAuthException", "code": 190}}, True),  # token yaroqsiz/eskirgan
        (400, {"error": {"code": 102}}, True),
        (400, {"error": {"code": 551}}, False),  # 24 soatlik oyna yopilgan — boshqa xato
        (404, {}, False),
    ],
)
def test_instagram_send_error_maps_revoked_token(status: int, body: dict[str, object], revoked: bool) -> None:
    assert _token_revoked(httpx.Response(status, json=body)) is revoked
    assert _token_revoked(httpx.Response(status, content=b"not json")) is (status in (401, 403))
