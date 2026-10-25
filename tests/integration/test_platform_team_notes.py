"""Platforma jamoasi (taklif, rol, o'chirish, parol tiklash), ichki izohlar va dev seed (business/15 §3, §5).

Haqiqiy PostgreSQL, HTTP orqali.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app.config.settings import Settings
from app.platform.staff.cli import create_platform_admin
from tests.conftest import FAST_TEST_SETTINGS
from tests.integration.conftest import PgUrls, migrate_all
from tests.integration.helpers import PASSWORD, World, _bearer, _code, _idem, _phone, _sql

pytestmark = pytest.mark.integration

PLATFORM = {"audience": "platform"}


def _platform_login(world: World, phone: str, password: str = PASSWORD) -> str:
    response = world.client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": password, **PLATFORM}
    )
    assert response.status_code == 200, response.text
    assert response.json()["audience"] == "platform"
    return str(response.json()["access_token"])


def _invite(world: World, role: str = "SPEC_EDITOR", phone: str | None = None) -> dict[str, Any]:
    response = world.client.post(
        "/api/v1/platform/staff/invites",
        json={"phone": phone or _phone(), "full_name": "Bekzod Kutubxona", "role": role},
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _accept(world: World, url: str, password: str = PASSWORD) -> str:
    response = world.client.post(
        f"/api/v1/auth/platform-invites/{url.rsplit('/', 1)[1]}/accept", json={"password": password}
    )
    assert response.status_code == 200, response.text
    assert response.json()["audience"] == "platform"
    return str(response.json()["access_token"])


def _member(world: World, staff_id: str) -> dict[str, Any]:
    items = world.client.get("/api/v1/platform/staff", headers=_bearer(world.admin_token)).json()["items"]
    return next(item for item in items if item["id"] == staff_id)


def test_invite_accept_login_and_audit(world: World) -> None:
    c = world.client
    key = _idem()
    response = c.post(
        "/api/v1/platform/staff/invites",
        json={"phone": _phone(), "full_name": "Bekzod Kutubxona", "role": "SPEC_EDITOR"},
        headers=_bearer(world.admin_token, **key),
    )
    assert response.status_code == 201, response.text
    invited = response.json()
    assert invited["member"]["status"] == "INVITED"
    assert invited["member"]["invited_by_name"] == "Platforma Admin"
    assert invited["invite"]["url"].startswith("http://localhost:3001/invite/")

    # Takroriy so'rov: o'sha a'zo, yangi havola; havola idempotency jadvaliga yozilmagan
    replay = c.post(
        "/api/v1/platform/staff/invites",
        json={"phone": invited["member"]["phone"], "full_name": "Bekzod Kutubxona", "role": "SPEC_EDITOR"},
        headers=_bearer(world.admin_token, **key),
    ).json()
    assert replay["member"]["id"] == invited["member"]["id"]
    assert replay["invite"]["url"] != invited["invite"]["url"]
    stored = _sql(
        world.urls.migrator,
        "SELECT response_body::text AS b FROM platform.idempotency_keys WHERE key = $1",
        key["Idempotency-Key"],
    )
    assert "/invite/" not in stored[0]["b"]

    token = _accept(world, replay["invite"]["url"])
    me = c.get("/api/v1/auth/me", headers=_bearer(token)).json()
    assert (me["audience"], me["role"]) == ("platform", "SPEC_EDITOR")
    assert "platform.spec.edit" in me["permissions"]
    _platform_login(world, invited["member"]["phone"])
    assert _member(world, invited["member"]["id"])["status"] == "ACTIVE"
    actions = {
        item["action"]
        for item in c.get("/api/v1/platform/audit", headers=_bearer(world.admin_token)).json()["items"]
    }
    assert {"platform.staff.invited", "platform.staff.joined"} <= actions


def test_duplicate_phone_rejected(world: World) -> None:
    shop = world.create_shop()
    for phone in (shop["owner_phone"], world.admin_phone):
        response = world.client.post(
            "/api/v1/platform/staff/invites",
            json={"phone": phone, "full_name": "Ikki Joyda", "role": "PLATFORM_SUPPORT"},
            headers=_bearer(world.admin_token, **_idem()),
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["fields"][0]["code"] == "not_unique"


def test_resend_revokes_previous_link(world: World) -> None:
    invited = _invite(world)
    staff_id = invited["member"]["id"]
    fresh = world.client.post(
        f"/api/v1/platform/staff/{staff_id}/invite", headers=_bearer(world.admin_token, **_idem())
    )
    assert fresh.status_code == 200, fresh.text
    old = world.client.post(
        f"/api/v1/auth/platform-invites/{invited['invite']['url'].rsplit('/', 1)[1]}/accept",
        json={"password": PASSWORD},
    )
    assert (old.status_code, old.json()["error"]["details"]) == (404, {"reason": "revoked"})
    _accept(world, fresh.json()["url"])
    again = world.client.post(
        f"/api/v1/platform/staff/{staff_id}/invite", headers=_bearer(world.admin_token, **_idem())
    )
    assert _code(again) == "INVALID_STATE_TRANSITION"  # faol a'zoga taklif qayta berilmaydi


def test_role_change_requires_if_match(world: World) -> None:
    invited = _invite(world, "PLATFORM_SUPPORT")
    staff_id = invited["member"]["id"]
    url = f"/api/v1/platform/staff/{staff_id}/role"
    admin = _bearer(world.admin_token)
    missing = world.client.put(url, json={"role": "SPEC_EDITOR"}, headers=admin)
    assert _code(missing) == "INVALID_REQUEST"
    saved = world.client.put(url, json={"role": "SPEC_EDITOR"}, headers={**admin, "If-Match": '"v1"'})
    assert (saved.status_code, saved.json()["role"], saved.headers["ETag"]) == (200, "SPEC_EDITOR", '"v2"')
    stale = world.client.put(url, json={"role": "PLATFORM_SUPPORT"}, headers={**admin, "If-Match": '"v1"'})
    assert _code(stale) == "VERSION_CONFLICT"


def test_disable_revokes_sessions_and_self_is_forbidden(world: World) -> None:
    invited = _invite(world, "PLATFORM_SUPPORT")
    token = _accept(world, invited["invite"]["url"])
    assert world.client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200
    staff_id = invited["member"]["id"]
    disabled = world.client.post(
        f"/api/v1/platform/staff/{staff_id}/disable",
        json={"reason": "Ishdan ketdi"},
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert (disabled.status_code, disabled.json()["status"]) == (200, "DISABLED")
    assert world.client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401  # darhol
    login = world.client.post(
        "/api/v1/auth/login", json={"phone": invited["member"]["phone"], "password": PASSWORD, **PLATFORM}
    )
    assert login.status_code == 401

    me = world.client.get("/api/v1/auth/me", headers=_bearer(world.admin_token)).json()
    own = next(
        item
        for item in world.client.get("/api/v1/platform/staff", headers=_bearer(world.admin_token)).json()[
            "items"
        ]
        if item["principal_id"] == me["principal_id"]
    )
    self_disable = world.client.post(
        f"/api/v1/platform/staff/{own['id']}/disable", json={}, headers=_bearer(world.admin_token, **_idem())
    )
    assert (self_disable.status_code, _code(self_disable)) == (403, "FORBIDDEN")


def test_last_active_admin_cannot_be_demoted(world: World) -> None:
    me = world.client.get("/api/v1/auth/me", headers=_bearer(world.admin_token)).json()
    own = next(
        item
        for item in world.client.get("/api/v1/platform/staff", headers=_bearer(world.admin_token)).json()[
            "items"
        ]
        if item["principal_id"] == me["principal_id"]
    )
    # Boshqa testlar yaratgan adminlarni vaqtincha o'chiramiz — shu admin yagona qoladi
    others = _sql(
        world.urls.admin,
        "UPDATE platform.platform_staff SET status = 'DISABLED' "
        "WHERE role = 'PLATFORM_ADMIN' AND status = 'ACTIVE' AND id <> $1 RETURNING id",
        UUID(own["id"]),
    )
    try:
        demote = world.client.put(
            f"/api/v1/platform/staff/{own['id']}/role",
            json={"role": "PLATFORM_SUPPORT"},
            headers=_bearer(world.admin_token, **{"If-Match": f'"v{own["version"]}"'}),
        )
        assert (demote.status_code, _code(demote)) == (409, "LAST_ADMIN_REQUIRED")
    finally:
        _sql(
            world.urls.admin,
            "UPDATE platform.platform_staff SET status = 'ACTIVE' WHERE id = ANY($1::uuid[])",
            [row["id"] for row in others],
        )


def test_support_can_note_but_not_see_or_manage_team(world: World) -> None:
    support_phone = _phone()
    asyncio.run(
        create_platform_admin(world.settings, support_phone, "Dilnoza Support", PASSWORD, "PLATFORM_SUPPORT")
    )
    support = _bearer(_platform_login(world, support_phone))
    # Platforma jamoasi bo'limi faqat adminga (business/15 §5)
    staff = world.client.get("/api/v1/platform/staff", headers=support)
    assert (staff.status_code, _code(staff)) == (403, "FORBIDDEN")
    me = world.client.get("/api/v1/auth/me", headers=support).json()
    assert "platform.staff.view" not in me["permissions"]
    invite = world.client.post(
        "/api/v1/platform/staff/invites",
        json={"phone": _phone(), "full_name": "Yangi Odam", "role": "SPEC_EDITOR"},
        headers={**support, **_idem()},
    )
    assert (invite.status_code, _code(invite)) == (403, "FORBIDDEN")
    staff_id = _invite(world)["member"]["id"]
    role = world.client.put(
        f"/api/v1/platform/staff/{staff_id}/role",
        json={"role": "PLATFORM_SUPPORT"},
        headers={**support, "If-Match": '"v1"'},
    )
    assert role.status_code == 403

    shop = world.create_shop()["shop"]
    note = world.client.post(
        f"/api/v1/platform/shops/{shop['id']}/notes",
        json={"body": "Ega bilan gaplashildi, hujjatlar ertaga"},
        headers={**support, **_idem()},
    )
    assert note.status_code == 201, note.text
    assert note.json()["author_name"] == "Dilnoza Support"


def test_notes_are_append_only_and_text_is_not_audited(world: World) -> None:
    c, admin = world.client, _bearer(world.admin_token)
    shop_id = world.create_shop()["shop"]["id"]
    url = f"/api/v1/platform/shops/{shop_id}/notes"
    secret = "Ega telefoni +998901234567, kechqurun qo'ng'iroq qilish"
    first = c.post(url, json={"body": "Kelishuv imzolandi"}, headers={**admin, **_idem()}).json()
    second = c.post(url, json={"body": secret}, headers={**admin, **_idem()}).json()
    items = c.get(url, headers=admin).json()["items"]
    assert [item["id"] for item in items] == [second["id"], first["id"]]  # yangisi birinchi
    assert items[0]["author_name"] == "Platforma Admin"

    assert c.post(url, json={"body": "   "}, headers={**admin, **_idem()}).status_code == 422
    assert c.post(url, json={"body": "x" * 2001}, headers={**admin, **_idem()}).status_code == 422
    assert c.delete(url, headers=admin).status_code == 405  # o'chirish yo'q

    rows = _sql(
        world.urls.migrator,
        "SELECT diff::text AS diff, reason, shop_id FROM audit.audit_entries "
        "WHERE action = 'platform.shop.note_added' AND entity_id = $1",
        UUID(second["id"]),
    )
    assert len(rows) == 1 and rows[0]["diff"] in (None, "null") and rows[0]["reason"] is None
    assert "+998901234567" not in str(rows)
    assert str(rows[0]["shop_id"]) == shop_id  # shop kartochkasi jurnalida ko'rinadi
    assert c.get(f"/api/v1/platform/shops/{UUID(int=0)}/notes", headers=admin).status_code == 404


def test_platform_password_reset_flow(world: World) -> None:
    invited = _invite(world, "PLATFORM_SUPPORT")
    staff_id = invited["member"]["id"]
    not_yet = world.client.post(
        f"/api/v1/platform/staff/{staff_id}/password-reset", headers=_bearer(world.admin_token, **_idem())
    )
    assert _code(not_yet) == "INVALID_STATE_TRANSITION"  # hali kirmagan — taklif kerak, tiklash emas
    old_token = _accept(world, invited["invite"]["url"])
    link = world.client.post(
        f"/api/v1/platform/staff/{staff_id}/password-reset", headers=_bearer(world.admin_token, **_idem())
    ).json()
    assert link["url"].startswith("http://localhost:3001/reset-password/")
    token = link["url"].rsplit("/", 1)[1]
    confirm = world.client.post(
        "/api/v1/auth/platform-password-reset/confirm", json={"token": token, "password": "Yangi-parol-2027"}
    )
    assert confirm.status_code == 204
    assert world.client.get("/api/v1/auth/me", headers=_bearer(old_token)).status_code == 401
    _platform_login(world, invited["member"]["phone"], "Yangi-parol-2027")
    again = world.client.post(
        "/api/v1/auth/platform-password-reset/confirm", json={"token": token, "password": "Boshqa-parol-2028"}
    )
    assert (again.status_code, again.json()["error"]["details"]) == (404, {"reason": "used"})


# ------------------------------------------------------------------ dev seed


@pytest.fixture(scope="module")
def seed_urls(pg_urls: PgUrls) -> PgUrls:
    """Seed uchun alohida baza — boshqa testlar ma'lumotiga aralashmasin."""

    async def create() -> None:
        conn = await asyncpg.connect(pg_urls.admin)
        try:
            await conn.execute("DROP DATABASE IF EXISTS seed_test")
            await conn.execute("CREATE DATABASE seed_test")
        finally:
            await conn.close()

    from app.db.bootstrap import bootstrap

    asyncio.run(create())
    urls = PgUrls(
        admin=pg_urls.admin.replace("/commerce_os", "/seed_test"),
        runtime=pg_urls.runtime.replace("/commerce_os", "/seed_test"),
        migrator=pg_urls.migrator.replace("/commerce_os", "/seed_test"),
    )
    asyncio.run(bootstrap(urls.admin, urls.runtime, urls.migrator))
    migrate_all(urls)
    return urls


