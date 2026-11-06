"""5b QA tuzatishlari — bazasiz qismlar: shablon tekshiruvi, Telegram qadamlari, mehmon tili, ish vaqti."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from app.domains.messaging.api.public_routes import visitor_locale
from app.domains.messaging.channels.telegram import MAX_CAPTION, MAX_TEXT, parse_update
from app.domains.messaging.common import TEST_TELEGRAM_TOKEN, within_inbox_hours
from app.domains.messaging.services.sending import telegram_steps
from app.platform.notifications.customer_templates import (
    MAX_RENDERED_LENGTH,
    TemplateBodyError,
    check_body,
    render_customer,
    safe_render,
)


@pytest.mark.parametrize(
    "body",
    ["a } {hours}", "{ {hours}", "{0}", "{}", "{hours.real}", "{hours[0]}", "{hours!s}", "{hours:>9}"],
)
def test_check_body_rejects_unsafe(body: str) -> None:
    with pytest.raises(TemplateBodyError):
        check_body("customer.handoff_after_hours", body)


def test_check_body_allows_escaped_braces_and_known_names() -> None:
    check_body("customer.handoff_after_hours", "{{izoh}} {hours} — {shop_name}")
    assert render_customer("{{izoh}} {hours}", {"hours": "9–18"}) == "{izoh} 9–18"


def test_render_never_uses_attribute_access_and_caps_length() -> None:
    assert render_customer("{order_number}", {"order_number": "x" * 10_000}) == "x" * MAX_RENDERED_LENGTH


def test_safe_render_falls_back_to_default_in_same_locale() -> None:
    text = safe_render("customer.handoff_after_hours", "bad } {hours}", {"hours": "9–18"}, "ru")
    assert text.startswith("Сейчас нерабочее время") and "9–18" in text


def test_ready_pickup_default_without_phone_has_no_dangling_label() -> None:
    from app.platform.notifications.customer_templates import default_body

    text = render_customer(
        default_body("customer.order_ready_pickup", "uz"),
        {"order_number": 7, "shop_address": "Chilonzor 1", "phone_line": ""},
    )
    assert "Tel" not in text and text.endswith("Manzil: Chilonzor 1.")


def test_telegram_steps_split_text_and_caption() -> None:
    assert telegram_steps("salom", has_photo=False) == [("text", "salom")]
    long = "so'z " * 1500
    steps = telegram_steps(long, has_photo=False)
    assert len(steps) == 2 and all(len(v or "") <= MAX_TEXT for _, v in steps)
    caption = "izoh " * 400  # ~2000 > 1024
    photo_steps = telegram_steps(caption, has_photo=True)
    assert photo_steps[0][0] == "photo" and len(photo_steps[0][1] or "") <= MAX_CAPTION
    assert photo_steps[1][0] == "text"
    assert telegram_steps(None, has_photo=True) == [("photo", None)]


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "method": "GET", "path": "/"})


def test_visitor_locale_prefers_explicit_header() -> None:
    assert visitor_locale(_request({"X-Customer-Locale": "ru"})) == "ru"
    assert visitor_locale(_request({"Accept-Language": "fr-FR, en;q=0.8"})) == "en"
    assert visitor_locale(_request({"X-Customer-Locale": "de"})) is None


def test_parse_update_ignores_wrong_types() -> None:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 2,
            "chat": {"id": 3, "type": "private"},
            "from": {"id": 3, "username": ["x"], "first_name": 5},
            "photo": [{"file_id": "a", "file_size": "big"}, {"file_id": "b", "file_size": 10}],
        },
    }
    parsed = parse_update(update)
    assert parsed is not None and parsed.username is None and parsed.display_name is None
    assert parsed.attachments[0].provider_file_ref == "b"


def test_equal_inbox_hours_are_treated_as_always_open() -> None:
    hours = {"days": [1, 2, 3, 4, 5, 6, 7], "start": "09:00", "end": "09:00"}
    assert within_inbox_hours(hours, "Asia/Tashkent", datetime(2026, 10, 26, 3, tzinfo=UTC)) is True


def test_test_token_pattern_matches_real_token_shape() -> None:
    assert TEST_TELEGRAM_TOKEN.fullmatch("900000001:TEST" + "a" * 26)
    assert not TEST_TELEGRAM_TOKEN.fullmatch("900000001:AAH" + "a" * 30)
