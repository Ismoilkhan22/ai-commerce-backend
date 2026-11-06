"""Sentry PII tozalash (09 §9, S0-05) va JSON logdagi service maydonlari."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config.observability import before_breadcrumb, before_send, init_sentry, scrub_text
from app.config.settings import Settings
from app.shared.errors.base import NotFoundError


def test_scrub_text_masks_pii_and_tokens() -> None:
    text = (
        "user +998 90 123 45 67 ali@example.uz token 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawZ "
        "Bearer abc.def /api/v1/shop/orders?q=998901234567 on 2026-10-27"
    )
    scrubbed = scrub_text(text)
    for secret in ("998", "ali@example.uz", "AAHdq", "abc.def", "q=99"):
        assert secret not in scrubbed
    assert "2026-10-27" in scrubbed  # sana telefon emas


def test_before_send_strips_request_and_user() -> None:
    event: dict[str, Any] = {
        "request": {
            "method": "POST",
            "url": "https://api.platforma.uz/api/v1/shop/orders?q=+998901234567",
            "headers": {"Authorization": "Bearer x", "Cookie": "cos_refresh_shop=y"},
            "cookies": {"a": "b"},
            "data": {"phone": "+998901234567"},
            "query_string": "q=+998901234567",
        },
        "user": {"id": "0192-actor", "email": "a@b.uz", "ip_address": "1.2.3.4"},
        "exception": {"values": [{"value": "bad phone +998901234567"}]},
    }
    result = before_send(event, {})
    assert result is not None
    assert result["request"] == {"method": "POST", "url": "https://api.platforma.uz/api/v1/shop/orders"}
    assert result["user"] == {"id": "0192-actor"}
    assert "998" not in json.dumps(result)


def test_before_send_drops_expected_domain_errors() -> None:
    exc = NotFoundError("File not found")
    assert before_send({}, {"exc_info": (type(exc), exc, None)}) is None
    boom = RuntimeError("boom")
    assert before_send({}, {"exc_info": (type(boom), boom, None)}) == {}


def test_http_breadcrumbs_dropped() -> None:
    crumb = {"category": "httplib", "data": {"url": "https://api.telegram.org/bot123:SECRET/sendMessage"}}
    assert before_breadcrumb(crumb, {}) is None
    kept = before_breadcrumb({"category": "log", "message": "call +998901234567"}, {})
    assert kept is not None and "998" not in kept["message"]


def test_sentry_disabled_without_dsn() -> None:
    assert init_sentry(Settings()) is False


def test_json_logs_carry_service_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import structlog

    from app.config.logging import configure_logging

    monkeypatch.setenv("SERVICE_NAME", "task-worker")
    monkeypatch.setenv("APP_VERSION", "abc123")
    configure_logging("INFO", json=True)
    try:
        structlog.get_logger().info("probe.event")
        line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert (
            line["service"] == "task-worker"
            and line["version"] == "abc123"
            and line["event"] == "probe.event"
        )
    finally:
        structlog.reset_defaults()
