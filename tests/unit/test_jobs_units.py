"""5a: event va fon ishlari yordamchilari (DB'siz) — payload PII tekshiruvi, tinglovchi mosligi, shablonlar,
tinch soat, realtime broker, bot webhook'i, retry kechikishi."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time
from uuid import uuid4

import pytest

from app.platform.notifications.api.webhook_routes import _start_code
from app.platform.notifications.models.orm import StaffNotificationSettings
from app.platform.notifications.services.delivery import _in_quiet_hours
from app.platform.notifications.services.tasks import task_link
from app.platform.notifications.templates import TEMPLATES, render
from app.shared.events.pii import EventPayloadError, check_payload, forbidden_keys
from app.shared.events.registry import JobResult, ScheduledJob, Subscriber, SubscriberRegistry
from app.shared.realtime import MemoryBroker
from app.workers.dispatch import MAX_BACKOFF_SECONDS, backoff_seconds, error_code


async def _noop(*_: object) -> None:
    return None


def _sub(name: str, *types: str) -> Subscriber:
    return Subscriber(consumer=name, event_types=frozenset(types), schema="platform", handler=_noop)


# ------------------------------------------------------------------ payload'da PII yo'q (05 §3.1)
@pytest.mark.parametrize(
    "payload",
    [
        {"customer_phone": "+998901234567"},
        {"order": {"deliveryAddress": "Chilonzor"}},
        {"lines": [{"sku_id": "x", "customer_name": "Jasur"}]},
        {"comment": "kechqurun qo'ng'iroq qiling"},
        {"token": "abc"},
        {"message_text": "salom"},
    ],
)
def test_payload_with_pii_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(EventPayloadError):
        check_payload(payload)


def test_payload_with_ids_and_facts_is_allowed() -> None:
    payload = {
        "order_id": str(uuid4()),
        "status": "CONFIRMED",
        "total_minor": 480_000_000,
        "lines": [{"sku_id": str(uuid4()), "qty": 1}],
        "assigned_staff_id": None,
    }
    assert forbidden_keys(payload) == []
    check_payload(payload)


# ------------------------------------------------------------------ tinglovchilar va rejali ishlar
def test_subscriber_matches_exact_and_wildcard() -> None:
    sub = _sub("x", "commerce.order.*", "commerce.stock.changed")
    assert sub.matches("commerce.order.confirmed") and sub.matches("commerce.stock.changed")
    assert not sub.matches("commerce.orders") and not sub.matches("catalog.price.changed")


def test_registry_rejects_duplicate_consumer_names() -> None:
    with pytest.raises(ValueError, match="takrorlangan"):
        SubscriberRegistry([_sub("same", "a.b.c"), _sub("same", "a.b.d")])
    registry = SubscriberRegistry([_sub("one", "a.b.c"), _sub("two", "a.b.*")])
    assert [s.consumer for s in registry.for_event("a.b.c")] == ["one", "two"]
    assert registry.get("two") is not None and registry.get("three") is None


def test_scheduled_job_needs_exactly_one_schedule() -> None:
    async def job(_: object) -> JobResult:
        return JobResult()

    with pytest.raises(ValueError):
        ScheduledJob("both", job, every_seconds=60, cron="* * * * *")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ScheduledJob("none", job)  # type: ignore[arg-type]


def test_backoff_grows_and_is_capped() -> None:
    assert 2 <= backoff_seconds(1) < 3
    assert MAX_BACKOFF_SECONDS <= backoff_seconds(20) < MAX_BACKOFF_SECONDS + 1


def test_error_code_never_contains_the_message() -> None:
    assert error_code(ValueError("+998901234567 telefon")) == "ValueError"

    class Coded(Exception):
        code = "BLOCKED"

    assert error_code(Coded("matn")) == "Coded:BLOCKED"


# ------------------------------------------------------------------ shablonlar va havolalar
def test_templates_exist_in_three_languages_and_render() -> None:
    for key, template in TEMPLATES.items():
        assert set(template.title) == set(template.body) == {"uz", "ru", "en"}, key
    title, body = render("staff.order_confirm_reminder", "ru", {"order_number": 1042, "hours": 24})
    assert title == "Заказ #1042 ждёт подтверждения" and "24" in body
    title, _ = render("staff.new_order", "uz-Cyrl", {})  # noma'lum til — o'zbekcha; yo'q o'zgaruvchi qoladi
    assert title == "Yangi buyurtma #{order_number}"


def test_task_links_point_to_panel_screens() -> None:
    order_id = uuid4()
    link = task_link("ORDER_CONFIRM_REMINDER", order_id)
    assert link is not None and (link.route, link.id) == ("order", order_id)
    stale = task_link("EXCHANGE_RATE_STALE", order_id)
    assert stale is not None and (stale.route, stale.id) == ("exchange_rates", None)
    assert task_link("UNKNOWN", order_id) is None


# ------------------------------------------------------------------ tinch soat (shop vaqti)
def _settings(start: time, end: time) -> StaffNotificationSettings:
    return StaffNotificationSettings(quiet_from=start, quiet_to=end, telegram_enabled=True, muted_types=[])


def test_quiet_hours_overnight_window() -> None:
    settings = _settings(time(22, 0), time(8, 0))
    night = datetime(2026, 10, 26, 23, 30, tzinfo=UTC)
    resume = _in_quiet_hours(settings, night)
    assert resume == datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    early = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
    assert _in_quiet_hours(settings, early) == datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    assert _in_quiet_hours(settings, datetime(2026, 10, 27, 12, 0, tzinfo=UTC)) is None
    assert _in_quiet_hours(None, night) is None


# ------------------------------------------------------------------ realtime broker
def test_memory_broker_sequences_and_single_use_tickets() -> None:
    async def run() -> None:
        broker, member = MemoryBroker(), uuid4()
        sub = await broker.subscribe(member)
        assert await broker.publish(member, {"type": "a"}) == 1
        assert await broker.publish(member, {"type": "b"}) == 2
        assert await broker.current_seq(member) == 2
        first = await sub.next(1.0)
        assert first == {"type": "a", "seq": 1}
        assert (await sub.next(1.0)) == {"type": "b", "seq": 2}
        assert await sub.next(0.05) is None
        await sub.close()
        await broker.put_ticket("h1", {"x": "y"}, 30)
        assert await broker.take_ticket("h1") == {"x": "y"}
        assert await broker.take_ticket("h1") is None  # bir martalik
        await broker.put_ticket("h2", {"x": "y"}, 0)
        assert await broker.take_ticket("h2") is None  # muddati o'tgan

    asyncio.run(run())


# ------------------------------------------------------------------ platforma boti webhook'i
def test_start_code_is_parsed_only_from_private_chat() -> None:
    update = {
        "message": {"text": "/start ABCD2345XY", "chat": {"id": 55, "type": "private"}, "from": {"id": 7}}
    }
    assert _start_code(update) == ("ABCD2345XY", 7, 55)
    group = {"message": {"text": "/start X", "chat": {"id": 1, "type": "group"}, "from": {"id": 7}}}
    assert _start_code(group) is None
    assert (
        _start_code({"message": {"text": "/start", "chat": {"id": 1, "type": "private"}, "from": {"id": 7}}})
        is None
    )
    assert _start_code({"edited_message": {}}) is None
