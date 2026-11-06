# ruff: noqa: E501
"""Xaridor akkaunti (Stage 3 davomi): SMS kod bilan kirish, sessiya, tarix, sevimlilar, maslahatchi suhbati.

Qabul mezonlari: kod 5 marta noto'g'ri bo'lsa yopiladi; token bekor qilinsa darhol ishlamaydi; tarix faqat
kirgan xaridor uchun yoziladi; boshqa xaridorning ma'lumotiga tegib bo'lmaydi; akkaunt o'chsa hamma o'chadi.
SMS — `FakeSmsSender` (`dev_code` faqat shu bilan qaytadi).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.domains.network.services import buyers as buyers_module
from app.platform.sms.sender import FakeSmsSender
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok
from tests.integration.test_jobs_events import _job
from tests.integration.test_network import _activate, _product, _publish, clean_outbox  # noqa: F401

pytestmark = pytest.mark.integration
API = "/api/v1/public/marketplace"
CHILD_TABLES = (
    "buyer_sessions",
    "buyer_views",
    "buyer_searches",
    "buyer_favorites",
    "buyer_advisor_messages",
)


def _phone() -> str:
    return f"+99890{uuid4().int % 10**7:07d}"


def _login(world: World, phone: str | None = None) -> tuple[str, dict[str, Any]]:
    phone = phone or _phone()
    started = _ok(world.client.post(f"{API}/auth/start", json={"phone": phone}), 202)
    done = _ok(
        world.client.post(
            f"{API}/auth/verify", json={"request_id": started["request_id"], "code": started["dev_code"]}
        )
    )
    return done["session_token"], done


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _listed(world: World, amount: int = 500_000_000) -> tuple[str, str, Shop, str]:
    """Ommaviy mahsulot: (canonical_id, qidiruv so'zi, shop, sku_id)."""
    shop = Shop(world)
    _activate(world, shop)
    word = f"buyer{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} RTX 4060", "MSI", f"B{uuid4().hex[:7].upper()}", amount=amount)
    _ok(_publish(world, shop.owner, sku))
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    return item["canonical_id"], word, shop, sku


def _count(world: World, table: str, buyer_id: str) -> int:
    rows = _admin_sql(world, f"SELECT count(*) AS n FROM network.{table} WHERE buyer_id = $1::uuid", buyer_id)
    return int(rows[0]["n"])


def test_login_happy_path_and_profile(world: World) -> None:
    sms: FakeSmsSender = world.client.app.state.sms
    phone = "+998901234567"
    started = _ok(world.client.post(f"{API}/auth/start", json={"phone": phone}), 202)
    assert started["resend_after_seconds"] == 60 and started["expires_in_seconds"] == 600
    code = started["dev_code"]
    assert len(code) == 6
    sent = [t for p, t in sms.sent if p == phone][-1]
    assert sent == f"AI Commerce: kirish kodi {code}. Uni hech kimga bermang."
    done = _ok(
        world.client.post(f"{API}/auth/verify", json={"request_id": started["request_id"], "code": code})
    )
    token = done["session_token"]
    assert done["buyer"]["phone_masked"] == "+998 90 *** ** 67" and done["buyer"]["locale"] == "uz"
    # Kod bir martalik
    again = world.client.post(f"{API}/auth/verify", json={"request_id": started["request_id"], "code": code})
    assert again.status_code == 404
    me = _ok(world.client.get(f"{API}/me", headers=_auth(token)))
    assert me["id"] == done["buyer"]["id"] and me["name"] is None
    patched = _ok(
        world.client.patch(f"{API}/me", json={"name": "Aziz", "locale": "ru"}, headers=_auth(token))
    )
    assert patched["name"] == "Aziz" and patched["locale"] == "ru"
    assert world.client.patch(f"{API}/me", json={"locale": "xx"}, headers=_auth(token)).status_code == 422
    # Telefon ochiq saqlanmaydi; ikkinchi kirishda o'sha xaridor
    stored = _admin_sql(world, "SELECT phone_enc FROM network.buyers WHERE id = $1::uuid", me["id"])[0]
    assert "901234567" not in stored["phone_enc"]
    _, second = _login(world, phone)
    assert second["buyer"]["id"] == me["id"]


def test_wrong_code_then_lockout(world: World) -> None:
    phone = _phone()
    started = _ok(world.client.post(f"{API}/auth/start", json={"phone": phone}), 202)
    wrong = "000000" if started["dev_code"] != "000000" else "111111"
    body = {"request_id": started["request_id"], "code": wrong}
    first = world.client.post(f"{API}/auth/verify", json=body)
    assert first.status_code == 422
    assert first.json()["error"]["details"]["fields"][0]["params"]["attempts_left"] == 4
    for _ in range(4):
        world.client.post(f"{API}/auth/verify", json=body)
    # 5 urinishdan keyin to'g'ri kod ham yopiq
    ok = world.client.post(
        f"{API}/auth/verify", json={"request_id": started["request_id"], "code": started["dev_code"]}
    )
    assert ok.status_code == 404


