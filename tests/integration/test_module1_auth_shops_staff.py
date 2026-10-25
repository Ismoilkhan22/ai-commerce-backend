"""1-modul: auth, shop va xodimlar — qabul mezonlari (27 §0, 1-modul kartasi).
Haqiqiy PostgreSQL, HTTP orqali.

TC-001/TC-ISO (shoplar izolyatsiyasi), TC-025 (o'chirilgan xodim), UAT-M01…M03, brute force,
refresh rotatsiyasi va qayta ishlatishni aniqlash, parol tiklash, yopilgan shop, rate limit.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.integration.helpers import (
    ADMIN_PASSWORD,
    PASSWORD,
    SHOP,
    World,
    _bearer,
    _code,
    _idem,
    _phone,
    _sql,
    _tin,
)

pytestmark = pytest.mark.integration

# ------------------------------------------------------------------ shop hayoti


def test_shop_lifecycle_from_creation_to_activation(world: World) -> None:  # UAT-M01, FSM-01
    c, s = world.client, world.create_shop()
    owner = _bearer(s["owner_token"])
    me = c.get("/api/v1/auth/me", headers=owner).json()
    assert (me["audience"], me["role"], me["shop"]["status"]) == ("shop", "OWNER", "DRAFT")
    assert "staff.member.invite" in me["permissions"]

    # Qoralama holatida ham ega sozlay oladi (onboarding, business/13)
    world.branch(s["owner_token"])
    submitted = c.post(
        "/api/v1/shop/profile/submit-for-verification", headers=_bearer(s["owner_token"], **_idem())
    )
    assert submitted.json()["status"] == "PENDING_VERIFICATION"
    assert (
        c.post(
            f"/api/v1/platform/shops/{s['shop']['id']}/activate", headers=_bearer(s["owner_token"], **_idem())
        ).status_code
        == 401
    )  # ega platforma tokeni emas
    activated = c.post(
        f"/api/v1/platform/shops/{s['shop']['id']}/activate", headers=_bearer(world.admin_token, **_idem())
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE" and activated.json()["activated_at"]

    rows = _sql(
        world.urls.migrator,
        "SELECT command FROM platform.transition_log WHERE entity_id = $1 ORDER BY occurred_at",
        UUID(s["shop"]["id"]),
    )
    assert [r["command"] for r in rows] == ["SUBMIT_FOR_VERIFICATION", "ACTIVATE"]


def test_suspend_requires_reason_and_closed_shop_blocks_panel(world: World) -> None:
    c, s = world.client, world.create_shop()
    shop_id, admin = s["shop"]["id"], _bearer(world.admin_token, **_idem())
    c.post("/api/v1/shop/profile/submit-for-verification", headers=_bearer(s["owner_token"], **_idem()))
    c.post(f"/api/v1/platform/shops/{shop_id}/activate", headers=admin)
    assert (
        c.post(
            f"/api/v1/platform/shops/{shop_id}/suspend",
            json={},
            headers=_bearer(world.admin_token, **_idem()),
        ).status_code
        == 422
    )
    assert (
        c.post(
            f"/api/v1/platform/shops/{shop_id}/close",
            json={"reason": "Shop bilan kelishildi"},
            headers=_bearer(world.admin_token, **_idem()),
        ).json()["status"]
        == "CLOSED"
    )
    blocked = c.get("/api/v1/shop/profile", headers=_bearer(s["owner_token"]))
    assert (blocked.status_code, _code(blocked)) == (409, "SHOP_NOT_ACTIVE")
    login = c.post(
        "/api/v1/auth/login", json={"phone": s["owner_phone"], "password": PASSWORD, "audience": "shop"}
    )
    assert _code(login) == "SHOP_NOT_ACTIVE"


def test_create_shop_replay_returns_same_shop_and_fresh_link(world: World) -> None:
    c, key = world.client, _idem()
    body = {
        "slug": f"shop-{uuid4().hex[:8]}",
        "name": "Replay",
        "tin": _tin(),
        "owner_phone": _phone(),
        "owner_full_name": "Ega Egayev",
    }
    first = c.post("/api/v1/platform/shops", json=body, headers=_bearer(world.admin_token, **key)).json()
    second = c.post("/api/v1/platform/shops", json=body, headers=_bearer(world.admin_token, **key)).json()
    assert first["shop"]["id"] == second["shop"]["id"]
    assert first["owner_invite"]["url"] != second["owner_invite"]["url"]  # havola bazada saqlanmagan
    old = c.post(
        f"/api/v1/auth/invites/{first['owner_invite']['url'].rsplit('/', 1)[1]}/accept",
        json={"password": PASSWORD},
    )
    assert (old.status_code, old.json()["error"]["details"]) == (404, {"reason": "revoked"})
    world.accept(second["owner_invite"]["url"])
    stored = _sql(
        world.urls.migrator,
        "SELECT response_body::text AS b FROM platform.idempotency_keys WHERE key = $1",
        key["Idempotency-Key"],
    )
    assert "/invite/" not in stored[0]["b"]  # sir (havola) bazaga yozilmagan


def test_duplicate_tin_and_owner_phone_rejected(world: World) -> None:
    s = world.create_shop()
    response = world.client.post(
        "/api/v1/platform/shops",
        json={
            "slug": f"shop-{uuid4().hex[:8]}",
            "name": "Dup",
            "tin": s["shop"]["tin"],
            "owner_phone": _phone(),
            "owner_full_name": "Boshqa Ega",
        },
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0] == {
        "field": "tin",
        "code": "not_unique",
        "params": {},
    }


# ----------------------------------------------------------------- xodimlar va rollar


def test_roles_limit_what_staff_can_do(world: World) -> None:  # business/04, DEC-131
    c, s = world.client, world.create_shop()
    _, _, manager = world.invite(s["owner_token"], "MANAGER")
    _, _, sales = world.invite(s["owner_token"], "SALES")
    assert c.get("/api/v1/shop/members", headers=_bearer(manager)).status_code == 200  # menejer ko'radi
    denied = c.post(
        "/api/v1/shop/members/invites",
        json={"phone": _phone(), "full_name": "X Y", "role": "SALES"},
        headers=_bearer(manager, **_idem()),
    )
    assert (denied.status_code, _code(denied)) == (403, "FORBIDDEN")
    assert c.get("/api/v1/shop/members", headers=_bearer(sales)).status_code == 403
    assert c.get("/api/v1/shop/profile", headers=_bearer(sales)).status_code == 403
    assert (
        c.patch(
            "/api/v1/shop/policies", json={}, headers=_bearer(manager, **{"If-Match": '"v1"'})
        ).status_code
        == 403
    )


def test_branch_scoped_staff_sees_only_own_branches(world: World) -> None:  # UAT-M03
    c, s = world.client, world.create_shop()
    chilonzor, yunusobod = world.branch(s["owner_token"]), world.branch(s["owner_token"], "Yunusobod")
    _, member_id, manager = world.invite(
        s["owner_token"], "MANAGER", branch_scope="SELECTED", branch_ids=[chilonzor["id"]]
    )
    me = c.get("/api/v1/auth/me", headers=_bearer(manager)).json()
    assert me["branch_ids"] == [chilonzor["id"]]
    visible = [b["id"] for b in c.get("/api/v1/shop/branches", headers=_bearer(manager)).json()["items"]]
    assert visible == [chilonzor["id"]] and yunusobod["id"] not in visible

    closed = c.post(
        f"/api/v1/shop/branches/{yunusobod['id']}/close", headers=_bearer(s["owner_token"], **_idem())
    )
    assert closed.json()["status"] == "CLOSED"
    edit = c.patch(
        f"/api/v1/shop/branches/{yunusobod['id']}",
        json={"name": "Yangi", "address": "Manzil 1"},
        headers=_bearer(s["owner_token"], **{"If-Match": f'"v{closed.json()["version"]}"'}),
    )
    assert _code(edit) == "BRANCH_CLOSED"
    assign = c.put(
        f"/api/v1/shop/members/{member_id}/roles",
        json={"role": "MANAGER", "branch_scope": "SELECTED", "branch_ids": [yunusobod["id"]]},
        headers=_bearer(s["owner_token"], **{"If-Match": '"v2"'}),
    )
    assert assign.json()["error"]["details"]["fields"][0]["code"] == "invalid_choice"  # yopiq filial


def test_disabled_member_is_locked_out_immediately(world: World) -> None:  # TC-025
    c, s = world.client, world.create_shop()
    _, member_id, sales = world.invite(s["owner_token"], "SALES")
    assert c.get("/api/v1/auth/me", headers=_bearer(sales)).status_code == 200
    disabled = c.post(
        f"/api/v1/shop/members/{member_id}/disable",
        json={"reason": "Ishdan ketdi"},
        headers=_bearer(s["owner_token"], **_idem()),
    )
    assert disabled.json()["status"] == "DISABLED"
    assert (
        c.get("/api/v1/auth/me", headers=_bearer(sales)).status_code == 401
    )  # access token hali "yangi", lekin
    assert (
        c.post("/api/v1/auth/refresh", json=SHOP).status_code == 401
    )  # cookie oxirgi kirgan xodimniki — u ham bekor


def test_last_owner_cannot_be_removed_or_demoted(world: World) -> None:  # UAT-M02
    c, s = world.client, world.create_shop()
    owner, owner_id = s["owner_token"], s["owner_membership_id"]
    response = c.post(f"/api/v1/shop/members/{owner_id}/disable", json={}, headers=_bearer(owner, **_idem()))
    assert (response.status_code, _code(response)) == (409, "LAST_OWNER_REQUIRED")
    demote = c.put(
        f"/api/v1/shop/members/{owner_id}/roles",
        json={"role": "MANAGER"},
        headers=_bearer(owner, **{"If-Match": '"v2"'}),
    )
    assert _code(demote) == "LAST_OWNER_REQUIRED"
    world.invite(owner, "OWNER")  # ikkinchi ega bo'lsa — birinchisini o'chirish mumkin
    assert (
        c.post(
            f"/api/v1/shop/members/{owner_id}/disable", json={}, headers=_bearer(owner, **_idem())
        ).status_code
        == 200
    )


def test_two_owners_disabling_each_other_concurrently_leave_one(world: World) -> None:
    from app.platform.staff.services.staff_service import StaffService
    from app.shared.db.session import Database
    from app.shared.errors.base import LastOwnerRequiredError
    from app.shared.types.actor import ActorContext

    s = world.create_shop()
    _, second_id, _ = world.invite(s["owner_token"], "OWNER")
    shop_id, first_id = UUID(s["shop"]["id"]), UUID(s["owner_membership_id"])
    staff: StaffService = world.client.app.state.staff_service  # type: ignore[attr-defined]

    def owner(membership_id: UUID) -> ActorContext:
        return ActorContext(
            actor_type="STAFF", actor_id=uuid4(), shop_id=shop_id, surface="shop", membership_id=membership_id
        )

    async def race() -> list[Any]:
        database = Database(world.settings.database_config())

        async def disable(actor_member: UUID, target: UUID) -> str:
            async with database.transaction(shop_id) as db:
                await staff.disable(db, owner(actor_member), target, None)
            return "ok"

        try:
            return await asyncio.gather(
                disable(first_id, UUID(second_id)), disable(UUID(second_id), first_id), return_exceptions=True
            )
        finally:
            await database.dispose()

    results = asyncio.run(race())
    assert results.count("ok") == 1
    assert sum(isinstance(r, LastOwnerRequiredError) for r in results) == 1
    # Tekshiruv superuser bilan: FORCE RLS migrator'ga ham ta'sir qiladi (kontekstsiz 0 qator)
    active = _sql(
        world.urls.admin,
        "SELECT count(*) AS n FROM platform.memberships WHERE shop_id = $1 "
        "AND role = 'OWNER' AND status = 'ACTIVE'",
        shop_id,
    )
    assert active[0]["n"] == 1


def test_invite_with_registered_phone_rejected(world: World) -> None:
    c, s = world.client, world.create_shop()
    other = world.create_shop()
    response = c.post(
        "/api/v1/shop/members/invites",
        json={"phone": other["owner_phone"], "full_name": "Ikki Shop", "role": "SALES"},
        headers=_bearer(s["owner_token"], **_idem()),
    )
    assert response.json()["error"]["details"]["fields"][0] == {
        "field": "phone",
        "code": "not_unique",
        "params": {},
    }


# --------------------------------------------------------------- izolyatsiya (TC-ISO)


def test_shop_a_cannot_touch_shop_b(world: World) -> None:  # TC-001, TC-ISO-01
    c = world.client
    a, b = world.create_shop(), world.create_shop()
    _, b_member, _ = world.invite(b["owner_token"], "SALES")
    b_branch = world.branch(b["owner_token"])
    a_owner = _bearer(a["owner_token"])

    members = [m["id"] for m in c.get("/api/v1/shop/members", headers=a_owner).json()["items"]]
    assert b_member not in members and b["owner_membership_id"] not in members
    for response in (
        c.put(
            f"/api/v1/shop/members/{b_member}/roles",
            json={"role": "MANAGER"},
            headers={**a_owner, "If-Match": '"v2"'},
        ),
        c.post(f"/api/v1/shop/members/{b_member}/disable", json={}, headers={**a_owner, **_idem()}),
        c.post(f"/api/v1/shop/members/{b_member}/password-reset", headers={**a_owner, **_idem()}),
        c.patch(
            f"/api/v1/shop/branches/{b_branch['id']}",
            json={"name": "Buzish", "address": "Manzil 1"},
            headers={**a_owner, "If-Match": '"v1"'},
        ),
        c.post(f"/api/v1/shop/branches/{b_branch['id']}/close", headers={**a_owner, **_idem()}),
    ):
        assert (response.status_code, _code(response)) == (404, "NOT_FOUND"), response.text
    assert all(
        br["id"] != b_branch["id"] for br in c.get("/api/v1/shop/branches", headers=a_owner).json()["items"]
    )


def test_tokens_are_bound_to_their_panel(world: World) -> None:
    c, s = world.client, world.create_shop()
    assert c.get("/api/v1/platform/shops", headers=_bearer(s["owner_token"])).status_code == 401
    assert c.get("/api/v1/shop/profile", headers=_bearer(world.admin_token)).status_code == 401
    assert c.get("/api/v1/shop/profile").status_code == 401
    assert c.get("/api/v1/shop/profile", headers=_bearer("not-a-jwt")).status_code == 401


def test_rls_hides_memberships_and_sessions_without_context(world: World) -> None:  # TC-ISO-08
    a, b = world.create_shop(), world.create_shop()
    runtime = world.urls.runtime

    async def check() -> tuple[int, int, set[str]]:
        conn = await asyncpg.connect(runtime.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            no_ctx_members = await conn.fetchval("SELECT count(*) FROM platform.memberships")
            no_ctx_sessions = await conn.fetchval("SELECT count(*) FROM platform.sessions")
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", a["shop"]["id"])
                shops = {
                    str(r["shop_id"]) for r in await conn.fetch("SELECT shop_id FROM platform.memberships")
                }
            return no_ctx_members, no_ctx_sessions, shops
        finally:
            await conn.close()

    members, sessions, visible_shops = asyncio.run(check())
    assert (members, sessions) == (0, 0)  # kontekst yo'q — hech narsa (fail closed)
    assert visible_shops == {a["shop"]["id"]} and b["shop"]["id"] not in visible_shops


# ------------------------------------------------------------------------ auth


def test_brute_force_locks_account(world: World) -> None:
    c, s = world.client, world.create_shop()
    for _ in range(5):
        wrong = c.post(
            "/api/v1/auth/login",
            json={"phone": s["owner_phone"], "password": "noto'g'ri-parol", "audience": "shop"},
        )
        assert _code(wrong) == "UNAUTHENTICATED"
    locked = c.post(
        "/api/v1/auth/login", json={"phone": s["owner_phone"], "password": PASSWORD, "audience": "shop"}
    )  # to'g'ri parol ham
    assert (locked.status_code, _code(locked)) == (429, "RATE_LIMITED")
    assert locked.json()["error"]["details"]["retry_after_seconds"] > 0
    failed = _sql(
        world.urls.migrator,
        "SELECT count(*) AS n FROM audit.audit_entries WHERE action = 'auth.login.failed' "
        "AND entity_id = (SELECT id FROM platform.principals WHERE phone = $1)",
        s["owner_phone"],
    )
    assert failed[0]["n"] == 5


def test_unknown_and_known_phone_get_same_error(world: World) -> None:
    c, s = world.client, world.create_shop()
    unknown = c.post("/api/v1/auth/login", json={"phone": _phone(), "password": PASSWORD, "audience": "shop"})
    wrong = c.post(
        "/api/v1/auth/login",
        json={"phone": s["owner_phone"], "password": "boshqa-parol-123", "audience": "shop"},
    )
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    assert unknown.status_code == wrong.status_code == 401


def test_login_rate_limited_per_ip_and_phone(world: World) -> None:
    c, phone = world.client, _phone()
    for _ in range(10):
        assert (
            c.post(
                "/api/v1/auth/login", json={"phone": phone, "password": "x", "audience": "shop"}
            ).status_code
            == 401
        )
    limited = c.post("/api/v1/auth/login", json={"phone": phone, "password": "x", "audience": "shop"})
    assert (limited.status_code, _code(limited)) == (429, "RATE_LIMITED")


def test_refresh_rotation_and_reuse_detection(world: World) -> None:
    c, s = world.client, world.create_shop()
    login = c.post(
        "/api/v1/auth/login", json={"phone": s["owner_phone"], "password": PASSWORD, "audience": "shop"}
    )
    first_cookie = login.cookies["cos_refresh_shop"]
    rotated = c.post("/api/v1/auth/refresh", json=SHOP)
    assert rotated.status_code == 200
    new_access = rotated.json()["access_token"]
    assert c.get("/api/v1/auth/me", headers=_bearer(new_access)).status_code == 200

    c.cookies.clear()
    c.cookies.set("cos_refresh_shop", first_cookie)  # eski token qayta ishlatildi
    stolen = c.post("/api/v1/auth/refresh", json=SHOP)
    assert stolen.status_code == 401
    # Butun oila bekor: yangi access token ham ishlamaydi
    assert c.get("/api/v1/auth/me", headers=_bearer(new_access)).status_code == 401


def test_logout_and_logout_all(world: World) -> None:
    c, s = world.client, world.create_shop()
    one, two = world.login(s["owner_phone"]), world.login(s["owner_phone"])
    assert c.post("/api/v1/auth/logout", headers=_bearer(one)).status_code == 204
    assert c.get("/api/v1/auth/me", headers=_bearer(one)).status_code == 401
    assert c.get("/api/v1/auth/me", headers=_bearer(two)).status_code == 200
    sessions = c.get("/api/v1/auth/sessions", headers=_bearer(two)).json()["items"]
    assert sum(item["current"] for item in sessions) == 1
    assert c.post("/api/v1/auth/logout-all", headers=_bearer(two)).status_code == 204
    assert c.get("/api/v1/auth/me", headers=_bearer(two)).status_code == 401


def test_change_password_keeps_current_session_only(world: World) -> None:
    c, s = world.client, world.create_shop()
    current, other = world.login(s["owner_phone"]), world.login(s["owner_phone"])
    weak = c.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "12345678"},
        headers=_bearer(current),
    )
    assert weak.json()["error"]["details"]["fields"][0]["code"] == "too_weak"
    ok = c.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "Yangi-parol-2027"},
        headers=_bearer(current),
    )
    assert ok.status_code == 204
    assert c.get("/api/v1/auth/me", headers=_bearer(current)).status_code == 200
    assert c.get("/api/v1/auth/me", headers=_bearer(other)).status_code == 401
    world.login(s["owner_phone"], "Yangi-parol-2027")


def test_password_reset_link_flow(world: World) -> None:
    c, s = world.client, world.create_shop()
    phone, member_id, sales = world.invite(s["owner_token"], "SALES")
    link = c.post(
        f"/api/v1/shop/members/{member_id}/password-reset", headers=_bearer(s["owner_token"], **_idem())
    ).json()
    token = link["url"].rsplit("/", 1)[1]
    confirm = c.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "Tiklangan-parol-1"}
    )
    assert confirm.status_code == 204
    assert c.get("/api/v1/auth/me", headers=_bearer(sales)).status_code == 401  # eski sessiyalar bekor
    world.login(phone, "Tiklangan-parol-1")
    again = c.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "Yana-boshqa-parol-2"}
    )
    assert (again.status_code, again.json()["error"]["details"]) == (404, {"reason": "used"})


def test_expired_invite_is_rejected(world: World) -> None:
    c, s = world.client, world.create_shop()
    invite = c.post(
        "/api/v1/shop/members/invites",
        json={"phone": _phone(), "full_name": "Kech Qolgan", "role": "SALES"},
        headers=_bearer(s["owner_token"], **_idem()),
    ).json()
    _sql(
        world.urls.migrator,
        "UPDATE platform.invitations SET expires_at = now() - interval '1 minute' WHERE membership_id = $1",
        UUID(invite["member"]["id"]),
    )
    token = invite["invite"]["url"].rsplit("/", 1)[1]
    expired = c.post(f"/api/v1/auth/invites/{token}/accept", json={"password": PASSWORD})
    assert (expired.status_code, expired.json()["error"]["details"]) == (404, {"reason": "expired"})


def test_policies_require_if_match_and_detect_conflicts(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    current = c.get("/api/v1/shop/policies", headers=_bearer(owner))
    assert current.headers["ETag"] == '"v1"'
    body = {
        **{k: v for k, v in current.json().items() if k != "version"},
        "discount_limit_manager_pct": "7.50",
    }
    assert _code(c.patch("/api/v1/shop/policies", json=body, headers=_bearer(owner))) == "INVALID_REQUEST"
    saved = c.patch("/api/v1/shop/policies", json=body, headers=_bearer(owner, **{"If-Match": '"v1"'}))
    assert (saved.status_code, saved.json()["discount_limit_manager_pct"], saved.headers["ETag"]) == (
        200,
        "7.50",
        '"v2"',
    )
    stale = c.patch("/api/v1/shop/policies", json=body, headers=_bearer(owner, **{"If-Match": '"v1"'}))
    assert (_code(stale), stale.json()["error"]["details"]) == (
        "VERSION_CONFLICT",
        {"current_version": 2, "your_version": 1},
    )


def test_shop_and_platform_panels_keep_separate_sessions_in_one_browser(world: World) -> None:
    c, s = world.client, world.create_shop()
    world.login(s["owner_phone"])  # admin allaqachon kirgan — endi shu brauzerda ega ham kirdi
    platform = c.post("/api/v1/auth/refresh", json={"audience": "platform"})
    shop = c.post("/api/v1/auth/refresh", json=SHOP)
    assert (platform.status_code, platform.json()["audience"]) == (200, "platform")
    assert (shop.status_code, shop.json()["audience"]) == (200, "shop")

    # Boshqa panelga kirish huquqi yo'q — oddiy "noto'g'ri login", sessiya ochilmaydi
    owner_to_platform = {"phone": s["owner_phone"], "password": PASSWORD, "audience": "platform"}
    admin_to_shop = {"phone": world.admin_phone, "password": ADMIN_PASSWORD, "audience": "shop"}
    for body in (owner_to_platform, admin_to_shop):
        response = c.post("/api/v1/auth/login", json=body)
        assert (response.status_code, _code(response)) == (401, "UNAUTHENTICATED")


def test_platform_shop_card_lists_owners_and_reissues_expired_owner_invite(world: World) -> None:
    c, admin = world.client, _bearer(world.admin_token)
    owner_phone = _phone()
    created = c.post(
        "/api/v1/platform/shops",
        json={
            "slug": f"shop-{uuid4().hex[:8]}",
            "name": "Kech qolgan shop",
            "tin": _tin(),
            "owner_phone": owner_phone,
            "owner_full_name": "Sardor Ega",
        },
        headers={**admin, **_idem()},
    ).json()
    shop_id, owner_id = created["shop"]["id"], created["owner_membership_id"]

    card = c.get(f"/api/v1/platform/shops/{shop_id}", headers=admin).json()
    assert card["owners"] == [
        {"membership_id": owner_id, "full_name": "Sardor Ega", "phone": owner_phone, "status": "INVITED"}
    ]

    # 72 soat o'tdi — ega havolani ochmadi. Platforma yangi havola beradi, eskisi ishlamaydi
    _sql(
        world.urls.admin,
        "UPDATE platform.invitations SET expires_at = now() - interval '1 minute' WHERE membership_id = $1",
        UUID(owner_id),
    )
    fresh = c.post(
        f"/api/v1/platform/shops/{shop_id}/members/{owner_id}/invite", headers={**admin, **_idem()}
    )
    assert fresh.status_code == 200, fresh.text
    world.accept(fresh.json()["url"])
    card = c.get(f"/api/v1/platform/shops/{shop_id}", headers=admin).json()
    assert card["owners"][0]["status"] == "ACTIVE"
    # Faol egaga taklif qayta berilmaydi
    again = c.post(
        f"/api/v1/platform/shops/{shop_id}/members/{owner_id}/invite", headers={**admin, **_idem()}
    )
    assert (again.status_code, _code(again)) == (404, "NOT_FOUND")


def test_reserved_slug_is_rejected(world: World) -> None:
    response = world.client.post(
        "/api/v1/platform/shops",
        json={
            "slug": "login",
            "name": "Login shop",
            "tin": _tin(),
            "owner_phone": _phone(),
            "owner_full_name": "Ega Ism",
        },
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0] == {
        "field": "slug",
        "code": "not_unique",
        "params": {},
    }
