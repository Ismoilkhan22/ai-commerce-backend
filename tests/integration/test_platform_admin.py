"""Platforma paneli, A bosqich (business/15): bosh sahifa, qidiruv, tahrir, shop kartochkasi, jurnal.

Baza testlar orasida umumiy — sanoqlar oldin/keyin farqi bilan, tartib esa shu testning shoplari
ichida tekshiriladi.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.platform.staff.cli import create_platform_admin
from tests.integration.helpers import (
    World,
    _bearer,
    _code,
    _idem,
    _phone,
    _sql,
    _tin,
)

pytestmark = pytest.mark.integration

SUPPORT_PASSWORD = "Support-parol-2026!"


def _new_shop(w: World, name: str | None = None, owner_phone: str | None = None) -> dict[str, Any]:
    """Shop yaratadi, ega taklifni QABUL QILMAYDI (havola holatlarini tekshirish uchun)."""
    response = w.client.post(
        "/api/v1/platform/shops",
        json={
            "slug": f"shop-{uuid4().hex[:8]}",
            "name": name or f"Shop {uuid4().hex[:6]}",
            "tin": _tin(),
            "owner_phone": owner_phone or _phone(),
            "owner_full_name": "Ega Egayev",
        },
        headers=_bearer(w.admin_token, **_idem()),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _submitted_shop(w: World) -> dict[str, Any]:
    s = w.create_shop()
    w.branch(s["owner_token"])
    submitted = w.client.post(
        "/api/v1/shop/profile/submit-for-verification", headers=_bearer(s["owner_token"], **_idem())
    )
    assert submitted.status_code == 200, submitted.text
    return s


def _dashboard(w: World) -> dict[str, Any]:
    response = w.client.get("/api/v1/platform/dashboard", headers=_bearer(w.admin_token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def _support_token(w: World) -> tuple[str, str]:
    phone = _phone()
    asyncio.run(
        create_platform_admin(w.settings, phone, "Yordam Xodimi", SUPPORT_PASSWORD, "PLATFORM_SUPPORT")
    )
    response = w.client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": SUPPORT_PASSWORD, "audience": "platform"}
    )
    assert response.status_code == 200, response.text
    me = w.client.get("/api/v1/auth/me", headers=_bearer(response.json()["access_token"])).json()
    return str(response.json()["access_token"]), str(me["principal_id"])


def test_dashboard_counts_queue_order_and_activity(world: World) -> None:
    before = _dashboard(world)
    first, second = _submitted_shop(world), _submitted_shop(world)
    # Birinchisi 3 kun oldin yuborilgan bo'lsin
    _sql(
        world.urls.admin,
        "UPDATE platform.transition_log SET occurred_at = now() - interval '3 days' "
        "WHERE entity_id = $1 AND command = 'SUBMIT_FOR_VERIFICATION'",
        UUID(first["shop"]["id"]),
    )
    after = _dashboard(world)

    pending_before = before["counts_by_status"]["PENDING_VERIFICATION"]
    assert after["counts_by_status"]["PENDING_VERIFICATION"] == pending_before + 2
    assert set(after["counts_by_status"]) == {
        "DRAFT",
        "PENDING_VERIFICATION",
        "ACTIVE",
        "SUSPENDED",
        "CLOSED",
    }
    assert after["new_shops_7d"] >= before["new_shops_7d"] + 2
    assert after["new_shops_30d"] >= after["new_shops_7d"]

    queue = [i for i in after["review_queue"] if i["shop_id"] in {first["shop"]["id"], second["shop"]["id"]}]
    assert [i["shop_id"] for i in queue] == [first["shop"]["id"], second["shop"]["id"]]  # eng eskisi birinchi
    assert queue[0]["waiting_days"] == 3 and queue[1]["waiting_days"] == 0
    assert queue[0]["owner_name"] == "Ali Valiyev"
    assert (queue[0]["branch_count"], queue[0]["staff_count"]) == (1, 1)

    activity = after["recent_activity"]
    assert len(activity) <= 10
    assert all(a["actor_type"] == "PLATFORM" and not a["action"].startswith("auth.") for a in activity)
    created = next(
        a for a in activity if a["action"] == "shops.shop.created" and a["shop_id"] == second["shop"]["id"]
    )
    assert (created["actor_name"], created["shop_name"]) == ("Platforma Admin", "TechPC")


def test_dashboard_pending_owner_invite_states(world: World) -> None:
    expired, expiring, fresh = _new_shop(world), _new_shop(world), _new_shop(world)
    _sql(
        world.urls.admin,
        "UPDATE platform.invitations SET expires_at = now() - interval '1 minute' WHERE membership_id = $1",
        UUID(expired["owner_membership_id"]),
    )
    _sql(
        world.urls.admin,
        "UPDATE platform.invitations SET expires_at = now() + interval '2 hours' WHERE membership_id = $1",
        UUID(expiring["owner_membership_id"]),
    )
    accepted = world.create_shop()  # ega kirgan — ro'yxatda bo'lmasligi kerak

    pending = {p["shop_id"]: p for p in _dashboard(world)["pending_owners"]}
    assert pending[expired["shop"]["id"]]["invite_state"] == "expired"
    assert pending[expiring["shop"]["id"]]["invite_state"] == "expiring"
    assert pending[expiring["shop"]["id"]]["membership_id"] == expiring["owner_membership_id"]
    assert pending[expiring["shop"]["id"]]["owner_name"] == "Ega Egayev"
    assert fresh["shop"]["id"] not in pending  # havola hali amalda — aralashish shart emas
    assert accepted["shop"]["id"] not in pending


def test_dashboard_pilot_day_and_days_left(world: World) -> None:
    s = _submitted_shop(world)
    activated = world.client.post(
        f"/api/v1/platform/shops/{s['shop']['id']}/activate", headers=_bearer(world.admin_token, **_idem())
    )
    assert activated.status_code == 200, activated.text
    _sql(
        world.urls.admin,
        "UPDATE platform.shops SET activated_at = now() - interval '26 days' WHERE id = $1",
        UUID(s["shop"]["id"]),
    )
    pilot = next(p for p in _dashboard(world)["pilots"] if p["shop_id"] == s["shop"]["id"])
    assert (pilot["day"], pilot["days_left"], pilot["ending_soon"]) == (27, 3, True)


def test_shop_list_search_filter_and_pagination(world: World) -> None:
    marker = uuid4().hex[:6]
    owner_phone = _phone()
    a = _new_shop(world, name=f"Qidiruv {marker} Alfa", owner_phone=owner_phone)
    b = _submitted_shop(world)
    c = _new_shop(world, name=f"Qidiruv {marker} Beta")
    admin = _bearer(world.admin_token)

    by_name = world.client.get(
        "/api/v1/platform/shops", params={"q": f"qidiruv {marker}"}, headers=admin
    ).json()
    assert by_name["total"] == 2 and {i["id"] for i in by_name["items"]} == {a["shop"]["id"], c["shop"]["id"]}
    item = next(i for i in by_name["items"] if i["id"] == a["shop"]["id"])
    assert (item["owner_name"], item["owner_status"], item["staff_count"], item["branch_count"]) == (
        "Ega Egayev",
        "INVITED",
        1,
        0,
    )
    assert item["last_activity_at"] is None

    # Telefon istalgan ko'rinishda: "90 123-45-67"
    local = owner_phone.removeprefix("+998")
    pretty = f"{local[:2]} {local[2:5]}-{local[5:7]}-{local[7:]}"
    by_phone = world.client.get("/api/v1/platform/shops", params={"q": pretty}, headers=admin).json()
    assert [i["id"] for i in by_phone["items"]] == [a["shop"]["id"]]

    by_status = world.client.get(
        "/api/v1/platform/shops", params={"status": ["PENDING_VERIFICATION"], "limit": 100}, headers=admin
    ).json()
    assert all(i["status"] == "PENDING_VERIFICATION" for i in by_status["items"])
    assert b["shop"]["id"] in {i["id"] for i in by_status["items"]}
    reviewed = next(i for i in by_status["items"] if i["id"] == b["shop"]["id"])
    assert reviewed["last_activity_at"] is not None  # ega kirgan

    page = world.client.get(
        "/api/v1/platform/shops",
        params={"q": f"qidiruv {marker}", "limit": 1, "offset": 1, "sort": "name"},
        headers=admin,
    ).json()
    assert (page["total"], [i["id"] for i in page["items"]]) == (2, [c["shop"]["id"]])  # Alfa, Beta → 2-chisi


def test_platform_edits_shop_with_reason_and_if_match(world: World) -> None:
    s, other = _new_shop(world), _new_shop(world)
    shop_id = s["shop"]["id"]
    admin = _bearer(world.admin_token)
    card = world.client.get(f"/api/v1/platform/shops/{shop_id}", headers=admin)
    assert card.headers["ETag"] == '"v1"'
    body = {"name": "Tuzatilgan nom", "legal_name": "Yangi MCHJ", "tin": _tin(), "default_locale": "ru"}
    url = f"/api/v1/platform/shops/{shop_id}"

    assert (
        _code(world.client.patch(url, json={**body, "reason": "Shartnoma"}, headers=admin))
        == "INVALID_REQUEST"
    )
    blank = world.client.patch(url, json={**body, "reason": "  "}, headers={**admin, "If-Match": '"v1"'})
    assert blank.json()["error"]["details"]["fields"][0] == {
        "field": "reason",
        "code": "required",
        "params": {},
    }
    short = world.client.patch(url, json={**body, "reason": " ab "}, headers={**admin, "If-Match": '"v1"'})
    assert short.json()["error"]["details"]["fields"][0] == {
        "field": "reason",
        "code": "min_length",
        "params": {"min": 3},
    }
    duplicate = world.client.patch(
        url,
        json={**body, "tin": other["shop"]["tin"], "reason": "Shartnoma"},
        headers={**admin, "If-Match": '"v1"'},
    )
    assert duplicate.json()["error"]["details"]["fields"][0] == {
        "field": "tin",
        "code": "not_unique",
        "params": {},
    }

    saved = world.client.patch(
        url, json={**body, "reason": "Shartnoma bo'yicha"}, headers={**admin, "If-Match": '"v1"'}
    )
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert (out["name"], out["legal_name"], out["default_locale"], out["slug"]) == (
        "Tuzatilgan nom",
        "Yangi MCHJ",
        "ru",
        s["shop"]["slug"],
    )
    assert saved.headers["ETag"] == '"v2"' and out["owners"][0]["full_name"] == "Ega Egayev"
    stale = world.client.patch(url, json={**body, "reason": "Yana"}, headers={**admin, "If-Match": '"v1"'})
    assert _code(stale) == "VERSION_CONFLICT"

    # PATCH: yuborilmagan legal_name va default_locale o'z qiymatida qoladi
    partial = world.client.patch(
        url,
        json={"name": "Faqat nom", "tin": body["tin"], "reason": "Nom tuzatildi"},
        headers={**admin, "If-Match": '"v2"'},
    )
    assert partial.status_code == 200, partial.text
    kept = partial.json()
    assert (kept["name"], kept["legal_name"], kept["default_locale"]) == ("Faqat nom", "Yangi MCHJ", "ru")

    rows = _sql(
        world.urls.admin,
        "SELECT shop_id, reason, diff FROM audit.audit_entries "
        "WHERE action = 'shops.shop.updated' AND entity_id = $1",
        UUID(shop_id),
    )
    rows = sorted(rows, key=lambda r: r["reason"] != "Shartnoma bo'yicha")
    assert (
        len(rows) == 2 and rows[0]["shop_id"] == UUID(shop_id) and rows[0]["reason"] == "Shartnoma bo'yicha"
    )
    assert (
        '"tin": {"changed": true}' in rows[0]["diff"] and body["tin"] not in rows[0]["diff"]
    )  # STIR qiymati yo'q
    assert set(json.loads(rows[1]["diff"])) == {"name"}  # faqat haqiqatan o'zgargan maydon


def test_support_role_reads_but_cannot_change(world: World) -> None:
    s = _submitted_shop(world)
    support, _ = _support_token(world)
    headers = _bearer(support)
    shop_id = s["shop"]["id"]
    for path in (
        "/dashboard",
        "/shops",
        f"/shops/{shop_id}",
        f"/shops/{shop_id}/members",
        f"/shops/{shop_id}/audit",
    ):
        assert world.client.get(f"/api/v1/platform{path}", headers=headers).status_code == 200, path
    edit = world.client.patch(
        f"/api/v1/platform/shops/{shop_id}",
        json={"name": "X nom", "tin": _tin(), "reason": "test"},
        headers={**headers, "If-Match": '"v1"'},
    )
    activate = world.client.post(f"/api/v1/platform/shops/{shop_id}/activate", headers={**headers, **_idem()})
    create = world.client.post(
        "/api/v1/platform/shops",
        json={
            "slug": f"s-{uuid4().hex[:8]}",
            "name": "Nom",
            "tin": _tin(),
            "owner_phone": _phone(),
            "owner_full_name": "A B",
        },
        headers={**headers, **_idem()},
    )
    for response in (edit, activate, create):
        assert (response.status_code, _code(response)) == (403, "FORBIDDEN")


def test_shop_card_members_branches_history_and_audit(world: World) -> None:
    s = _submitted_shop(world)
    shop_id = s["shop"]["id"]
    world.invite(s["owner_token"], "SALES")
    activated = world.client.post(
        f"/api/v1/platform/shops/{shop_id}/activate", headers=_bearer(world.admin_token, **_idem())
    )
    assert activated.status_code == 200
    admin = _bearer(world.admin_token)

    members = world.client.get(f"/api/v1/platform/shops/{shop_id}/members", headers=admin).json()["items"]
    assert [m["role"] for m in members] == ["OWNER", "SALES"]
    assert members[0]["full_name"] == "Ali Valiyev" and members[0]["status"] == "ACTIVE"
    assert {"membership_id", "phone", "branch_scope", "last_login_at", "activated_at"} <= set(members[0])

    branches = world.client.get(f"/api/v1/platform/shops/{shop_id}/branches", headers=admin).json()["items"]
    assert [b["name"] for b in branches] == ["Chilonzor"]

    history = world.client.get(f"/api/v1/platform/shops/{shop_id}/history", headers=admin).json()["items"]
    assert [h["command"] for h in history] == ["ACTIVATE", "SUBMIT_FOR_VERIFICATION"]  # yangisi birinchi
    assert (history[0]["actor_type"], history[0]["actor_name"], history[0]["to_status"]) == (
        "PLATFORM",
        "Platforma Admin",
        "ACTIVE",
    )
    assert history[1]["actor_name"] == "Ali Valiyev"

    audit = world.client.get(f"/api/v1/platform/shops/{shop_id}/audit", headers=admin)
    page = audit.json()
    actions = [i["action"] for i in page["items"]]
    assert "shops.shop.activate" in actions and "shops.shop.created" in actions
    assert page["total"] >= len(page["items"])
    activation = next(i for i in page["items"] if i["action"] == "shops.shop.activate")
    assert (activation["shop_id"], activation["changed_fields"], activation["actor_name"]) == (
        shop_id,
        ["status"],
        "Platforma Admin",
    )
    assert (
        all("diff" not in i for i in page["items"]) and "PENDING_VERIFICATION" not in audit.text
    )  # qiymatlarsiz

    missing = world.client.get(f"/api/v1/platform/shops/{uuid4()}/members", headers=admin)
    assert (missing.status_code, _code(missing)) == (404, "NOT_FOUND")


def test_platform_activity_log_filters(world: World) -> None:
    s = _new_shop(world)
    shop_id = s["shop"]["id"]
    admin = _bearer(world.admin_token)
    me = world.client.get("/api/v1/auth/me", headers=admin).json()
    world.client.patch(
        f"/api/v1/platform/shops/{shop_id}",
        json={"name": "Jurnal shop", "tin": s["shop"]["tin"], "reason": "Nom xato"},
        headers={**admin, "If-Match": '"v1"'},
    )
    _, support_id = _support_token(world)

    by_shop = world.client.get("/api/v1/platform/audit", params={"shop_id": shop_id}, headers=admin).json()
    assert by_shop["total"] >= 2 and all(i["shop_id"] == shop_id for i in by_shop["items"])
    assert {i["action"] for i in by_shop["items"]} >= {"shops.shop.created", "shops.shop.updated"}
    updated = next(i for i in by_shop["items"] if i["action"] == "shops.shop.updated")
    assert (updated["reason"], updated["changed_fields"], updated["shop_name"]) == (
        "Nom xato",
        ["name"],
        "Jurnal shop",
    )

    by_action = world.client.get(
        "/api/v1/platform/audit",
        params={"action": "shops.shop.upd", "actor_id": me["principal_id"]},
        headers=admin,
    ).json()
    assert by_action["items"] and all(i["action"] == "shops.shop.updated" for i in by_action["items"])
    assert all(i["actor_type"] == "PLATFORM" for i in by_action["items"])

    future = world.client.get(
        "/api/v1/platform/audit", params={"date_from": "2999-01-01T00:00:00Z"}, headers=admin
    ).json()
    assert (future["total"], future["items"]) == (0, [])
    nobody = world.client.get(
        "/api/v1/platform/audit", params={"actor_id": support_id, "action": "shops."}, headers=admin
    ).json()
    assert nobody["total"] == 0  # yordam xodimi hech narsa o'zgartirmagan


def test_owner_cannot_reach_platform_endpoints(world: World) -> None:
    s = world.create_shop()
    response = world.client.get("/api/v1/platform/dashboard", headers=_bearer(s["owner_token"]))
    assert response.status_code == 401  # shop paneli tokeni platforma panelida ishlamaydi
