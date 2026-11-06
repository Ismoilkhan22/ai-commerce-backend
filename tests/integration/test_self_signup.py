"""M21 (Stage 2): shopning o'zi ro'yxatdan o'tishi — SMS kod, token, shop DRAFT + ega, firibgarlikdan himoya.

SMS — `FakeSmsSender` (`app.state.sms.sent`), flag — test ichida yoqiladi.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from app.platform.sms.sender import FakeSmsSender
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import _admin_sql, _ok

pytestmark = pytest.mark.integration

API = "/api/v1/auth/signup"


@pytest.fixture
def signup(world: World) -> Iterator[FakeSmsSender]:
    service = world.client.app.state.signup
    object.__setattr__(service.config, "enabled", True)
    sms: FakeSmsSender = world.client.app.state.sms
    sms.sent.clear()
    yield sms
    object.__setattr__(service.config, "enabled", False)


def _phone() -> str:
    return f"+99890{uuid4().int % 10**7:07d}"


def _tin() -> str:
    return f"{uuid4().int % 10**9:09d}"


def _code(sms: FakeSmsSender, phone: str) -> str:
    text = next(t for p, t in reversed(sms.sent) if p == phone)
    match = re.search(r"\b(\d{6})\b", text)
    assert match is not None
    return match.group(1)


def _start(world: World, phone: str) -> Any:
    return world.client.post(f"{API}/start", json={"phone": phone})


def test_self_signup_creates_draft_shop_and_logs_owner_in(world: World, signup: FakeSmsSender) -> None:
    phone, tin = _phone(), _tin()
    started = _ok(_start(world, phone), 202)
    assert started["resend_after_seconds"] == 60
    assert _start(world, phone).status_code == 429  # 60 soniya o'tmagan
    wrong = world.client.post(f"{API}/verify", json={"request_id": started["request_id"], "code": "000000"})
    if _code(signup, phone) != "000000":
        assert wrong.status_code == 422
        rows = _admin_sql(world, "SELECT attempts FROM platform.signup_requests WHERE phone = $1", phone)
        assert rows[0]["attempts"] == 1  # xato urinish saqlandi (rollback bo'lmadi)
    verified = _ok(
        world.client.post(
            f"{API}/verify", json={"request_id": started["request_id"], "code": _code(signup, phone)}
        )
    )
    body = {
        "signup_token": verified["signup_token"],
        "shop_name": "Kompyuter Олами",
        "tin": tin,
        "owner_full_name": "Aziz Karimov",
        "password": "Yaxshi-Parol-2026",
    }
    created = _ok(world.client.post(f"{API}/complete", json=body), 201)
    token = created["access_token"]
    me = _ok(world.client.get("/api/v1/auth/me", headers=_bearer(token)))
    assert me["shop"]["slug"].startswith("kompyuter-olami") and me["shop"]["status"] == "DRAFT"
    shop = _admin_sql(world, "SELECT signup_source, status FROM platform.shops WHERE tin = $1", tin)[0]
    assert shop["signup_source"] == "SELF" and shop["status"] == "DRAFT"
    # Token ikkinchi marta ishlamaydi; o'sha telefon va STIR qayta ishlatilmaydi
    again = world.client.post(f"{API}/complete", json=body)
    assert again.status_code == 422
    login = world.client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": "Yaxshi-Parol-2026", "audience": "shop"}
    )
    assert login.status_code == 200


def test_signup_guards(world: World, signup: FakeSmsSender) -> None:
    phone = _phone()
    started = _ok(_start(world, phone), 202)
    for _ in range(5):
        world.client.post(f"{API}/verify", json={"request_id": started["request_id"], "code": "123456"})
    # 5 urinishdan keyin to'g'ri kod ham ishlamaydi
    late = world.client.post(
        f"{API}/verify", json={"request_id": started["request_id"], "code": _code(signup, phone)}
    )
    assert late.status_code in (404, 422)
    forged = world.client.post(
        f"{API}/complete",
        json={
            "signup_token": "x.y",
            "shop_name": "Test",
            "tin": _tin(),
            "owner_full_name": "Test Test",
            "password": "Yaxshi-Parol-2026",
        },
    )
    assert forged.status_code == 422


def test_signup_disabled_by_default(world: World) -> None:
    assert (
        world.client.post(f"{API}/start", json={"phone": _phone()}).status_code == 501
    )  # FEATURE_NOT_AVAILABLE
