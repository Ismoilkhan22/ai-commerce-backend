"""7b (kafolat murojaatlari): kafolat hisobi, FSM-11 qoidalari, ruxsatlar, xaridor shablonlari."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.domains.support import permissions as perm
from app.domains.support.common import add_months, warranty_window
from app.domains.support.events import case_payload
from app.domains.support.models.orm import SupportCase
from app.domains.support.state_machine import CASE_RULES, NON_FORCEABLE
from app.platform.notifications.customer_templates import (
    CUSTOMER_TEMPLATES,
    LOCALES,
    check_body,
    render_customer,
)
from app.shared.events.pii import forbidden_keys

TASHKENT = ZoneInfo("Asia/Tashkent")


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 10, 27), 12) == date(2027, 10, 27)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_warranty_window_is_inclusive_uses_shop_zone_and_none_means_no_warranty() -> None:
    # 2026-10-27 23:30 UTC = 2026-10-28 04:30 Toshkent → sotilgan kun 28-oktyabr
    sold = datetime(2026, 10, 27, 23, 30, tzinfo=UTC)
    until, within = warranty_window(sold, 12, TASHKENT, datetime(2027, 10, 28, 12, 0, tzinfo=UTC))
    assert until == date(2027, 10, 28) and within is True  # oxirgi kun ham kafolat ichida
    _, late = warranty_window(
        sold, 12, TASHKENT, datetime(2027, 10, 28, 20, 0, tzinfo=UTC)
    )  # Toshkentda 29-oktyabr
    assert late is False
    assert warranty_window(sold, None, TASHKENT, sold) == (None, False)
    assert warranty_window(sold, 0, TASHKENT, sold)[1] is True  # 0 oy — sotilgan kun


def test_fsm11_rules_cover_business_arrows_and_protect_stock_states() -> None:
    arrows = {(r.command, r.from_status, r.to_status) for r in CASE_RULES}
    assert arrows == {
        ("START_REVIEW", "NEW", "IN_REVIEW"),
        ("APPROVE", "IN_REVIEW", "APPROVED"),
        ("REJECT", "IN_REVIEW", "REJECTED"),
        ("START_SERVICE", "APPROVED", "IN_SERVICE"),
        ("RESOLVE", "IN_SERVICE", "RESOLVED"),
        ("CLOSE", "RESOLVED", "CLOSED"),
    }
    assert {r.command for r in CASE_RULES if r.requires_reason} == {"REJECT"}
    assert {r.command for r in CASE_RULES if "SYSTEM" in r.actors} == {"CLOSE"}
    assert NON_FORCEABLE["support.case"] == frozenset({"IN_SERVICE", "RESOLVED"})  # ombor yozuvi bor holatlar


def test_permissions_match_business_04() -> None:
    from app.domains.support.permissions import SUPPORT_ROLE_GRANTS as grants

    assert perm.CASE_DECIDE in grants["OWNER"] and perm.CASE_DECIDE in grants["MANAGER"]
    assert perm.CASE_DECIDE not in grants["SALES"] and perm.CASE_DECIDE not in grants["WAREHOUSE"]
    assert perm.CASE_OPEN in grants["SALES"] and perm.CASE_OPEN not in grants["WAREHOUSE"]
    assert perm.CASE_VIEW in grants["WAREHOUSE"] and perm.CASE_FULFIL not in grants["SALES"]


@pytest.mark.parametrize("key", [k for k in CUSTOMER_TEMPLATES if k.startswith("customer.support_case_")])
def test_support_customer_templates_have_three_locales_and_render(key: str) -> None:
    template = CUSTOMER_TEMPLATES[key]
    assert set(template.body) == set(LOCALES) and "case_number" in template.required
    values = {name: "X" for name in template.allowed}
    for locale in LOCALES:
        check_body(key, template.body[locale])
        assert "K-X" in render_customer(template.body[locale], values)


def test_four_support_customer_templates_exist() -> None:
    assert {k for k in CUSTOMER_TEMPLATES if k.startswith("customer.support_case_")} == {
        "customer.support_case_opened",
        "customer.support_case_approved",
        "customer.support_case_rejected",
        "customer.support_case_ready",
    }


def test_event_payload_has_no_pii_words() -> None:
    case = SupportCase(
        id=uuid4(),
        shop_id=uuid4(),
        number=1,
        type="WARRANTY",
        status="NEW",
        source="ORDER_LINE",
        qty=1,
        branch_id=uuid4(),
        title_snapshot="GPU",
        within_warranty=True,
        opened_by=uuid4(),
        customer_locale="uz",
        customer_name="Jasur",
        problem_description="o'chib qoladi",
    )
    payload = case_payload(case, change="NOTE", note_kind="DIAGNOSIS")
    assert forbidden_keys(payload) == []
    assert "Jasur" not in str(payload) and "o'chib qoladi" not in str(payload)
