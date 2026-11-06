"""5a QA tuzatishlari — bazasiz qismlar: log filtri, cron oralig'i, bot parseri, sozlama sxemasi,
vazifa rollari, qoldiq agregati, ulanish chegarasi va rate limit ko'paytmasi."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config.logging import RedactQueryFilter
from app.config.settings import Settings
from app.domains.commerce.events import stock_aggregate_id
from app.platform.jobs.api.platform_routes import interval_of
from app.platform.notifications.api.webhook_routes import _start_code
from app.platform.notifications.schemas import MUTABLE_TYPES, NotificationSettingsIn
from app.platform.notifications.services.tasks import task_role_allows
from app.platform.notifications.templates import priority_of
from app.shared.realtime import MemoryBroker


def test_uvicorn_websocket_log_hides_ticket() -> None:  # F6
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5000", "/api/v1/ws?ticket=SECRET-TICKET-VALUE"),
        None,
    )
    assert RedactQueryFilter().filter(record)
    assert "SECRET" not in record.getMessage() and "/api/v1/ws?…" in record.getMessage()


def test_configured_uvicorn_error_logger_has_filter() -> None:
    from app.config.logging import configure_logging

    configure_logging("INFO", json=True)
    assert any(isinstance(f, RedactQueryFilter) for f in logging.getLogger("uvicorn.error").filters)


@pytest.mark.parametrize(
    ("every", "cron", "expected"),
    [
        (900, None, 900),
        (None, "30 3 * * *", 86400),
        (None, "0 4 1 * *", 31 * 86400),
        (None, "*/15 * * * *", 900),
    ],
)
def test_job_interval(every: int | None, cron: str | None, expected: int) -> None:  # I2
    assert interval_of(every, cron) == expected


def _update(text: str, user: object = 42, chat: object = 42, kind: str = "private") -> dict[str, object]:
    return {"message": {"text": text, "chat": {"id": chat, "type": kind}, "from": {"id": user}}}


def test_bot_start_parser_is_strict() -> None:  # I3
    assert _start_code(_update("/start ABCD2345")) == ("ABCD2345", 42, 42)
    assert _start_code(_update("/start@cos_staff_bot ABCD2345")) == ("ABCD2345", 42, 42)
    assert _start_code(_update("/startXYZ ABCD2345")) is None
    assert _start_code(_update("/start")) is None
    assert _start_code(_update("/start ABCD2345", user=True)) is None  # bool — ID emas
    assert _start_code(_update("/start ABCD2345", chat=2**63)) is None  # int64 dan katta
    assert _start_code(_update("/start ABCD2345", kind="group")) is None


def test_settings_schema_rejects_unknown_fields_same_quiet_and_offsets() -> None:  # F9
    with pytest.raises(ValidationError):
        NotificationSettingsIn.model_validate({"quiet_form": "23:00"})
    with pytest.raises(ValidationError):
        NotificationSettingsIn.model_validate({"quiet_from": "09:00", "quiet_to": "09:00"})
    with pytest.raises(ValidationError):
        NotificationSettingsIn.model_validate({"quiet_from": "22:00+03:00", "quiet_to": "07:00"})
    with pytest.raises(ValidationError):
        NotificationSettingsIn.model_validate({"muted_types": ["staff.stock_reconcile_mismatch"]})  # HIGH
    ok = NotificationSettingsIn.model_validate(
        {"quiet_from": "22:00", "quiet_to": "07:00", "muted_types": ["staff.order_confirm_reminder"]}
    )
    assert ok.muted_types == ["staff.order_confirm_reminder"]
    assert "staff.new_order" not in MUTABLE_TYPES and priority_of("staff.new_order") == "HIGH"  # I4


def test_task_roles_per_type() -> None:  # F8
    assert task_role_allows("ADJUSTMENT_APPROVAL", "MANAGER", "MANAGER")
    assert task_role_allows("ADJUSTMENT_APPROVAL", "MANAGER", "OWNER")
    assert not task_role_allows("ADJUSTMENT_APPROVAL", "MANAGER", "WAREHOUSE")
    assert not task_role_allows("ADJUSTMENT_APPROVAL", "MANAGER", "SALES")
    assert task_role_allows("ORDER_CONFIRM_REMINDER", "MANAGER", "SALES")
    assert not task_role_allows("NEW_KIND", "OWNER", "MANAGER")  # ro'yxatda yo'q — assignee_role bo'yicha
    assert task_role_allows("NEW_KIND", "SALES", "MANAGER")


def test_stock_aggregate_is_per_branch_and_stable() -> None:  # F4
    branch, other, sku = uuid4(), uuid4(), uuid4()
    assert stock_aggregate_id(branch, sku) == stock_aggregate_id(branch, sku)
    assert stock_aggregate_id(branch, sku) != stock_aggregate_id(other, sku)


def test_memory_broker_socket_cap_ignores_stale() -> None:  # F11
    broker, member = MemoryBroker(), uuid4()

    async def go() -> list[bool]:
        results = [
            await broker.claim_socket(member, f"c{i}", now=100.0, stale_after=75, limit=2) for i in range(3)
        ]
        await broker.release_socket(member, "c0")
        results.append(await broker.claim_socket(member, "c3", now=101.0, stale_after=75, limit=2))
        # c1 va c3 eskirdi (heartbeat yo'q) — yangi ulanish joy oladi
        results.append(await broker.claim_socket(member, "c4", now=300.0, stale_after=75, limit=2))
        return results

    assert asyncio.run(go()) == [True, True, False, True, True]


def test_rate_limit_scale_is_local_only() -> None:  # (c)
    assert Settings(app_env="test", rate_limit_scale=10).rate_limit_scale == 10  # type: ignore[call-arg]
    legacy = Settings.model_validate({"app_env": "test", "rate_limit_memory_scale": 4})
    assert legacy.rate_limit_scale == 4
    urls = {
        "database_url": "postgresql+asyncpg://app_runtime:r4nd0m-runtime-pw@db.internal:5432/cos",
        "database_migrator_url": "postgresql+asyncpg://app_migrator:r4nd0m-migrator-pw@db.internal:5432/cos",
    }
    with pytest.raises(ValidationError, match="rate_limit_scale"):
        Settings.model_validate(
            {"app_env": "production", "jwt_secret": "x" * 40, "rate_limit_scale": 5, **urls}
        )