def test_resend_limits(world: World) -> None:
    phone = _phone()
    started = _ok(world.client.post(f"{API}/auth/start", json={"phone": phone}), 202)
    assert (
        world.client.post(f"{API}/auth/start", json={"phone": phone}).status_code == 429
    )  # 60 soniya o'tmagan
    for _ in range(4):  # vaqtni surish: yana 4 marta yuboriladi (jami 5)
        _admin_sql(
            world,
            "UPDATE network.buyer_login_codes SET last_sent_at = now() - interval '2 minutes' WHERE id = $1::uuid",
            started["request_id"],
        )
        again = _ok(world.client.post(f"{API}/auth/start", json={"phone": phone}), 202)
        assert again["request_id"] == started["request_id"]
    _admin_sql(
        world,
        "UPDATE network.buyer_login_codes SET last_sent_at = now() - interval '2 minutes' WHERE id = $1::uuid",
        started["request_id"],
    )
    assert (
        world.client.post(f"{API}/auth/start", json={"phone": phone}).status_code == 429
    )  # 5 yuborishdan keyin


def test_session_auth_missing_bad_revoked_expired_and_sliding(world: World) -> None:
    assert world.client.get(f"{API}/me").status_code == 401
    assert world.client.get(f"{API}/me", headers=_auth("nope")).status_code == 401
    assert world.client.get(f"{API}/me", headers=_auth(f"{uuid4()}.abc")).status_code == 401
    token, done = _login(world)
    bad = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    resp = world.client.get(f"{API}/me", headers=_auth(bad))
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "UNAUTHENTICATED"
    # Yaroqsiz token ixtiyoriy auth'li yo'lda xato bermaydi — anonim
    assert world.client.get(f"{API}/search?q=zzz", headers=_auth(bad)).status_code == 200

    sid = token.split(".")[0]
    _admin_sql(
        world,
        "UPDATE network.buyer_sessions SET last_used_at = now() - interval '3 days', expires_at = now() + interval '10 days' WHERE id = $1::uuid",
        sid,
    )
    _ok(world.client.get(f"{API}/me", headers=_auth(token)))
    row = _admin_sql(
        world,
        "SELECT expires_at > now() + interval '50 days' AS slid FROM network.buyer_sessions WHERE id = $1::uuid",
        sid,
    )[0]
    assert row["slid"] is True  # sirpanuvchi muddat

    other, _ = _login(world)
    assert world.client.post(f"{API}/auth/logout", headers=_auth(other)).status_code == 204
    assert world.client.get(f"{API}/me", headers=_auth(other)).status_code == 401  # bekor qilingan
    assert (
        world.client.get(f"{API}/me", headers=_auth(token)).status_code == 200
    )  # boshqa sessiya ta'sirlanmadi

    _admin_sql(
        world,
        "UPDATE network.buyer_sessions SET expires_at = now() - interval '1 minute' WHERE id = $1::uuid",
        sid,
    )
    assert world.client.get(f"{API}/me", headers=_auth(token)).status_code == 401
    assert done["buyer"]["id"]


def test_records_views_and_searches_only_when_logged_in(world: World) -> None:
    cid, word, _, _ = _listed(world)
    token, done = _login(world)
    buyer_id = done["buyer"]["id"]
    anon = _ok(world.client.get(f"{API}/products/{cid}"))
    assert anon["is_favorite"] is None
    assert _count(world, "buyer_views", buyer_id) == 0
    world.client.get(f"{API}/search?q={word}")  # anonim
    assert _count(world, "buyer_searches", buyer_id) == 0

    seen = _ok(world.client.get(f"{API}/products/{cid}", headers=_auth(token)))
    assert seen["is_favorite"] is False
    world.client.get(f"{API}/products/{cid}", headers=_auth(token))  # takror — upsert, bitta qator
    world.client.get(f"{API}/search?q=", headers=_auth(token))  # bo'sh so'rov yozilmaydi
    world.client.get(f"{API}/search?q={word}&category=GPU", headers=_auth(token))
    world.client.get(
        f"{API}/search?q={word}&category=GPU", headers=_auth(token)
    )  # oxirgisi bilan bir xil — o'tkazib yuboriladi
    world.client.get(f"{API}/search?q={word}", headers=_auth(token))
    history = _ok(world.client.get(f"{API}/me/history", headers=_auth(token)))
    assert [v["canonical_id"] for v in history["views"]] == [cid]
    view = history["views"][0]
    assert view["min_price_uzs_minor"] == 500_000_000 and view["offers_count"] == 1 and view["brand"] == "MSI"
    assert [(s["query"], s["category"]) for s in history["searches"]] == [(word, None), (word, "GPU")]