def test_dev_seed_builds_demo_data_and_is_idempotent(seed_urls: PgUrls) -> None:
    from app.db.seed.dev_seed import run_seed

    settings = Settings(
        **{
            **FAST_TEST_SETTINGS,
            "database_url": seed_urls.runtime,
            "database_migrator_url": seed_urls.migrator,
        }  # type: ignore[arg-type]
    )
    first = asyncio.run(run_seed(settings))
    assert len(first.created_shops) == 8 and first.skipped_shops == []

    def counts() -> dict[str, int]:
        row = _sql(
            seed_urls.admin,
            "SELECT (SELECT count(*) FROM platform.shops) AS shops, "
            "(SELECT count(*) FROM platform.principals) AS people, "
            "(SELECT count(*) FROM platform.platform_staff) AS team, "
            "(SELECT count(*) FROM platform.branches) AS branches, "
            "(SELECT count(*) FROM platform.shop_notes) AS notes",
        )[0]
        return dict(row)

    before = counts()
    second = asyncio.run(run_seed(settings))
    assert second.created_shops == [] and second.created_team == []
    assert counts() == before
    assert before["shops"] == 8 and before["team"] == 3

    shops = {
        r["slug"]: r
        for r in _sql(
            seed_urls.admin,
            "SELECT slug, status, now()::date - activated_at::date AS active_days FROM platform.shops",
        )
    }
    assert shops["techpc"]["status"] == "PENDING_VERIFICATION"
    assert shops["noutbukuz"]["status"] == "ACTIVE" and shops["noutbukuz"]["active_days"] == 26
    assert shops["byteshop"]["status"] == "SUSPENDED"
    assert shops["gamezone"]["status"] == "DRAFT"
    invites = {
        r["slug"]: r["left_hours"]
        for r in _sql(
            seed_urls.admin,
            "SELECT s.slug, extract(epoch FROM i.expires_at - now()) / 3600 AS left_hours "
            "FROM platform.invitations i JOIN platform.shops s ON s.id = i.shop_id "
            "WHERE s.slug IN ('gamezone', 'pc-market') AND i.accepted_at IS NULL AND i.revoked_at IS NULL",
        )
    }
    assert 0 < invites["gamezone"] <= 6 and invites["pc-market"] < 0
    waiting = _sql(
        seed_urls.admin,
        "SELECT now()::date - t.occurred_at::date AS days FROM platform.transition_log t "
        "JOIN platform.shops s ON s.id = t.entity_id "
        "WHERE s.slug = 'techpc' AND t.command = 'SUBMIT_FOR_VERIFICATION'",
    )
    assert waiting[0]["days"] == 3
