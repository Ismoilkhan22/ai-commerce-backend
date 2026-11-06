"""6a QA tekshiruvi topilmalari (F1–F19) — har biriga regressiya testi, haqiqiy PostgreSQL'da."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.integration.helpers import World, _bearer, _code, _idem
from tests.integration.test_catalog import _approved_spec, _platform_member
from tests.integration.test_jobs_events import _drain_now
from tests.integration.test_quotes import Pc, _admin, _ok, _sent

pytestmark = pytest.mark.integration


def _conversation(world: World, shop_id: str) -> str:
    """Shu shopda suhbat (5b jadvallari) — admin ulanishi bilan to'g'ridan yoziladi."""
    shop = UUID(shop_id)
    account = _admin(world, "SELECT id FROM messaging.channel_accounts WHERE shop_id = $1 LIMIT 1", shop)
    account_id = account[0]["id"] if account else uuid4()
    if not account:
        _admin(
            world,
            "INSERT INTO messaging.channel_accounts (id, shop_id, channel, status, account_ref, version) "
            "VALUES ($1, $2, 'WEB_CHAT', 'CONNECTED', $3, 1)",
            account_id,
            shop,
            uuid4().hex + uuid4().hex,
        )
    identity, conversation = uuid4(), uuid4()
    _admin(
        world,
        "INSERT INTO messaging.customer_identities (id, shop_id, channel, external_user_id, version) "
        "VALUES ($1, $2, 'WEB_CHAT', $3, 1)",
        identity,
        shop,
        uuid4().hex,
    )
    _admin(
        world,
        "INSERT INTO messaging.conversations "
        "(id, shop_id, customer_identity_id, channel_account_id, channel, version) "
        "VALUES ($1, $2, $3, $4, 'WEB_CHAT', 1)",
        conversation,
        shop,
        identity,
        account_id,
    )
    return str(conversation)


def _message_event(world: World, shop_id: str, conversation_id: str) -> None:
    """Suhbatga kiruvchi xabar event'i (messaging outbox) — 5b ingest'ini chetlab, faqat event."""
    from app.shared.db.session import Database, DatabaseConfig
    from app.shared.events.outbox import write_outbox
    from app.shared.types.actor import ActorContext

    async def run() -> None:
        database = Database(DatabaseConfig(url=world.urls.runtime))
        try:
            async with database.transaction(UUID(shop_id)) as db:
                await write_outbox(
                    db,
                    schema="messaging",
                    event_type="messaging.message.received",
                    actor=ActorContext.system(UUID(shop_id)),
                    shop_id=UUID(shop_id),
                    aggregate_type="messaging.message",
                    aggregate_id=uuid4(),
                    aggregate_version=1,
                    payload={"conversation_id": conversation_id, "seq": 1, "kind": "TEXT"},
                )
        finally:
            await database.dispose()

    asyncio.run(run())


def _quote_get(pc: Pc, token: str, quote_id: str, locale: str | None = None) -> dict[str, Any]:
    headers = _bearer(token, **({"Accept-Language": locale} if locale else {}))
    return _ok(pc.world.client.get(f"/api/v1/shop/quotes/{quote_id}", headers=headers))


# ------------------------------------------------------------------ F1: o'zi tuzganini tasdiqlamaydi


def test_creator_cannot_approve_after_return_or_revise(world: World) -> None:
    pc = Pc(world)
    quote = pc.quote(pc.manager)  # menejer tuzdi
    review = pc.step(pc.manager, quote, "submit")
    returned = pc.step(pc.owner, review, "return", {"reason": "QA qaytarildi"})
    again = pc.step(pc.manager, returned, "submit")
    assert "APPROVE" not in again["allowed_actions"]
    denied = pc.post(pc.manager, f"/quotes/{quote['id']}/approve", {}, version=again["version"])
    assert _code(denied) == "SELF_APPROVAL_NOT_ALLOWED"
    # Qaytargan ega qatorlarga tegmagan — qayta yuborilganini tasdiqlay oladi
    assert pc.step(pc.owner, again, "approve", {})["status"] == "APPROVED"

    # Revise yo'li: rad etildi → ega qayta ishladi → menejer tahrirlab yubordi → menejer tasdiqlay olmaydi
    sent, _ = _sent(pc, _ok(pc.get(pc.owner, f"/quotes/{quote['id']}")))
    rejected = pc.step(pc.owner, sent, "reject", {"reason": "QA rad"})
    revised = pc.step(pc.owner, rejected, "revise")
    edited = _ok(
        pc.world.client.put(
            f"/api/v1/shop/quotes/{quote['id']}/lines",
            json={"lines": pc.lines(CPU={"discount_pct": "5"})},
            headers=_bearer(pc.manager, **_idem(), **{"If-Match": f'"v{revised["version"]}"'}),
        )
    )
    submitted = pc.step(pc.manager, edited, "submit")
    blocked = pc.post(pc.manager, f"/quotes/{quote['id']}/approve", {}, version=submitted["version"])
    assert _code(blocked) == "SELF_APPROVAL_NOT_ALLOWED"


def test_manager_editing_operator_draft_cannot_approve_it(world: World) -> None:
    pc = Pc(world)
    quote = pc.quote(pc.sales)
    edited = _ok(
        pc.world.client.put(
            f"/api/v1/shop/quotes/{quote['id']}/lines",
            json={"lines": pc.lines(CPU={"discount_pct": "3"})},
            headers=_bearer(pc.manager, **_idem(), **{"If-Match": f'"v{quote["version"]}"'}),
        )
    )
    review = pc.step(pc.sales, edited, "submit")
    denied = pc.post(pc.manager, f"/quotes/{quote['id']}/approve", {}, version=review["version"])
    assert _code(denied) == "SELF_APPROVAL_NOT_ALLOWED"
    assert pc.step(pc.owner, review, "approve", {})["status"] == "APPROVED"


# ---------------------------------------------------- F2, F8: BLOCK yashirinmaydi, tafsilot shakli


def test_unlinked_sibling_keeps_block_and_rule_block_details(world: World) -> None:
    pc = Pc(world)
    unlinked_ssd = pc._product("STORAGE", "Noname", "SSD ???", model_name=f"SSD {uuid4().hex[:6]}")
    lines = [
        *pc.lines(skip=("STORAGE",)),
        {"sku_id": pc.skus["STORAGE"], "qty": 3},  # 3 ta NVMe, platada 2 ta M.2
        {"sku_id": unlinked_ssd, "qty": 1},
    ]
    check = _ok(pc.post(pc.owner, "/pc-builds/check", {"lines": lines}))
    rules = {f["rule_id"] for f in check["compatibility"]["findings"]}
    assert check["compatibility"]["decision"] == "BLOCK"
    assert {"STORAGE_M2_SLOTS", "UNLINKED_PART"} <= rules
    assert check["compatibility"]["ruleset_version"] == "pc-2026-10-v2"
    quote = pc.quote(pc.sales, lines)
    refused = pc.post(pc.sales, f"/quotes/{quote['id']}/submit", version=quote["version"])
    assert refused.status_code == 422 and _code(refused) == "RULE_BLOCK"
    details = refused.json()["error"]["details"]
    assert details["ruleset_version"] == "pc-2026-10-v2"
    assert {"rule_id": "STORAGE_M2_SLOTS", "severity": "BLOCK"} in details["findings"]


# ---------------------------------------------------- F3: til — so'rov tilida, snapshot qayta yasaladi


def test_compat_text_follows_request_locale_and_snapshots_store_keys(world: World) -> None:
    pc = Pc(world)
    lines = [*pc.lines(skip=("GPU",)), {"sku_id": pc.unlinked_gpu, "qty": 1}]

    def explanation(locale: str) -> str:
        headers = _bearer(pc.owner, **_idem(), **{"Accept-Language": locale})
        out = _ok(
            pc.world.client.post("/api/v1/shop/pc-builds/check", json={"lines": lines}, headers=headers)
        )
        return str(
            next(f for f in out["compatibility"]["findings"] if f["rule_id"] == "UNLINKED_PART")[
                "explanation"
            ]
        )

    uz, ru, en = explanation("uz"), explanation("ru"), explanation("en")
    assert len({uz, ru, en}) == 3

    quote = pc.step(pc.sales, pc.quote(pc.sales, lines), "submit")
    assert quote["compatibility"]["decision"] == "REVIEW_REQUIRED"
    texts = {
        loc: next(
            f["explanation"]
            for f in _quote_get(pc, pc.owner, quote["id"], loc)["compatibility"]["findings"]
            if f["rule_id"] == "UNLINKED_PART"
        )
        for loc in ("uz", "ru", "en")
    }
    assert len(set(texts.values())) == 3
    stored = _admin(
        world,
        "SELECT s.findings FROM commerce.quote_compatibility_snapshots s JOIN commerce.quote_revisions r "
        "ON r.id = s.quote_revision_id WHERE r.quote_id = $1",
        UUID(quote["id"]),
    )
    findings = (
        json.loads(stored[0]["findings"]) if isinstance(stored[0]["findings"], str) else stored[0]["findings"]
    )
    assert findings and all("explanation" not in f and f["message_key"] for f in findings)


# ------------------------------------------------------------------ F4, F5, F11: suhbat orqali lead


def test_conversation_lead_visibility_race_and_shop_check(world: World) -> None:
    pc = Pc(world)
    conversation = _conversation(world, pc.shop_id)
    lead = _ok(pc.post(pc.sales, "/leads", {"conversation_id": conversation, "customer_name": "QA Ali"}), 201)
    assert lead["assigned"]["membership_id"] == pc.sales_id
    # Boshqa operator shu suhbat orqali leadni ham, taklif orqali ham ola olmaydi (F4)
    other = pc.post(pc.sales2, "/leads", {"conversation_id": conversation})
    assert other.status_code == 403
    assert pc.post(pc.sales2, "/quotes", {"conversation_id": conversation, "lines": []}).status_code == 403
    assert "customer_name" not in other.text
    # Begona yoki yo'q suhbat — 422 (F11)
    foreign = _conversation(world, world.create_shop()["shop"]["id"])
    for conv in (foreign, str(uuid4())):
        bad = pc.post(pc.owner, "/leads", {"conversation_id": conv})
        assert bad.status_code == 422 and "conversation_id" in bad.text
    # Parallel yaratish: bitta lead, 500 yo'q (F5)
    fresh = _conversation(world, pc.shop_id)

    def create(_: int) -> int:
        return int(pc.post(pc.owner, "/leads", {"conversation_id": fresh}).status_code)

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(create, range(6)))
    assert all(code in (200, 201) for code in statuses), statuses
    count = _admin(world, "SELECT count(*) AS n FROM commerce.leads WHERE conversation_id = $1", UUID(fresh))
    assert count[0]["n"] == 1

    fresh2 = _conversation(world, pc.shop_id)

    def quote(_: int) -> int:
        return int(pc.post(pc.owner, "/quotes", {"conversation_id": fresh2, "lines": []}).status_code)

    with ThreadPoolExecutor(max_workers=4) as pool:
        quote_statuses = list(pool.map(quote, range(4)))
    assert all(code == 201 for code in quote_statuses), quote_statuses


# ---------------------------------------------------- F6: nomzodlar — mos va omborda borlari birinchi


def test_candidates_find_compatible_beyond_decoys(world: World) -> None:
    pc = Pc(world)
    editor = _platform_member(world)
    tag = uuid4().hex[:5].upper()
    _approved_spec(
        world,
        editor,
        category="CPU",
        brand="Intel",
        model_name=f"Core i5 {tag}",
        attributes={"socket": "LGA1700", "memory_types": ["DDR5"], "max_power_w": 117, "base_power_w": 65},
    )
    for i in range(42):
        pc._product("CPU", "Intel", f"Aaa decoy {i:02d} {tag}", model_name=f"Core i5 {tag}")
    out = _ok(
        pc.post(
            pc.owner,
            "/pc-builds/candidates",
            {"role": "CPU", "lines": [{"sku_id": pc.skus["MOTHERBOARD"]}, {"sku_id": pc.skus["RAM"]}]},
        )
    )
    assert out["items"] and out["items"][0]["sku_id"] == pc.skus["CPU"]
    assert out["items"][0]["decision"] != "BLOCK"
    only = _ok(
        pc.post(
            pc.owner,
            "/pc-builds/candidates",
            {"role": "CPU", "only_compatible": True, "lines": [{"sku_id": pc.skus["MOTHERBOARD"]}]},
        )
    )
    assert [c["sku_id"] for c in only["items"]] == [pc.skus["CPU"]]


# ------------------------------------------------------------------ F7: takror ham huquq tekshiruvidan o'tadi


def test_send_replay_is_reauthorized(world: World) -> None:
    pc = Pc(world)
    approved = pc.step(pc.owner, pc.step(pc.sales, pc.quote(pc.sales), "submit"), "approve", {})
    key = _idem()
    headers = {**_bearer(pc.sales), **key, "If-Match": f'"v{approved["version"]}"'}
    sent = world.client.post(f"/api/v1/shop/quotes/{approved['id']}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    replay = world.client.post(
        f"/api/v1/shop/quotes/{approved['id']}/send",
        headers={**_bearer(pc.sales2), **key, "If-Match": f'"v{approved["version"]}"'},
    )
    assert replay.status_code == 403
    token = sent.json()["public_path"].removeprefix("/q/")
    assert world.client.get(pc.public(f"/quotes/{token}")).status_code == 200  # havola buzilmadi


# ------------------------------------------------------------------ F10, F12: yopilgan lead


def test_lost_lead_cancels_open_quotes_and_closed_lead_is_frozen(world: World) -> None:
    pc = Pc(world)
    draft = pc.quote(pc.sales)
    sent, token = _sent(
        pc,
        pc.step(
            pc.owner, pc.step(pc.sales, pc.quote(pc.sales, lead_id=draft["lead_id"]), "submit"), "approve", {}
        ),
    )
    lead = _ok(pc.get(pc.sales, f"/leads/{draft['lead_id']}"))
    lose = {"reason": "TOO_EXPENSIVE"}
    lost = _ok(pc.post(pc.sales, f"/leads/{lead['id']}/lose", lose, version=lead["version"]))
    assert lost["status"] == "LOST"
    assert {q["status"] for q in lost["quotes"]} == {"CANCELLED"}
    assert world.client.get(pc.public(f"/quotes/{token}")).status_code == 404  # havola o'chdi
    assert sent["status"] == "SENT"
    tasks = _admin(
        world,
        "SELECT count(*) AS n FROM platform.staff_tasks "
        "WHERE subject_id = ANY($1::uuid[]) AND status = 'OPEN'",
        [UUID(draft["id"]), UUID(sent["id"])],
    )
    assert tasks[0]["n"] == 0
    # Yopilgan leadni tahrirlab va biriktirib bo'lmaydi (F10)
    patch = world.client.patch(
        f"/api/v1/shop/leads/{lead['id']}",
        json={"customer_name": "QA"},
        headers=_bearer(pc.owner, **_idem(), **{"If-Match": f'"v{lost["version"]}"'}),
    )
    assert patch.status_code == 409
    assign = pc.post(
        pc.owner, f"/leads/{lead['id']}/assign", {"membership_id": None}, version=lost["version"]
    )
    assert assign.status_code == 409


# ------------------------------------------------------------------ F13, F15, F16: qabul va xaridor sahifasi


def test_accept_detects_new_review_rule_and_public_view_hides_internals(world: World) -> None:
    pc = Pc(world)
    # Bog'lanmagan GPU — REVIEW; dalil bilan tasdiqlanadi
    risky_lines = [*pc.lines(skip=("GPU",)), {"sku_id": pc.unlinked_gpu, "qty": 1}]
    review = pc.step(pc.sales, pc.quote(pc.sales, risky_lines), "submit")
    approved = pc.step(pc.manager, review, "approve", {"note": "QA mutaxassis tekshirdi"})
    _, token = _sent(pc, approved)
    view = _ok(world.client.get(pc.public(f"/quotes/{token}")))
    compat = view["compatibility"]
    assert compat["expert_checked"] is True and compat["note"]
    dumped = json.dumps(view)
    for internal in ("UNLINKED_PART", "MISSING_ATTRIBUTE", "QA mutaxassis tekshirdi", "kutubxona"):
        assert internal not in dumped
    # Yuborilgandan keyin boshqa qism bog'lanishi uzildi — yangi REVIEW qoidasi → QUOTE_CHANGED (F13)
    pass_quote = pc.step(pc.manager, pc.step(pc.sales, pc.quote(pc.sales), "submit"), "approve", {})
    _, token2 = _sent(pc, pass_quote)
    _admin(world, "DELETE FROM catalog.sku_spec_links WHERE sku_id = $1", UUID(pc.skus["CASE"]))
    changed = world.client.post(pc.public(f"/quotes/{token2}/accept"), headers=_idem())
    assert changed.status_code == 409 and _code(changed) == "QUOTE_CHANGED"
    assert "UNLINKED_PART" in json.dumps(changed.json()["error"]["details"]) or "new_rule_ids" in changed.text
    # Muddati o'tgan taklifni rad ham qilib bo'lmaydi (F15)
    _admin(
        world,
        "UPDATE commerce.quotes SET expires_at = now() - interval '1 minute' WHERE id = $1",
        UUID(approved["id"]),
    )
    expired = world.client.post(pc.public(f"/quotes/{token}/reject"), json={"reason": "QA"}, headers=_idem())
    assert expired.status_code == 409 and _code(expired) == "QUOTE_EXPIRED"


# ---------------------------------------------------- F14, F17, F19 va frontend so'ragan maydonlar


def test_availability_activity_branch_scope_and_list_fields(world: World) -> None:
    pc = Pc(world)
    conversation = _conversation(world, pc.shop_id)
    quote = pc.quote(pc.sales, conversation_id=conversation)
    assert quote["availability"] and all(
        a["available"] == 0 and a["enough"] is False for a in quote["availability"]
    )
    assert quote["revisions"][0]["created_at"]
    items = _ok(pc.get(pc.sales, "/quotes"))["items"]
    assert "customer_name" in items[0]
    lead = _ok(pc.get(pc.sales, f"/leads/{quote['lead_id']}"))
    assert lead["orders"] == []
    assert _ok(pc.get(pc.owner, "/leads?source=STAFF"))["items"]
    assert _ok(pc.get(pc.owner, "/leads?source=AI"))["items"] == []
    # Suhbatdagi xabar → lead faolligi (F17)
    _admin(
        world,
        "UPDATE commerce.leads SET last_activity_at = now() - interval '40 days' WHERE id = $1",
        UUID(lead["id"]),
    )
    _message_event(world, pc.shop_id, conversation)
    _drain_now(world)
    fresh = _admin(
        world,
        "SELECT last_activity_at > now() - interval '1 day' AS ok FROM commerce.leads WHERE id = $1",
        UUID(lead["id"]),
    )
    assert fresh[0]["ok"] is True
    # Filial doirasi (F19): boshqa shop filiali — 422
    other_branch = world.branch(world.create_shop()["owner_token"])["id"]
    bad = pc.post(pc.owner, "/pc-builds/check", {"lines": pc.lines(), "branch_id": other_branch})
    assert bad.status_code == 422
