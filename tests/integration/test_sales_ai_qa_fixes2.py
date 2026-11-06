# ruff: noqa: T201, F811
"""6b QA regressiyasi (2) — in-flight gate, sinov oynasi, takliflar, debounce.

Mustaqil QA (6b) topilmalari regressiya sifatida (scratchpad harness'dan ko'chirilgan). Har test —
hujjatdagi kutilgan xulq; dizayn ataylab o'zgargan joylarda kutilganlar yangilangan (M06b §11).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from app.platform.llm.providers.fake import FakeProvider, FakeText, FakeTools
from app.workers.queue import RecordingQueue
from app.workers.runtime import WorkerRuntime
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _ok
from tests.integration.test_jobs_events import _drain_now, _run
from tests.integration.test_messaging import Inbox, clean_outbox  # noqa: F401
from tests.integration.test_sales_ai import (  # noqa: F401
    _enable,
    _patch_settings,
    _product,
    _request_texts,
    _suggestions,
    _turns,
    fake,
)

pytestmark = pytest.mark.integration


def _say(*a: Any) -> None:
    """Diagnostika (pytest -s bilan ko'rinadi)."""
    print("QA-RESULT", *a)


def _luhn_complete(prefix: str) -> str:
    for d in "0123456789":
        s = prefix + d
        total, parity = 0, len(s) % 2
        for i, c in enumerate(s):
            n = int(c)
            if i % 2 == parity:
                n = n * 2 - 9 if n * 2 > 9 else n * 2
            total += n
        if total % 10 == 0:
            return s
    raise AssertionError


CARD = _luhn_complete("860031040123456")  # 16-digit Uzcard-like, Luhn-valid


@pytest.mark.parametrize(
    ("label", "fmt"),
    [
        ("spaces", lambda c: f"{c[:4]} {c[4:8]} {c[8:12]} {c[12:]}"),
        ("compact", lambda c: c),
        ("dashes", lambda c: f"{c[:4]}-{c[4:8]}-{c[8:12]}-{c[12:]}"),
        ("dots", lambda c: f"{c[:4]}.{c[4:8]}.{c[8:12]}.{c[12:]}"),
        ("slash", lambda c: f"{c[:4]}/{c[4:8]}/{c[8:12]}/{c[12:]}"),
        ("double_space", lambda c: f"{c[:4]}  {c[4:8]}  {c[8:12]}  {c[12:]}"),
    ],
)
def test_luhn_valid_card_formats(world: World, fake: FakeProvider, label: str, fmt: Any) -> None:
    inbox = Inbox(world)
    _enable(world, inbox, "AUTO")
    fake.push(FakeText("Karta [CARD_1]."))
    raw = fmt(CARD)
    inbox.text(f"kartam {raw} ga pul tashlayman")
    _drain_now(world)
    seen = _request_texts(fake)
    leaked = CARD[4:12] in seen.replace(" ", "").replace("-", "").replace(".", "").replace("/", "")
    sent = [t for _, _, t in inbox.fake.sent]
    _say("card_fmt", label, raw, "LEAKED" if leaked else "redacted", "sent=", sent)
    assert not leaked
    assert all(CARD[4:12] not in t.replace(" ", "") for t in sent)


def test_forged_branch_with_valid_contact(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    other = Shop(world)
    sku = _product(inbox.shop)
    _enable(world, inbox, "AUTO")
    fake.push(
        FakeTools(
            (
                (
                    "commerce_create_order_draft",
                    {
                        "lines": [{"sku_id": sku, "qty": 1}],
                        "fulfillment_method": "PICKUP",
                        "branch_id": other.branch,
                        "contact_ref": "PHONE_1",
                    },
                ),
            )
        ),
        FakeText("Operator bog'lanadi."),
    )
    inbox.text("Olaman, 90 765 43 21")
    _drain_now(world)
    [conv] = inbox.conversations()
    [turn] = _turns(world, inbox.owner, conv["id"])
    orders = _admin_sql(
        world, "SELECT id, branch_id::text AS b FROM commerce.orders WHERE shop_id = $1", inbox.shop.id
    )
    _say(
        "forged_branch",
        [(c["decision"], c["error_code"]) for c in turn["tool_calls"]],
        "orders=",
        [o["b"] for o in orders],
        "other_branch=",
        other.branch,
        "sent=",
        [t for _, _, t in inbox.fake.sent],
    )
    assert not any(o["b"] == str(other.branch) for o in orders)


def test_contact_ref_token_of_other_kind(world: World, fake: FakeProvider) -> None:
    """contact_ref must be PHONE_n; EMAIL token or another conversation's token resolves to nothing."""
    inbox = Inbox(world)
    sku = _product(inbox.shop)
    _enable(world, inbox, "AUTO")
    fake.push(FakeText("ok"))
    inbox.text("raqamim 90 111 22 33", user_id=5301)  # conv A gets PHONE_1 = 901112233
    _drain_now(world)
    fake.push(
        FakeTools(
            (
                (
                    "commerce_create_order_draft",
                    {
                        "lines": [{"sku_id": sku, "qty": 1}],
                        "fulfillment_method": "PICKUP",
                        "branch_id": inbox.shop.branch,
                        "contact_ref": "PHONE_1",
                    },
                ),
            )
        ),
        FakeText("Operator bog'lanadi."),
    )
    inbox.text("olaman", user_id=5302)  # conv B has no PHONE_1
    _drain_now(world)
    orders = _admin_sql(
        world, "SELECT customer_phone_hmac FROM commerce.orders WHERE shop_id = $1", inbox.shop.id
    )
    turns = _turns(world, inbox.owner, inbox.conversations()[0]["id"]) + _turns(
        world, inbox.owner, inbox.conversations()[1]["id"]
    )
    _say(
        "cross_conv_token",
        "orders=",
        len(orders),
        [o["customer_phone_hmac"] is not None for o in orders],
        [(c["tool"], c["error_code"]) for t in turns for c in t["tool_calls"]],
    )
    assert all(o["customer_phone_hmac"] is None for o in orders)


def test_kill_switch_during_inflight_turn(world: World, fake: FakeProvider) -> None:
    """Kill switch: 'true — AI darhol to'xtaydi'. Turn prepared before, finished after the switch."""
    inbox = Inbox(world)
    _enable(world, inbox, "AUTO")
    inbox.text("Salom")
    [conv] = inbox.conversations()
    mid = UUID(inbox.messages(conv["id"])[-1]["id"])

    async def prepare(rt: WorkerRuntime) -> Any:
        return await rt.services.sales_ai.runner(rt.database)._prepare(inbox.shop.id, UUID(conv["id"]), mid)

    prepared = _run(world, RecordingQueue(), prepare)
    _ok(_patch_settings(world, inbox.owner, {"kill_switch": True, "kill_switch_reason": "QA"}))
    fake.push(FakeText("AI javobi kill switchdan keyin"))

    async def finish(rt: WorkerRuntime) -> str:
        runner = rt.services.sales_ai.runner(rt.database)
        result = await runner.loop.run(prepared.system, prepared.history, prepared.ctx)
        return await runner._finish(inbox.shop.id, UUID(conv["id"]), prepared, result, 0.0)

    out = _run(world, RecordingQueue(), finish)
    _drain_now(world)
    sent = [t for _, _, t in inbox.fake.sent]
    _say("kill_inflight", out, sent)
    assert "AI javobi kill switchdan keyin" not in sent


def test_mode_auto_to_suggest_during_inflight_turn(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    _enable(world, inbox, "AUTO")
    inbox.text("Salom")
    [conv] = inbox.conversations()
    mid = UUID(inbox.messages(conv["id"])[-1]["id"])

    async def prepare(rt: WorkerRuntime) -> Any:
        return await rt.services.sales_ai.runner(rt.database)._prepare(inbox.shop.id, UUID(conv["id"]), mid)

    prepared = _run(world, RecordingQueue(), prepare)
    _ok(_patch_settings(world, inbox.owner, {"mode": "SUGGEST"}))
    fake.push(FakeText("AUTO javob"))

    async def finish(rt: WorkerRuntime) -> str:
        runner = rt.services.sales_ai.runner(rt.database)
        result = await runner.loop.run(prepared.system, prepared.history, prepared.ctx)
        return await runner._finish(inbox.shop.id, UUID(conv["id"]), prepared, result, 0.0)

    out = _run(world, RecordingQueue(), finish)
    _drain_now(world)
    _say("mode_inflight", out, [t for _, _, t in inbox.fake.sent])
    assert "AUTO javob" not in [t for _, _, t in inbox.fake.sent]


def test_max_turns_never_resets_after_resume(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    sales, _ = inbox.shop.staff("SALES")
    _enable(
        world,
        inbox,
        "AUTO",
        handoff_rules={"always_handoff_on": ["COMPLAINT"], "max_ai_turns_before_offer_human": 2},
    )
    for i in range(2):
        fake.push(FakeText(f"Javob {i}"))
        inbox.text(f"Savol {i}")
        _drain_now(world)
    [conv] = inbox.conversations()
    _ok(inbox.action(conv["id"], "take", token=sales))
    _ok(inbox.action(conv["id"], "resume-ai", token=sales))
    fake.push(FakeText("Javob after resume"))
    inbox.text("Yangi savol")
    _drain_now(world)
    turns = _turns(world, inbox.owner, conv["id"])
    _say(
        "max_turns_after_resume",
        [(t["outcome"], t["handoff_reason"]) for t in turns][:2],
        inbox.conversation(conv["id"])["status"],
        "sent=",
        [t for _, _, t in inbox.fake.sent],
    )
    assert turns[0]["outcome"] != "HANDOFF", (
        "after resume-ai the AI immediately hands off again (turn_count never resets)"
    )


def test_sandbox_write_tools_dry_and_nothing_persisted(world: World, fake: FakeProvider) -> None:
    shop = Shop(world)
    sku = _product(shop)
    before = {
        t: _admin_sql(world, f"SELECT count(*) AS n FROM {t} WHERE shop_id = $1", shop.id)[0]["n"]
        for t in (
            "commerce.leads",
            "commerce.quotes",
            "commerce.orders",
            "sales_ai.ai_turns",
            "sales_ai.ai_tool_executions",
            "sales_ai.ai_sessions",
            "platform.llm_pii_refs",
            "messaging.conversations",
        )
    }
    fake.push(
        FakeTools(
            (
                (
                    "commerce_create_order_draft",
                    {
                        "lines": [{"sku_id": sku, "qty": 1}],
                        "fulfillment_method": "PICKUP",
                        "branch_id": shop.branch,
                        "contact_ref": "PHONE_1",
                    },
                ),
                ("commerce_prepare_quote_draft", {"lines": [{"sku_id": sku, "qty": 1}]}),
                (
                    "commerce_capture_lead",
                    {"budget_uzs": 1, "workloads": [], "brand_prefs": [], "notes": None},
                ),
            )
        ),
        FakeText("Qoralama tayyor, operator [PHONE_1] ga qo'ng'iroq qiladi."),
    )
    r = _ok(
        world.client.post(
            "/api/v1/shop/ai/sandbox/messages",
            json={"text": "olaman 90 765 43 21"},
            headers=_bearer(shop.owner),
        )
    )
    after = {
        t: _admin_sql(world, f"SELECT count(*) AS n FROM {t} WHERE shop_id = $1", shop.id)[0]["n"]
        for t in before
    }
    _say(
        "sandbox_dry",
        r["outcome"],
        r["handoff_reason"],
        [(c["tool"], c["output"]) for c in r["turn"]["tool_calls"]],
        r["reply_text"],
    )
    _say("sandbox_dry counts", {k: (before[k], after[k]) for k in before})
    assert before == after
    assert "PHONE_1" not in (r["reply_text"] or "")
    # cached session contains no raw phone
    raw = None

    async def peek(rt: WorkerRuntime) -> Any:
        return await rt.services.sales_ai.sandbox.cache.get(f"sales_ai:sandbox:{shop.id}:{r['session_id']}")

    raw = _run(world, RecordingQueue(), peek)
    _say("sandbox_cache", raw)
    assert raw is None or "765 43" not in raw


def test_sandbox_ignores_kill_switch(world: World, fake: FakeProvider) -> None:
    shop = Shop(world)
    _ok(world.client.get("/api/v1/shop/ai/settings", headers=_bearer(shop.owner)))
    _ok(_patch_settings(world, shop.owner, {"kill_switch": True}))
    fake.push(FakeText("salom"))
    r = world.client.post(
        "/api/v1/shop/ai/sandbox/messages", json={"text": "salom"}, headers=_bearer(shop.owner)
    )
    _say("sandbox_kill_switch", r.status_code, r.text[:120])
    assert r.status_code == 503 and r.json()["error"]["details"]["reason"] == "KILL_SWITCH"  # F-31


def test_whitespace_suggestion_reaches_customer(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    sales, _ = inbox.shop.staff("SALES")
    _enable(world, inbox, "SUGGEST")
    fake.push(FakeText("Javob"))
    inbox.text("Savol")
    _drain_now(world)
    [conv] = inbox.conversations()
    [s] = _suggestions(world, sales, conv["id"])
    r = world.client.post(
        f"/api/v1/shop/conversations/{conv['id']}/ai/suggestions/{s['reply_id']}/send",
        json={"body": "   "},
        headers=_bearer(sales, **_idem()),
    )
    _drain_now(world)
    last = inbox.messages(conv["id"])[-1]
    _say(
        "ws_sent",
        r.status_code,
        repr(last["body"]),
        last["delivery_status"],
        "telegram sent=",
        inbox.fake.sent,
    )
    assert r.status_code == 422


def test_operator_reply_while_suggestion_pending(world: World, fake: FakeProvider) -> None:
    """Operator types own reply (no take) in SUGGEST, then sends the stale AI suggestion too."""
    inbox = Inbox(world)
    sales, _ = inbox.shop.staff("SALES")
    _enable(world, inbox, "SUGGEST")
    fake.push(FakeText("AI taklif"))
    inbox.text("Savol")
    _drain_now(world)
    [conv] = inbox.conversations()
    [s] = _suggestions(world, sales, conv["id"])
    rr = inbox.reply(conv["id"], "Operator javobi", token=sales)
    detail = inbox.conversation(conv["id"])
    r = world.client.post(
        f"/api/v1/shop/conversations/{conv['id']}/ai/suggestions/{s['reply_id']}/send",
        json={},
        headers=_bearer(sales, **_idem()),
    )
    _drain_now(world)
    _say(
        "reply_then_send",
        rr.status_code,
        detail["status"],
        detail["speaker_mode"],
        "send ->",
        r.status_code,
        "telegram:",
        [t for _, _, t in inbox.fake.sent],
    )


def test_discount_word_false_positive_cheaper_option(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    _enable(world, inbox, "AUTO")
    fake.push(FakeText("Ha, bor."))
    inbox.text("Arzonroq variant bormi? Qaytadan aytib bering")
    _drain_now(world)
    [conv] = inbox.conversations()
    [turn] = _turns(world, inbox.owner, conv["id"])
    _say("fp_handoff", turn["outcome"], turn["handoff_reason"], "llm calls", len(fake.requests))
    assert turn["handoff_reason"] not in ("DISCOUNT_REQUEST", "WARRANTY_OR_RETURN") and fake.requests  # F-28


def test_uz_cyrillic_handoff_notice(world: World, fake: FakeProvider) -> None:
    inbox = Inbox(world)
    _enable(world, inbox, "AUTO")
    inbox.text("Оператор билан гаплашмоқчиман")
    _drain_now(world)
    _say("uz_cyrl_notice", [t for _, _, t in inbox.fake.sent])
    assert [t for _, _, t in inbox.fake.sent] == [
        "Саволингизни операторимизга ўтказдим — тез орада жавоб беради."
    ]


def test_signals_payload_ids_only(world: World, fake: FakeProvider) -> None:
    import json as _json

    inbox = Inbox(world)
    _enable(world, inbox, "AUTO")
    fake.push(FakeText("Salom [PHONE_1]"))
    inbox.text("90 765 43 21")
    _drain_now(world)
    rows = _admin_sql(
        world, "SELECT event_type, envelope FROM sales_ai.outbox_events WHERE shop_id = $1", inbox.shop.id
    )
    payloads = [(r["event_type"], sorted(_json.loads(r["envelope"])["payload"].keys())) for r in rows]
    _say("signals", payloads)
    # Faqat payload: konvertdagi vaqt belgisi (mikrosekund) tasodifan "765" bo'lishi mumkin
    assert "765" not in str([_json.loads(r["envelope"])["payload"] for r in rows])


def test_takeover_during_debounce_leaves_turn_queued(world: World, fake: FakeProvider) -> None:
    from tests.integration.test_messaging import _drain_retrying

    inbox = Inbox(world)
    _enable(world, inbox, "SUGGEST")
    services = world.client.app.state.sales_ai
    services.debounce_s = 3600
    try:
        inbox.text("Salom")
        _drain_retrying(world, max_attempts=1)  # turn QUEUED, RetryLater
    finally:
        services.debounce_s = 0
    [conv] = inbox.conversations()
    _ok(inbox.action(conv["id"], "take"))
    # event retried after debounce
    from uuid import UUID as _U

    mid = _U(inbox.messages(conv["id"])[0]["id"])

    async def again(rt: WorkerRuntime) -> str:
        return await rt.services.sales_ai.runner(rt.database).on_message(inbox.shop.id, _U(conv["id"]), mid)

    out = _run(world, RecordingQueue(), again)
    turns = _turns(world, inbox.owner, conv["id"])
    _say("debounce_takeover", out, [(t["status"], t["outcome"]) for t in turns])
    assert turns[0]["status"] != "QUEUED", (
        "turn left QUEUED forever (later FAILED/NOT_STARTED by the stuck job)"
    )