def test_advisor_conversation_saved_only_when_logged_in(world: World) -> None:
    from app.platform.llm.providers.fake import FakeProvider, FakeText, FakeTools

    cid, word, _, _ = _listed(world, amount=700_000_000)
    token, done = _login(world)
    llm: FakeProvider = world.client.app.state.sales_ai.router.provider
    llm.script.clear()
    llm.requests.clear()
    for _ in range(2):
        llm.push(
            FakeTools((("market_search", {"query": word, "max_price_uzs": None, "in_stock_only": False}),)),
            FakeText("Topildi: 1 ta do'konda."),
        )
    _ok(world.client.post(f"{API}/advisor", json={"message": f"{word} bormi?"}))  # anonim
    assert _count(world, "buyer_advisor_messages", done["buyer"]["id"]) == 0
    _ok(world.client.post(f"{API}/advisor", json={"message": f"{word} bormi?"}, headers=_auth(token)))
    items = _ok(world.client.get(f"{API}/me/advisor", headers=_auth(token)))["items"]
    assert [i["role"] for i in items] == ["user", "assistant"]
    assert items[0]["text"] == f"{word} bormi?" and items[1]["text"].startswith("Topildi")
    assert items[1]["sources"][0]["canonical_id"] == cid
    assert world.client.delete(f"{API}/me/advisor", headers=_auth(token)).status_code == 204
    assert _ok(world.client.get(f"{API}/me/advisor", headers=_auth(token)))["items"] == []


def test_favorites_price_snapshot_and_unlisted(world: World) -> None:
    cid, _, shop, sku = _listed(world, amount=500_000_000)
    token, _done = _login(world)
    h = _auth(token)
    assert world.client.put(f"{API}/me/favorites/{uuid4()}", headers=h).status_code == 404  # ommaviy emas
    assert world.client.put(f"{API}/me/favorites/{cid}", headers=h).status_code == 204
    assert world.client.put(f"{API}/me/favorites/{cid}", headers=h).status_code == 204  # idempotent
    assert _ok(world.client.get(f"{API}/products/{cid}", headers=h))["is_favorite"] is True
    [fav] = _ok(world.client.get(f"{API}/me/favorites", headers=h))["items"]
    assert fav["saved_price_uzs_minor"] == 500_000_000 and fav["current_min_price_uzs_minor"] == 500_000_000
    assert fav["offers_count"] == 1 and fav["in_stock_count"] in (0, 1) and fav["title"]

    # Taklif qaytarib olindi: sevimli qoladi, hozirgi maydonlar null
    _ok(world.client.post(f"/api/v1/shop/network/offers/{sku}/withdraw", headers=_bearer(shop.owner)))
    [gone] = _ok(world.client.get(f"{API}/me/favorites", headers=h))["items"]
    assert gone["saved_price_uzs_minor"] == 500_000_000
    assert (
        gone["current_min_price_uzs_minor"] is None and gone["offers_count"] is None and gone["title"] is None
    )

    assert world.client.delete(f"{API}/me/favorites/{cid}", headers=h).status_code == 204
    assert _ok(world.client.get(f"{API}/me/favorites", headers=h))["items"] == []
    assert world.client.get(f"{API}/me/favorites").status_code == 401


def test_clear_history_and_delete_single_items(world: World) -> None:
    cid, word, _, _ = _listed(world)
    token, _done = _login(world)
    h = _auth(token)
    world.client.get(f"{API}/products/{cid}", headers=h)
    world.client.get(f"{API}/search?q={word}", headers=h)
    world.client.get(f"{API}/search?q={word}x", headers=h)
    history = _ok(world.client.get(f"{API}/me/history", headers=h))
    assert len(history["searches"]) == 2 and len(history["views"]) == 1
    sid = history["searches"][0]["id"]
    assert world.client.delete(f"{API}/me/history/searches/{sid}", headers=h).status_code == 204
    assert len(_ok(world.client.get(f"{API}/me/history", headers=h))["searches"]) == 1
    assert world.client.delete(f"{API}/me/history/views/{cid}", headers=h).status_code == 204
    assert _ok(world.client.get(f"{API}/me/history", headers=h))["views"] == []
    world.client.get(f"{API}/products/{cid}", headers=h)
    assert world.client.delete(f"{API}/me/history", headers=h).status_code == 204
    assert _ok(world.client.get(f"{API}/me/history", headers=h)) == {"views": [], "searches": []}


