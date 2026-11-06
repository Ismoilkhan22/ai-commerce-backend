"""6a: leadlar, PC takliflari va xaridor havolasi — haqiqiy PostgreSQL'da.

Qabul mezonlari (DEC-142 taklif): FSM-05/FSM-06, narx nusxasi va qabulda qayta tekshiruv, moslik snapshot'lari
(engine orqali), tasdiq qoidalari (ALL / RISKY_ONLY, o'zi tasdiqlamaydi, chegirma limiti), havola xavfsizligi
(faqat xesh, PII yo'q, boshqa shop — 404), qabul → DRAFT buyurtma, idempotentlik, RLS/IDOR, event'da PII yo'q.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.integration.helpers import World, _bearer, _code, _idem, _sql
from tests.integration.test_catalog import _create, _platform_member, _sku
from tests.integration.test_compat_service import _specs
from tests.integration.test_jobs_events import _drain_now

pytestmark = pytest.mark.integration

PHONE = "+998901234567"


def _hdr(token: str, version: int | None = None) -> dict[str, str]:
    extra = {"If-Match": f'"v{version}"'} if version is not None else {}
    return _bearer(token, **_idem(), **extra)


def _ok(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    return dict(response.json())


def _admin(world: World, query: str, *args: Any) -> list[asyncpg.Record]:
    return _sql(world.urls.admin, query, *args)


class Pc:
    """Shop + jamoa + kutubxonaga bog'langan, chiqarilgan PC qismlari (PASS yig'ma)."""

    def __init__(self, world: World, *, risky_only: bool = False) -> None:
        self.world = world
        created = world.create_shop()
        self.shop_id = created["shop"]["id"]
        self.slug = created["shop"]["slug"]
        self.owner = created["owner_token"]
        self.branch = world.branch(self.owner)["id"]
        _, self.manager_id, self.manager = world.invite(self.owner, "MANAGER")
        _, self.sales_id, self.sales = world.invite(self.owner, "SALES")
        _, _, self.sales2 = world.invite(self.owner, "SALES")
        _, _, self.warehouse = world.invite(self.owner, "WAREHOUSE")
        editor = _platform_member(world)
        tag = uuid4().hex[:5].upper()
        self.skus: dict[str, str] = {}
        for category, (brand, model, _) in _specs(world, editor, tag).items():
            self.skus[category] = self._product(category, brand, f"{brand} {model}", model_name=model)
        self.unlinked_gpu = self._product("GPU", "MSI", "RTX ???", model_name=f"RTX 9999 {tag}")
        if risky_only:
            _admin(
                world,
                "UPDATE platform.shop_policies SET quote_approval_mode = 'RISKY_ONLY' WHERE shop_id = $1",
                UUID(self.shop_id),
            )

    def _product(self, category: str, brand: str, title: str, **sku: Any) -> str:
        product = _create(
            self.world,
            self.owner,
            category_code=category,
            brand=brand,
            title=title,
            skus=[_sku(price={"amount_minor": 100_000_000, "currency": "UZS"}, **sku)],
        )
        _ok(self.post(self.owner, f"/products/{product['id']}/publish"))
        return str(product["skus"][0]["id"])

    def post(self, token: str, path: str, body: Any = None, version: int | None = None) -> Any:
        return self.world.client.post(f"/api/v1/shop{path}", json=body, headers=_hdr(token, version))

    def get(self, token: str, path: str) -> Any:
        return self.world.client.get(f"/api/v1/shop{path}", headers=_bearer(token))

    def lines(self, *, skip: tuple[str, ...] = (), **extra: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"sku_id": sku, "qty": 1, **extra.get(category, {})}
            for category, sku in self.skus.items()
            if category not in skip
        ]

    def quote(self, token: str, lines: list[dict[str, Any]] | None = None, **body: Any) -> dict[str, Any]:
        return _ok(
            self.post(token, "/quotes", {"lines": lines if lines is not None else self.lines(), **body}), 201
        )

    def step(self, token: str, quote: dict[str, Any], action: str, body: Any = None) -> dict[str, Any]:
        return _ok(self.post(token, f"/quotes/{quote['id']}/{action}", body, version=quote["version"]))

    def public(self, path: str) -> str:
        return f"/api/v1/storefront/{self.slug}{path}"


def _sent(pc: Pc, quote: dict[str, Any]) -> tuple[dict[str, Any], str]:
    sent = pc.step(pc.sales, quote, "send")
    assert sent["public_path"].startswith("/q/")
    return sent["quote"], sent["public_path"].removeprefix("/q/")


# ------------------------------------------------------------------ to'liq oqim


def test_risky_only_pass_quote_auto_approves_and_customer_accepts(world: World) -> None:
    pc = Pc(world, risky_only=True)
    quote = pc.quote(pc.sales)
    assert quote["status"] == "DRAFT" and quote["revision"] == 1
    assert quote["compatibility"]["stage"] == "LIVE" and quote["compatibility"]["decision"] == "PASS"
    assert quote["total_uzs_minor"] == 7 * 100_000_000
    assert {line["role"] for line in quote["lines"]} >= {"CPU", "MOTHERBOARD", "GPU", "PSU"}
    lead = _ok(pc.get(pc.sales, f"/leads/{quote['lead_id']}"))
    assert lead["status"] == "NEW" and lead["assigned"]["membership_id"] == pc.sales_id

    approved = pc.step(pc.sales, quote, "submit")
    assert approved["status"] == "APPROVED" and approved["approval_mode"] == "AUTO_RISKY_ONLY"
    assert approved["compatibility"]["stage"] == "SUBMIT"
    sent, token = _sent(pc, approved)
    assert sent["status"] == "SENT" and sent["expires_at"]
    assert _ok(pc.get(pc.sales, f"/leads/{quote['lead_id']}"))["status"] == "QUOTED"

    # Havola: shaxsiy ma'lumot yo'q, token bazada emas — faqat xeshi
    view = _ok(world.client.get(pc.public(f"/quotes/{token}")))
    assert view["status"] == "SENT" and view["total_uzs_minor"] == 7 * 100_000_000
    assert "customer" not in json.dumps(view) and "sku_id" not in json.dumps(view)
    stored = _admin(world, "SELECT public_token_hash FROM commerce.quotes WHERE id = $1", UUID(quote["id"]))
    assert stored[0]["public_token_hash"] != token and len(stored[0]["public_token_hash"]) == 64
    leaked = _admin(
        world,
        "SELECT count(*) AS n FROM platform.idempotency_keys WHERE response_body::text LIKE $1",
        f"%{token}%",
    )
    assert leaked[0]["n"] == 0

    key = _idem()
    accepted = _ok(world.client.post(pc.public(f"/quotes/{token}/accept"), headers=key))
    assert accepted["status"] == "ACCEPTED" and accepted["tracking_path"].startswith("/orders/")
    replay = _ok(world.client.post(pc.public(f"/quotes/{token}/accept"), headers=key))
    assert replay["order_number"] == accepted["order_number"]  # takror — o'sha buyurtma
    again = _ok(world.client.post(pc.public(f"/quotes/{token}/accept"), headers=_idem()))
    assert again["order_number"] == accepted["order_number"]

    detail = _ok(pc.get(pc.sales, f"/quotes/{quote['id']}"))
    assert detail["status"] == "ACCEPTED" and detail["compatibility"]["stage"] == "ACCEPT"
    order = _ok(pc.get(pc.owner, f"/orders/{detail['accepted_order_id']}"))
    assert order["status"] == "DRAFT" and order["source"] == "QUOTE"
    assert order["total_minor"] == 7 * 100_000_000 and len(order["lines"]) == 7
    stages = _admin(
        world,
        "SELECT stage FROM commerce.quote_compatibility_snapshots s JOIN commerce.quote_revisions r "
        "ON r.id = s.quote_revision_id WHERE r.quote_id = $1 ORDER BY stage",
        UUID(quote["id"]),
    )
    assert [r["stage"] for r in stages] == ["ACCEPT", "SUBMIT"]
    tracking = world.client.get(pc.public(again["tracking_path"]))  # oxirgi havola (oldingilari bekor)
    assert tracking.status_code == 200, tracking.text


def test_manual_approval_rules(world: World) -> None:
    pc = Pc(world)
    quote = pc.quote(pc.sales)
    review = pc.step(pc.sales, quote, "submit")
    assert review["status"] == "REVIEW" and review["approval_mode"] is None
    assert "APPROVE" not in review["allowed_actions"]
    denied = pc.post(pc.sales, f"/quotes/{quote['id']}/approve", {}, version=review["version"])
    assert denied.status_code == 403
    tasks = _ok(pc.get(pc.manager, "/tasks?status=OPEN"))["items"]
    assert any(t["type"] == "QUOTE_APPROVAL" for t in tasks)
    approved = pc.step(pc.manager, review, "approve", {})
    assert approved["status"] == "APPROVED" and approved["approved_by"]["membership_id"] == pc.manager_id

    # O'zi tuzganini o'zi tasdiqlay olmaydi (DEC-109)
    own = pc.step(pc.manager, pc.quote(pc.manager), "submit")
    assert _code(pc.post(pc.manager, f"/quotes/{own['id']}/approve", {}, version=own["version"])) == (
        "SELF_APPROVAL_NOT_ALLOWED"
    )

    # Chegirma 10% — menejer limiti 5% → egaga
    discounted = pc.step(pc.sales, pc.quote(pc.sales, pc.lines(CPU={"discount_pct": "10"})), "submit")
    assert discounted["status"] == "REVIEW" and discounted["discount_uzs_minor"] == 10_000_000
    over = pc.post(pc.manager, f"/quotes/{discounted['id']}/approve", {}, version=discounted["version"])
    assert _code(over) == "DISCOUNT_LIMIT_EXCEEDED"
    assert pc.step(pc.owner, discounted, "approve", {})["status"] == "APPROVED"

    # Bog'lanmagan qism — REVIEW_REQUIRED: dalil yozuvisiz tasdiqlanmaydi
    risky = pc.step(
        pc.sales,
        pc.quote(pc.sales, [*pc.lines(skip=("GPU",)), {"sku_id": pc.unlinked_gpu, "qty": 1}]),
        "submit",
    )
    assert risky["compatibility"]["decision"] == "REVIEW_REQUIRED"
    no_note = pc.post(pc.manager, f"/quotes/{risky['id']}/approve", {}, version=risky["version"])
    assert no_note.status_code == 422 and _code(no_note) == "VALIDATION_FAILED"
    assert (
        pc.step(pc.manager, risky, "approve", {"note": "GPU modeli tekshirildi, 199 mm"})["status"]
        == "APPROVED"
    )

    # Mos emas (3 ta M.2 disk, 2 ta slot) — tekshiruvga o'tmaydi
    blocked = pc.quote(pc.sales, pc.lines(STORAGE={"qty": 3}))
    assert blocked["compatibility"]["decision"] == "BLOCK"
    refused = pc.post(pc.sales, f"/quotes/{blocked['id']}/submit", version=blocked["version"])
    assert refused.status_code == 422 and _code(refused) == "RULE_BLOCK"

    # Qaytarish — yangi versiya (qoralama)
    second = pc.step(pc.sales, pc.quote(pc.sales), "submit")
    returned = pc.step(pc.manager, second, "return", {"reason": "Monitor qo'shing"})
    assert returned["status"] == "DRAFT" and returned["revision"] == 2
    assert returned["revisions"][0]["returned_note"] == "Monitor qo'shing"
    first = _ok(pc.get(pc.sales, f"/quotes/{second['id']}/revisions/1"))
    assert len(first["lines"]) == 7 and [c["stage"] for c in first["compatibility"]] == ["SUBMIT"]
    assert pc.get(pc.sales, f"/quotes/{second['id']}/revisions/9").status_code == 404
    assert returned["approver_discount_limit_pct"] == "5.00" and returned["price_changed"] is False


def test_accept_detects_price_change_and_revise_invalidates_link(world: World) -> None:
    pc = Pc(world, risky_only=True)
    quote = pc.step(pc.sales, pc.quote(pc.sales), "submit")
    _, token = _sent(pc, quote)
    price = world.client.put(
        f"/api/v1/shop/skus/{pc.skus['GPU']}/price",
        json={"amount_minor": 120_000_000, "currency": "UZS"},
        headers=_hdr(pc.owner, 1),
    )
    assert price.status_code == 200, price.text
    changed = world.client.post(pc.public(f"/quotes/{token}/accept"), headers=_idem())
    assert changed.status_code == 409 and _code(changed) == "QUOTE_CHANGED"
    lines = changed.json()["error"]["details"]["lines"]
    assert lines and all("sku_id" not in line for line in lines)  # xaridorga ichki ID yo'q
    assert lines[0]["new_uzs_minor"] == 120_000_000

    current = _ok(pc.get(pc.sales, f"/quotes/{quote['id']}"))
    revised = pc.step(pc.sales, current, "revise")
    assert revised["status"] == "DRAFT" and revised["revision"] == 2
    assert world.client.get(pc.public(f"/quotes/{token}")).status_code == 404  # eski havola bekor
    resent = pc.step(pc.sales, revised, "submit")
    assert resent["status"] == "APPROVED" and resent["total_uzs_minor"] == 6 * 100_000_000 + 120_000_000


def test_stale_exchange_rate_blocks_usd_quote_at_every_step(world: World, monkeypatch: Any) -> None:
    """UAT-M05, BL-018: dollar narxli qator va eskirgan kurs — taklif tasdiqlanmaydi, yuborilmaydi, qabul
    qilinmaydi (buyurtma bilan bir xil `EXCHANGE_RATE_STALE`)."""
    pc = Pc(world, risky_only=True)
    _ok(pc.post(pc.owner, "/exchange-rates", {"rate": "12800"}), 201)
    price = world.client.put(
        f"/api/v1/shop/skus/{pc.skus['GPU']}/price",
        json={"amount_minor": 30_000, "currency": "USD"},
        headers=_hdr(pc.owner, 1),
    )
    assert price.status_code == 200, price.text
    stale_after = "app.domains.catalog.query_port.RATE_MAX_AGE"

    def stale(response: Any) -> None:
        assert response.status_code == 409 and _code(response) == "EXCHANGE_RATE_STALE", response.text
        assert response.json()["error"]["details"]["max_age_hours"] == 72

    # 1) yuborish (submit): kurs eskirgan
    draft = pc.quote(pc.sales)
    with monkeypatch.context() as patch:
        patch.setattr(stale_after, timedelta(seconds=-60))
        stale(pc.post(pc.sales, f"/quotes/{draft['id']}/submit", version=draft["version"]))
    approved = pc.step(pc.sales, draft, "submit")  # kurs yangi — o'tadi
    assert approved["status"] == "APPROVED"

    # 2) mijozga yuborish (send): tasdiqlangandan keyin kurs eskirdi
    with monkeypatch.context() as patch:
        patch.setattr(stale_after, timedelta(seconds=-60))
        stale(pc.post(pc.sales, f"/quotes/{draft['id']}/send", version=approved["version"]))
    _, token = _sent(pc, approved)

    # 3) xaridor qabul qiladi: kurs eskirgan — buyurtma ochilmaydi
    with monkeypatch.context() as patch:
        patch.setattr(stale_after, timedelta(seconds=-60))
        stale(world.client.post(pc.public(f"/quotes/{token}/accept"), headers=_idem()))
    assert _ok(pc.get(pc.sales, f"/quotes/{draft['id']}"))["status"] == "SENT"

    # 4) menejer tasdiqlaydi (approve): kurs eskirgan
    _admin(
        world,
        "UPDATE platform.shop_policies SET quote_approval_mode = 'ALL' WHERE shop_id = $1",
        UUID(pc.shop_id),
    )
    manual = pc
    review = manual.step(manual.sales, manual.quote(manual.sales), "submit")
    assert review["status"] == "REVIEW"
    with monkeypatch.context() as patch:
        patch.setattr(stale_after, timedelta(seconds=-60))
        stale(manual.post(manual.manager, f"/quotes/{review['id']}/approve", {}, version=review["version"]))
    assert manual.step(manual.manager, review, "approve", {})["status"] == "APPROVED"


def test_public_link_security_and_reject(world: World) -> None:
    pc, other = Pc(world, risky_only=True), world.create_shop()
    quote = pc.step(pc.sales, pc.quote(pc.sales), "submit")
    _, token = _sent(pc, quote)
    other_slug = other["shop"]["slug"]
    assert world.client.get(f"/api/v1/storefront/{other_slug}/quotes/{token}").status_code == 404
    assert world.client.get(pc.public("/quotes/short")).status_code == 404
    assert world.client.get(pc.public(f"/quotes/{'x' * 43}")).status_code == 404
    rejected = _ok(world.client.post(pc.public(f"/quotes/{token}/reject"), json={"reason": "Qimmat"}))
    assert rejected["status"] == "REJECTED"
    late = world.client.post(pc.public(f"/quotes/{token}/accept"), headers=_idem())
    assert late.status_code == 409


def test_leads_contact_consent_permissions_and_isolation(world: World) -> None:
    pc, other = Pc(world), world.create_shop()
    no_consent = pc.post(pc.sales, "/leads", {"customer_name": "Jasur", "contact_phone": PHONE})
    assert no_consent.status_code == 422
    lead = _ok(
        pc.post(
            pc.sales,
            "/leads",
            {
                "customer_name": "Jasur",
                "contact_phone": PHONE,
                "consent_contact": True,
                "requirements": {"budget_minor": 1_000_000_000, "workloads": ["GAMING_1080P"]},
            },
        ),
        201,
    )
    assert lead["contact_phone"] == "+998 90 *** ** 67" and lead["budget_minor"] == 1_000_000_000
    stored = _admin(world, "SELECT contact_phone_enc FROM commerce.leads WHERE id = $1", UUID(lead["id"]))
    assert PHONE not in stored[0]["contact_phone_enc"]  # shifrlangan
    events = _admin(
        world,
        "SELECT envelope FROM commerce.outbox_events WHERE aggregate_id = $1",
        UUID(lead["id"]),
    )
    assert events and all("Jasur" not in r["envelope"] and PHONE not in r["envelope"] for r in events)

    # Navbat: biriktirilmagan leadni operator o'ziga oladi
    queued = _ok(pc.post(pc.manager, "/leads", {"customer_name": "Navbat"}), 201)
    assert (
        queued["assigned"] is None
        and "TAKE" in _ok(pc.get(pc.sales2, f"/leads/{queued['id']}"))["allowed_actions"]
    )
    counts = _ok(pc.get(pc.sales2, "/leads/counts"))
    assert counts["unassigned"] >= 1 and counts["mine"] == 0
    taken = _ok(pc.post(pc.sales2, f"/leads/{queued['id']}/take", version=queued["version"]))
    assert taken["assigned"] is not None and _ok(pc.get(pc.sales2, "/leads/counts"))["mine"] == 1
    again = pc.post(pc.sales, f"/leads/{queued['id']}/take", version=taken["version"])
    assert again.status_code == 403  # endi boshqa operatorniki

    # Boshqa operator biriktirilgan leadni ko'rmaydi; omborchi — umuman
    assert pc.get(pc.sales2, f"/leads/{lead['id']}").status_code == 403
    assert pc.get(pc.warehouse, "/leads").status_code == 403
    assert pc.get(pc.warehouse, "/quotes").status_code == 403
    assert (
        world.client.get(
            f"/api/v1/shop/leads/{lead['id']}", headers=_bearer(other["owner_token"])
        ).status_code
        == 404
    )

    no_reason = pc.post(pc.sales, f"/leads/{lead['id']}/lose", {}, version=lead["version"])
    assert no_reason.status_code == 422
    lost = _ok(
        pc.post(pc.sales, f"/leads/{lead['id']}/lose", {"reason": "TOO_EXPENSIVE"}, version=lead["version"])
    )
    assert lost["status"] == "LOST" and lost["allowed_actions"] == ["REOPEN"]
    reopened = _ok(pc.post(pc.sales, f"/leads/{lead['id']}/reopen", version=lost["version"]))
    assert reopened["status"] == "QUALIFIED"
    history = _ok(pc.get(pc.sales, f"/leads/{lead['id']}/history"))["items"]
    assert [h["command"] for h in history] == ["LOSE", "REOPEN"]

    # Taklif boshqa shop egasiga ko'rinmaydi (IDOR)
    quote = pc.quote(pc.sales, lead_id=lead["id"])
    assert (
        world.client.get(
            f"/api/v1/shop/quotes/{quote['id']}", headers=_bearer(other["owner_token"])
        ).status_code
        == 404
    )
    rls = _sql(world.urls.runtime, "SELECT count(*) AS n FROM commerce.quotes")
    assert rls[0]["n"] == 0  # shop konteksti yo'q — RLS hech narsa bermaydi


def test_submitted_revision_is_frozen_in_the_database(world: World) -> None:
    pc = Pc(world)
    quote = pc.step(pc.sales, pc.quote(pc.sales), "submit")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        _admin(
            world,
            "UPDATE commerce.quote_lines SET qty = 5 WHERE quote_revision_id = $1",
            UUID(quote["revision_id"]),
        )


def test_lead_won_when_quote_order_completes(world: World) -> None:
    pc = Pc(world, risky_only=True)
    sku_stock = {"branch_id": pc.branch, "lines": [{"sku_id": s, "qty": 2} for s in pc.skus.values()]}
    _ok(pc.post(pc.owner, "/stock/receipts", sku_stock), 201)
    quote = pc.step(pc.sales, pc.quote(pc.sales), "submit")
    sent, _ = _sent(pc, quote)
    accepted = _ok(pc.post(pc.sales, f"/quotes/{quote['id']}/accept", version=sent["version"]))
    order = _ok(pc.get(pc.owner, f"/orders/{accepted['order_id']}"))
    patched = world.client.patch(
        f"/api/v1/shop/orders/{order['id']}",
        json={"branch_id": pc.branch, "customer_name": "Jasur", "customer_phone": PHONE},
        headers=_hdr(pc.owner, order["version"]),
    )
    order = _ok(patched)
    for step in ("submit", "confirm", "start-processing", "complete"):
        order = _ok(pc.post(pc.owner, f"/orders/{order['id']}/{step}", version=order["version"]))
    assert order["status"] == "COMPLETED"
    _drain_now(world)
    lead = _ok(pc.get(pc.owner, f"/leads/{quote['lead_id']}"))
    assert lead["status"] == "WON" and lead["won_order_id"] == order["id"]


def test_build_page_check_and_candidates(world: World) -> None:
    pc = Pc(world)
    partial = [{"sku_id": pc.skus["CPU"], "qty": 1}, {"sku_id": pc.skus["GPU"], "qty": 1}]
    check = _ok(pc.post(pc.sales, "/pc-builds/check", {"lines": partial, "full_build": False}))
    assert check["total_uzs_minor"] == 2 * 100_000_000 and check["compatibility"]["decision"] in (
        "PASS",
        "REVIEW_REQUIRED",
    )
    candidates = _ok(pc.post(pc.sales, "/pc-builds/candidates", {"role": "MOTHERBOARD", "lines": partial}))
    assert candidates["items"] and candidates["items"][0]["sku_id"] == pc.skus["MOTHERBOARD"]
    assert candidates["items"][0]["decision"] != "BLOCK"
    not_pc = pc.post(pc.sales, "/pc-builds/candidates", {"role": "MONITOR", "lines": partial})
    assert not_pc.status_code == 422
    assert pc.post(pc.warehouse, "/pc-builds/check", {"lines": partial}).status_code == 403