def test_buyer_cannot_touch_another_buyers_data(world: World) -> None:
    cid, word, _, _ = _listed(world)
    a, a_done = _login(world)
    b, _ = _login(world)
    world.client.get(f"{API}/products/{cid}", headers=_auth(a))
    world.client.get(f"{API}/search?q={word}", headers=_auth(a))
    world.client.put(f"{API}/me/favorites/{cid}", headers=_auth(a))
    a_search = _ok(world.client.get(f"{API}/me/history", headers=_auth(a)))["searches"][0]["id"]
    assert _ok(world.client.get(f"{API}/me/history", headers=_auth(b))) == {"views": [], "searches": []}
    assert _ok(world.client.get(f"{API}/me/favorites", headers=_auth(b)))["items"] == []
    # B, A ning yozuvlarini o'chirmoqchi: 204, lekin A'da hammasi joyida
    assert world.client.delete(f"{API}/me/history/searches/{a_search}", headers=_auth(b)).status_code == 204
    assert world.client.delete(f"{API}/me/history/views/{cid}", headers=_auth(b)).status_code == 204
    assert world.client.delete(f"{API}/me/favorites/{cid}", headers=_auth(b)).status_code == 204
    assert world.client.delete(f"{API}/me/history", headers=_auth(b)).status_code == 204
    assert _count(world, "buyer_views", a_done["buyer"]["id"]) == 1
    assert _count(world, "buyer_searches", a_done["buyer"]["id"]) == 1
    assert _count(world, "buyer_favorites", a_done["buyer"]["id"]) == 1


def test_delete_account_cascades(world: World) -> None:
    cid, word, _, _ = _listed(world)
    token, done = _login(world)
    h = _auth(token)
    buyer_id = done["buyer"]["id"]
    world.client.get(f"{API}/products/{cid}", headers=h)
    world.client.get(f"{API}/search?q={word}", headers=h)
    world.client.put(f"{API}/me/favorites/{cid}", headers=h)
    _admin_sql(
        world,
        "INSERT INTO network.buyer_advisor_messages (id, buyer_id, role, text) VALUES (gen_random_uuid(), $1::uuid, 'user', 'salom')",
        buyer_id,
    )
    for table in CHILD_TABLES:
        assert _count(world, table, buyer_id) >= 1, table
    assert world.client.delete(f"{API}/me", headers=h).status_code == 204
    for table in CHILD_TABLES:
        assert _count(world, table, buyer_id) == 0, table
    assert (
        _admin_sql(world, "SELECT count(*) AS n FROM network.buyers WHERE id = $1::uuid", buyer_id)[0]["n"]
        == 0
    )
    assert world.client.get(f"{API}/me", headers=h).status_code == 401


def test_history_caps_and_cleanup(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, word, _, _ = _listed(world)
    token, done = _login(world)
    h = _auth(token)
    buyer_id = done["buyer"]["id"]
    monkeypatch.setattr(buyers_module, "MAX_SEARCHES", 3)
    monkeypatch.setattr(buyers_module, "MAX_VIEWS", 2)
    for i in range(5):
        world.client.get(f"{API}/search?q={word}{i}", headers=h)
    searches = _ok(world.client.get(f"{API}/me/history", headers=h))["searches"]
    assert [s["query"] for s in searches] == [f"{word}4", f"{word}3", f"{word}2"]  # eng yangi 3 ta
    for _ in range(3):  # ommaviy bo'lmagan eski ko'rishlar — kesiladi
        _admin_sql(
            world,
            "INSERT INTO network.buyer_views (buyer_id, canonical_id, viewed_at) VALUES ($1::uuid, gen_random_uuid(), now() - interval '1 day')",
            buyer_id,
        )
    world.client.get(f"{API}/products/{cid}", headers=h)
    assert _count(world, "buyer_views", buyer_id) == 2

    # Kunlik tozalash
    _admin_sql(
        world,
        "UPDATE network.buyer_login_codes SET created_at = now() - interval '2 days' WHERE phone_hash IS NOT NULL AND id IN (SELECT id FROM network.buyer_login_codes ORDER BY created_at DESC LIMIT 1)",
    )
    _admin_sql(
        world,
        "UPDATE network.buyer_sessions SET revoked_at = now() - interval '8 days' WHERE id = $1::uuid",
        token.split(".")[0],
    )
    _job(world, "buyer_cleanup")
    old = _admin_sql(
        world,
        "SELECT count(*) AS n FROM network.buyer_login_codes WHERE created_at < now() - interval '1 day'",
    )
    assert old[0]["n"] == 0
    left = _admin_sql(
        world, "SELECT count(*) AS n FROM network.buyer_sessions WHERE id = $1::uuid", token.split(".")[0]
    )
    assert left[0]["n"] == 0
