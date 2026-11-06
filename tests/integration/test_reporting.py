"""7c-modul (hisobot read model va API): proyeksiya to'g'riligi, idempotentlik, PARTIAL_COST_DATA,
Toshkent kuni chegarasi, ruxsatlar, RLS, CSV xavfsizligi, qayta qurish — PostgreSQL'da, HTTP orqali.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.domains.reporting.backfill import rebuild_shop
from app.domains.reporting.models.orm import MessageFact, OrderFact, OrderLineFact
from app.domains.reporting.projections import apply_event
from app.domains.reporting.services.export import safe_cell, to_csv
from app.shared.db.session import Database
from app.shared.events.envelope import EventActor, EventEnvelope
from app.shared.events.models import OUTBOX_SCHEMAS
from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import PHONE, Shop, _admin_sql, _hdr, _ok, _post
from tests.integration.test_jobs_events import _drain_now, _events, _job
from tests.integration.test_support import Warranty

pytestmark = pytest.mark.integration

R = "/api/v1/shop/reporting"
PRICE = 480_000_000  # 4 800 000 so'm, tiyinda
COST = 300_000_000


@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> Iterator[None]:
    """Oldingi testlarning PENDING event'lari shu testning proyeksiyasiga aralashmasin."""
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )
    yield


# ------------------------------------------------------------------ yordamchilar
def _get(shop: Shop, path: str, token: str | None = None, **params: Any) -> dict[str, Any]:
    response = shop.world.client.get(f"{R}{path}", params=params, headers=_bearer(token or shop.owner))
    return _ok(response)


def _in_db[T](world: World, shop_id: UUID, fn: Callable[..., Awaitable[T]]) -> T:
    """Shop kontekstida (RLS) bitta tranzaksiya; `fn(db, services)`."""

    async def go() -> T:
        database = Database(world.settings.database_config())
        try:
            async with database.transaction(shop_id) as db:
                return await fn(db, world.client.app.state.reporting)
        finally:
            await database.dispose()

    return asyncio.run(go())


def _env(
    shop: Shop,
    event_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
    at: datetime,
    *,
    version: int = 1,
    actor: EventActor | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type=event_type,
        shop_id=shop.id,
        aggregate_type=event_type.rsplit(".", 1)[0],
        aggregate_id=aggregate_id,
        aggregate_version=version,
        occurred_at=at,
        actor=actor or EventActor(kind="SYSTEM", id=None),
        payload=payload,
    )


def _apply(shop: Shop, *envelopes: EventEnvelope, times: int = 1) -> None:
    async def go(db: Any, services: Any) -> None:
        for _ in range(times):
            for envelope in envelopes:
                await apply_event(db, services.catalog, envelope)

    _in_db(shop.world, shop.id, go)


def _completed(shop: Shop, at: datetime, total: int = 100_000, **extra: Any) -> EventEnvelope:
    order_id = uuid4()
    payload = {
        "order_id": order_id,
        "status": "COMPLETED",
        "source": "AI",
        "branch_id": UUID(shop.branch),
        "total_minor": total,
        "currency": "UZS",
        "lines": [],
        **extra,
    }
    return _env(shop, "commerce.order.completed", order_id, payload, at, version=5)


def _receive_cost(shop: Shop, sku: str, qty: int, cost: int | None) -> None:
    line: dict[str, Any] = {"sku_id": sku, "qty": qty}
    if cost is not None:
        line.update(unit_cost_minor=cost, cost_currency="UZS")
    _ok(_post(shop.world, shop.owner, "/stock/receipts", {"branch_id": shop.branch, "lines": [line]}), 201)


def _sell(shop: Shop, sku: str, qty: int = 1) -> dict[str, Any]:
    return shop.step(shop.order({sku: qty}), "submit", "confirm", "start-processing", "complete")


def _quick_sale(shop: Shop, sku: str, qty: int = 1) -> dict[str, Any]:
    body = {"branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": qty}]}
    return _ok(_post(shop.world, shop.owner, "/quick-sales", body), 201)


def _stocked(shop: Shop, cost: int | None, qty: int = 5) -> str:
    sku = shop.sku(PRICE)
    _receive_cost(shop, sku, qty, cost)
    return sku


# ------------------------------------------------------------------ sotuv va foyda
def test_sales_reports_from_events(world: World) -> None:
    shop = Shop(world)
    sku = _stocked(shop, COST)
    _sell(shop, sku, 2)  # buyurtma: 2 dona
    _quick_sale(shop, sku, 1)  # do'kondagi tez sotuv: 1 dona
    _drain_now(world)

    summary = _get(shop, "/sales/summary")
    assert (summary["orders_count"], summary["orders_amount_minor"]) == (1, 2 * PRICE)
    assert (summary["quick_sales_count"], summary["quick_sales_amount_minor"]) == (1, PRICE)
    assert (summary["total_count"], summary["total_amount_minor"], summary["units_sold"]) == (2, 3 * PRICE, 3)
    assert summary["average_ticket_minor"] == 3 * PRICE // 2
    assert {r["source"] for r in summary["by_source"]} == {"STAFF", "OFFLINE"}
    assert summary["by_branch"] == [{"branch_id": shop.branch, "count": 2, "amount_minor": 3 * PRICE}]
    assert summary["data_as_of"] is not None
    assert summary["period"]["timezone"] == "Asia/Tashkent"

    assert _get(shop, "/sales/summary", source="OFFLINE")["total_amount_minor"] == PRICE
    assert _get(shop, "/sales/summary", branch_id=shop.branch2)["total_count"] == 0

    daily = _get(shop, "/sales/daily")
    assert len(daily["days"]) == 30
    assert sum(d["total_amount_minor"] for d in daily["days"]) == 3 * PRICE

    top = _get(shop, "/sales/top-products")["items"]
    assert [(t["sku_id"], t["qty"], t["amount_minor"]) for t in top] == [(sku, 3, 3 * PRICE)]
    assert top[0]["title"].startswith("Test GPU")
    categories = _get(shop, "/sales/by-category")["items"]
    assert [(c["category_code"], c["qty"]) for c in categories] == [("GPU", 3)]

    profit = _get(shop, "/profit")
    assert profit["gross_profit_minor"] == 3 * (PRICE - COST)
    assert profit["cost_coverage_percent"] == 100.0 and profit["quality_flags"] == []
    stock = _get(shop, "/stock-value")  # soatlik ish hali ishlamagan
    assert stock["as_of_day"] is None and stock["value_at_price_minor"] == 0


def test_profit_flags_partial_and_missing_cost(world: World) -> None:
    shop = Shop(world)
    costed, plain = _stocked(shop, COST), _stocked(shop, None)
    _sell(shop, costed)
    _sell(shop, plain)
    _drain_now(world)
    profit = _get(shop, "/profit")
    assert profit["quality_flags"] == ["PARTIAL_COST_DATA"]
    assert profit["revenue_minor"] == 2 * PRICE and profit["covered_revenue_minor"] == PRICE
    assert profit["cost_coverage_percent"] == 50.0
    assert profit["gross_profit_minor"] == PRICE - COST  # faqat tannarxi ma'lum qator
    assert (profit["lines_count"], profit["lines_without_cost"]) == (2, 1)

    other = Shop(world)  # umuman tannarx yo'q: foyda raqami aytilmaydi
    _sell(other, _stocked(other, None))
    _drain_now(world)
    none = _get(other, "/profit")
    assert none["quality_flags"] == ["NO_COST_DATA"]
    assert none["gross_profit_minor"] is None and none["gross_margin_percent"] is None
    assert none["cost_minor"] is None  # tannarx yo'q: 0 emas, null (F8)
    assert none["cost_coverage_percent"] == 0.0 and none["revenue_minor"] == PRICE

    empty = _get(Shop(world), "/profit")  # sotuv yo'q: bayroq ham, raqam ham yo'q
    assert empty["quality_flags"] == [] and empty["gross_profit_minor"] is None


def test_cost_is_frozen_at_completion(world: World) -> None:
    """Tannarx keyin o'zgarsa, topshirilgan buyurtma foydasi o'zgarmaydi (qator nusxasi, DEC-146)."""
    shop = Shop(world)
    sku = _stocked(shop, COST)
    _sell(shop, sku)
    _receive_cost(shop, sku, 10, COST * 3)  # o'rtacha tannarx ko'tarildi
    _drain_now(world)
    assert _get(shop, "/profit")["gross_profit_minor"] == PRICE - COST


# ------------------------------------------------------------------ idempotentlik
def test_replayed_events_do_not_double_count(world: World) -> None:
    shop = Shop(world)
    sku = _stocked(shop, COST)
    _sell(shop, sku, 2)
    _quick_sale(shop, sku)
    _drain_now(world)
    before = {p: _get(shop, p) for p in ("/sales/summary", "/profit", "/sales/top-products")}

    # 1) o'sha event/tinglovchi qayta yetkazilsa — consumer_receipts
    envelopes = [
        EventEnvelope.model_validate(e["envelope"])
        for schema in ("commerce",)
        for e in _events(world, schema, shop.id)
    ]
    assert envelopes
    # 2) receipt'dan o'tib ketgan takror (masalan, 7 kundan keyin dead-letter replay) — proyeksiyaning o'zi
    _apply(shop, *envelopes, times=3)
    after = {p: _get(shop, p) for p in before}
    for path, report in before.items():
        assert after[path] == report, path


def test_older_event_does_not_overwrite_newer(world: World) -> None:
    shop = Shop(world)
    order_id = uuid4()
    at = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    base = {"order_id": order_id, "source": "AI", "total_minor": 500, "currency": "UZS"}
    done = _env(
        shop,
        "commerce.order.completed",
        order_id,
        {**base, "status": "COMPLETED", "lines": []},
        at,
        version=5,
    )
    stale = _env(shop, "commerce.order.confirmed", order_id, {**base, "status": "CONFIRMED"}, at, version=3)
    _apply(shop, done, stale)

    async def status(db: Any, _: Any) -> str:
        return str(await db.scalar(select(OrderFact.status).where(OrderFact.order_id == order_id)))

    assert _in_db(world, shop.id, status) == "COMPLETED"


def test_legacy_event_without_lines_keeps_line_facts(world: World) -> None:
    """F2: `lines` kaliti yo'q eski event mavjud qator faktlarini o'chirmasligi kerak."""
    shop = Shop(world)
    order = _sell(shop, _stocked(shop, COST))
    _drain_now(world)
    order_id = UUID(order["id"])

    async def count(db: Any, _: Any) -> int:
        return int(
            await db.scalar(
                select(func.count()).select_from(OrderLineFact).where(OrderLineFact.order_id == order_id)
            )
        )

    assert _in_db(world, shop.id, count) == 1
    payload = {"order_id": order_id, "status": "COMPLETED", "source": "AI", "total_minor": PRICE}
    at = datetime.now(UTC)
    legacy = _env(shop, "commerce.order.completed", order_id, payload, at, version=99)
    _apply(shop, legacy)
    assert _in_db(world, shop.id, count) == 1
    assert _get(shop, "/profit")["cost_minor"] == COST
    # `lines: []` esa aniq "qatorlar yo'q" — almashtiriladi
    _apply(shop, _env(shop, "commerce.order.completed", order_id, {**payload, "lines": []}, at, version=100))
    assert _in_db(world, shop.id, count) == 0


# ------------------------------------------------------------------ Toshkent kuni
def test_day_boundaries_are_tashkent_time(world: World) -> None:
    shop = Shop(world)
    # UTC 18:59:59 = Toshkent 23:59:59 (26-oktabr); UTC 19:00:00 = Toshkent 00:00:00 (27-oktabr)
    late = _completed(shop, datetime(2026, 10, 26, 18, 59, 59, tzinfo=UTC), total=100)
    early = _completed(shop, datetime(2026, 10, 26, 19, 0, 0, tzinfo=UTC), total=200)
    _apply(shop, late, early)
    daily = _get(shop, "/sales/daily", **{"from": "2026-10-26", "to": "2026-10-27"})
    assert [(d["day"], d["orders_count"], d["orders_amount_minor"]) for d in daily["days"]] == [
        ("2026-10-26", 1, 100),
        ("2026-10-27", 1, 200),
    ]
    only_27 = _get(shop, "/sales/summary", **{"from": "2026-10-27", "to": "2026-10-27"})
    assert only_27["orders_amount_minor"] == 200


def test_period_validation(world: World) -> None:
    shop = Shop(world)
    for params in ({"from": "2026-10-27", "to": "2026-10-01"}, {"from": "2020-01-01", "to": "2026-10-01"}):
        response = world.client.get(f"{R}/sales/summary", params=params, headers=_bearer(shop.owner))
        assert response.status_code == 422, response.text


# ------------------------------------------------------------------ ombor qiymati va AI xarajati (soatlik)
def test_stock_value_snapshot_job(world: World) -> None:
    shop = Shop(world)
    costed, plain = _stocked(shop, COST, qty=4), _stocked(shop, None, qty=2)
    _drain_now(world)
    _job(world, "reporting_stock_value")
    stock = _get(shop, "/stock-value")
    assert stock["units"] == 6
    assert stock["value_at_price_minor"] == 6 * PRICE
    assert stock["value_at_cost_minor"] == 4 * COST  # tannarxi noma'lum donalar qiymatga kirmaydi
    assert stock["units_without_cost"] == 2 and stock["quality_flags"] == ["PARTIAL_COST_DATA"]
    assert [b["branch_id"] for b in stock["branches"]] == [shop.branch]
    assert len(stock["series"]) == 1
    _job(world, "reporting_stock_value")  # qayta ishga tushsa ham bir xil
    assert _get(shop, "/stock-value")["value_at_price_minor"] == 6 * PRICE
    _ = (costed, plain)


def test_ai_usage_rollup_job(world: World) -> None:
    shop = Shop(world)
    now = datetime.now(UTC)
    for purpose, cost, tokens in (("SALES_TURN", 3000, 100), ("SALES_TURN", 2000, 50), ("CLASSIFY", 600, 10)):
        _admin_sql(
            world,
            "INSERT INTO platform.ai_usage (id, shop_id, provider, model_id, purpose, tokens_in, tokens_out, "
            "cost_micros, occurred_at) VALUES ($1, $2, 'fake', 'fake-seller', $3, $4, 5, $5, $6)",
            uuid4(),
            shop.id,
            purpose,
            tokens,
            cost,
            now,
        )
    _job(world, "reporting_ai_usage")
    _job(world, "reporting_ai_usage")  # idempotent
    usage = _get(shop, "/ai-usage")
    assert (usage["calls"], usage["tokens_in"], usage["tokens_out"], usage["cost_micros"]) == (
        3,
        160,
        15,
        5600,
    )
    assert {r["key"]: r["calls"] for r in usage["by_purpose"]} == {"SALES_TURN": 2, "CLASSIFY": 1}
    assert len(usage["by_day"]) == 1


# ------------------------------------------------------------------ operatorlar
def test_operator_metrics_and_replay(world: World) -> None:
    shop = Shop(world)
    staff_id, ai_actor = uuid4(), EventActor(kind="AI", id=None)
    staff = EventActor(kind="STAFF", id=staff_id)
    t0 = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)
    conv, conv2, handoff = uuid4(), uuid4(), uuid4()
    msg = {"conversation_id": conv, "channel": "TELEGRAM"}

    def message(
        kind: str, offset: int, payload: dict[str, Any], actor: EventActor | None = None
    ) -> EventEnvelope:
        return _env(shop, kind, uuid4(), payload, t0 + timedelta(seconds=offset), actor=actor)

    events = [
        message("messaging.message.received", 0, msg),
        message("messaging.message.queued", 30, {**msg, "origin": "GREETING"}),  # salom: javob hisoblanmaydi
        message("messaging.message.queued", 240, {**msg, "origin": "STAFF"}, staff),  # 240 s
        message("messaging.message.sent", 241, msg),  # yetkazish tasdig'i: hisobga olinmaydi
        message("messaging.message.received", 300, {"conversation_id": conv2, "channel": "TELEGRAM"}),
        message(
            "messaging.message.queued",
            310,
            {"conversation_id": conv2, "channel": "TELEGRAM", "origin": "AI_AUTO"},
            ai_actor,
        ),
        _env(
            shop,
            "messaging.conversation.handed_off",
            conv,
            {**msg, "handoff_id": handoff, "reason_code": "CUSTOMER_REQUEST"},
            t0 + timedelta(seconds=400),
        ),
        _env(shop, "messaging.conversation.taken", conv, msg, t0 + timedelta(seconds=460), actor=staff),
    ]
    _apply(shop, *events, times=2)  # ikki marta qo'llash natijani o'zgartirmaydi
    ops = _get(shop, "/operators", **{"from": "2026-10-20", "to": "2026-10-20"})
    assert (ops["inbound_messages"], ops["staff_replies"], ops["ai_replies"]) == (2, 1, 1)
    assert ops["ai_reply_share_percent"] == 50.0
    assert (ops["conversations_started"], ops["handoffs_opened"], ops["handoffs_taken"]) == (2, 1, 1)
    assert ops["handoff_wait_p50_seconds"] == 60
    assert ops["response_p50_seconds"] == 125  # 240 va 10 s ning mediani
    [operator] = ops["operators"]
    assert operator["staff_id"] == str(staff_id) and operator["replies_count"] == 1
    assert operator["response_p50_seconds"] == 240 and operator["handoffs_taken"] == 1

    async def counters(db: Any, _: Any) -> tuple[int, int]:
        count = await db.scalar(select(func.count()).select_from(MessageFact))
        slow = await db.scalar(select(func.count()).where(MessageFact.response_seconds.is_not(None)))
        return int(count), int(slow)

    assert _in_db(world, shop.id, counters) == (5, 2)  # 2 kiruvchi, salom, odam, AI; ikkitasida javob vaqti


# ------------------------------------------------------------------ kafolat
def test_warranty_stats(world: World) -> None:
    w = Warranty(world)
    case = w.opened()
    w.to_service(w.opened(), "REPAIR")
    _drain_now(world)
    stats = _get(w.shop, "/warranty")
    assert stats["opened_count"] == 2 and stats["within_warranty_count"] == 2
    assert {r["key"] for r in stats["by_type"]} == {"WARRANTY"}
    assert sum(r["count"] for r in stats["by_status"]) == 2
    assert stats["top_skus"][0]["sku_id"] == w.sku and stats["top_skus"][0]["count"] == 2
    _ = case


# ------------------------------------------------------------------ ruxsat va RLS
def test_permissions(world: World) -> None:
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    sales, _ = shop.staff("SALES")
    warehouse, _ = shop.staff("WAREHOUSE")
    paths = (
        "/sales/summary",
        "/sales/daily",
        "/stock-value",
        "/operators",
        "/ai-usage",
        "/warranty",
    )
    for token in (shop.owner, manager):
        for path in paths:
            assert world.client.get(f"{R}{path}", headers=_bearer(token)).status_code == 200, path
    assert world.client.get(f"{R}/profit", headers=_bearer(shop.owner)).status_code == 200
    for token in (sales, warehouse):
        for path in (*paths, "/profit", "/export?report=profit"):
            response = world.client.get(f"{R}{path}", headers=_bearer(token))
            assert response.status_code == 403, (path, response.status_code)
    assert world.client.get(f"{R}/sales/summary").status_code == 401


def test_manager_never_sees_cost_or_profit(world: World) -> None:
    """DEC-146: tannarx, foyda va AI xarajatini faqat ega ko'radi (`reporting.margin.read`)."""
    shop = Shop(world)
    manager, _ = shop.staff("MANAGER")
    _sell(shop, _stocked(shop, COST))
    _admin_sql(
        world,
        "INSERT INTO platform.ai_usage (id, shop_id, provider, model_id, purpose, tokens_in, tokens_out, "
        "cost_micros, occurred_at) VALUES ($1, $2, 'fake', 'fake-seller', 'SALES_TURN', 10, 5, 777, now())",
        uuid4(),
        shop.id,
    )
    _drain_now(world)
    _job(world, "reporting_stock_value")
    _job(world, "reporting_ai_usage")
    # ega — hammasi bor
    assert _get(shop, "/profit")["cost_minor"] == COST
    assert _get(shop, "/stock-value")["value_at_cost_minor"] == 4 * COST
    assert _get(shop, "/ai-usage")["cost_micros"] == 777
    # menejer — /profit 403, boshqalarda tannarx maydonlari null
    assert world.client.get(f"{R}/profit", headers=_bearer(manager)).status_code == 403
    assert world.client.get(f"{R}/export?report=profit", headers=_bearer(manager)).status_code == 403
    stock = _get(shop, "/stock-value", manager)
    assert stock["value_at_cost_minor"] is None and stock["value_at_price_minor"] == 4 * PRICE
    assert all(b["value_at_cost_minor"] is None for b in stock["branches"])
    assert stock["series"] and all(d["value_at_cost_minor"] is None for d in stock["series"])
    usage = _get(shop, "/ai-usage", manager)
    assert usage["cost_micros"] is None and usage["calls"] == 1 and usage["tokens_in"] == 10
    assert all(r["cost_micros"] is None for r in (*usage["by_day"], *usage["by_purpose"]))
    for report, column in (("stock_value", "value_at_cost_minor"), ("ai_usage", "cost_micros")):
        mine = world.client.get(f"{R}/export", params={"report": report}, headers=_bearer(manager))
        assert mine.status_code == 200 and column not in mine.text
        owner = world.client.get(f"{R}/export", params={"report": report}, headers=_bearer(shop.owner))
        assert column in owner.text
    assert str(COST) not in json.dumps(_get(shop, "/sales/top-products", manager))


def test_branch_scope_is_enforced(world: World) -> None:
    shop = Shop(world)
    _, _, token = world.invite(shop.owner, "MANAGER", branch_scope="SELECTED", branch_ids=[shop.branch])
    sku = _stocked(shop, COST)
    _sell(shop, sku)  # Chilonzor
    _quick_sale(shop, sku)
    _drain_now(world)
    assert _get(shop, "/sales/summary", token)["total_count"] == 2
    response = world.client.get(
        f"{R}/sales/summary", params={"branch_id": shop.branch2}, headers=_bearer(token)
    )
    assert response.status_code == 403


def test_reports_are_isolated_between_shops(world: World) -> None:
    mine, other = Shop(world), Shop(world)
    _sell(mine, _stocked(mine, COST))
    _drain_now(world)
    assert _get(mine, "/sales/summary")["total_count"] == 1
    assert _get(other, "/sales/summary")["total_count"] == 0
    assert _get(other, "/sales/top-products")["items"] == []

    async def visible(db: Any, _: Any) -> int:
        return int(await db.scalar(select(func.count()).select_from(OrderFact)))

    assert _in_db(world, other.id, visible) == 0  # RLS: boshqa shop qatorlari ko'rinmaydi
    assert (
        _admin_sql(world, "SELECT count(*) AS n FROM reporting.order_facts WHERE shop_id = $1", mine.id)[0][
            "n"
        ]
        == 1
    )
    for table in ("order_facts", "stock_value_daily", "message_facts", "projection_checkpoints"):
        flags = _admin_sql(
            world,
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'reporting' AND c.relname = $1",
            table,
        )[0]
        assert (flags["relrowsecurity"], flags["relforcerowsecurity"]) == (True, True), table


# ------------------------------------------------------------------ CSV
def test_safe_cell_blocks_formula_injection() -> None:
    assert safe_cell('=HYPERLINK("http://x")') == '\'=HYPERLINK("http://x")'
    assert safe_cell("+1") == "'+1" and safe_cell("-1") == "'-1" and safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert safe_cell("\tcmd") == "'\tcmd" and safe_cell(" =1+1") == "' =1+1"
    assert safe_cell(-5) == "-5" and safe_cell(0.5) == "0.5" and safe_cell(None) == ""  # sonlar buzilmaydi
    assert safe_cell("Oddiy nom") == "Oddiy nom"
    assert to_csv(["a"], [["=1"], [-1]]).splitlines() == ["﻿a", "'=1", "-1"]


def test_csv_export_has_no_pii_and_is_injection_safe(world: World) -> None:
    shop = Shop(world)
    body = {
        "category_code": "GPU",
        "title": "=cmd|' /C calc'!A0",
        "skus": [{"sku_code": f"X-{uuid4().hex[:8]}", "price": {"amount_minor": PRICE, "currency": "UZS"}}],
    }
    product = _ok(world.client.post("/api/v1/shop/products", json=body, headers=_hdr(shop.owner)), 201)
    _ok(_post(world, shop.owner, f"/products/{product['id']}/publish"))
    sku = product["skus"][0]["id"]
    _receive_cost(shop, sku, 3, COST)
    _sell(shop, sku)
    _drain_now(world)

    response = world.client.get(f"{R}/export", params={"report": "top_products"}, headers=_bearer(shop.owner))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        "attachment" in response.headers["content-disposition"]
        and "top_products_" in response.headers["content-disposition"]
    )
    text = response.content.decode("utf-8")
    lines = text.lstrip("﻿").splitlines()
    assert lines[0] == "sku_id,title,category_code,qty,amount_minor"
    assert "'=cmd" in lines[1] and ",=cmd" not in lines[1]
    for report in (
        "sales_daily",
        "by_category",
        "profit",
        "stock_value",
        "operators",
        "ai_usage",
        "warranty",
    ):
        assert (
            world.client.get(
                f"{R}/export", params={"report": report}, headers=_bearer(shop.owner)
            ).status_code
            == 200
        )
    assert (
        world.client.get(f"{R}/export", params={"report": "nope"}, headers=_bearer(shop.owner)).status_code
        == 422
    )

    # xaridor ismi/telefoni hech bir hisobotda va jadvalda yo'q (19 §3, DEC-146)
    digits = PHONE.replace("+", "")
    dump = text + json.dumps(
        [_get(shop, p) for p in ("/sales/summary", "/profit", "/operators", "/warranty")]
    )
    assert digits not in dump and "Jasur" not in dump
    rows = _admin_sql(
        world, "SELECT row_to_json(f)::text AS j FROM reporting.order_facts f WHERE shop_id = $1", shop.id
    )
    assert rows and all(digits not in r["j"] and "Jasur" not in r["j"] for r in rows)


# ------------------------------------------------------------------ qayta qurish
def test_backfill_rebuilds_same_numbers(world: World) -> None:
    shop = Shop(world)
    sku = _stocked(shop, COST)
    _sell(shop, sku, 2)
    _quick_sale(shop, sku)
    _sell(shop, _stocked(shop, None))
    _drain_now(world)
    paths = ("/sales/summary", "/sales/daily", "/sales/by-category", "/profit")
    live = {p: _get(shop, p) for p in paths}
    assert live["/profit"]["quality_flags"] == ["PARTIAL_COST_DATA"]

    _admin_sql(world, "DELETE FROM reporting.order_line_facts WHERE shop_id = $1", shop.id)
    _admin_sql(world, "DELETE FROM reporting.order_facts WHERE shop_id = $1", shop.id)
    _admin_sql(world, "DELETE FROM reporting.quick_sale_facts WHERE shop_id = $1", shop.id)
    assert _get(shop, "/sales/summary")["total_count"] == 0

    async def rebuild(db: Any, services: Any) -> dict[str, int]:
        return await rebuild_shop(db, services.catalog, services.sources, shop.id, datetime.now(UTC))

    counts = _in_db(world, shop.id, rebuild)
    assert counts["orders"] >= 2 and counts["quick_sales"] == 1 and counts["stock"] >= 2
    again = _in_db(world, shop.id, rebuild)  # takror qayta qurish ham xavfsiz
    assert again == counts
    for path in paths:
        rebuilt = _get(shop, path)
        assert {k: v for k, v in rebuilt.items() if k != "data_as_of"} == {
            k: v for k, v in live[path].items() if k != "data_as_of"
        }, path
    checkpoint = _admin_sql(
        world,
        "SELECT count(*) AS n FROM reporting.projection_checkpoints "
        "WHERE shop_id = $1 AND rebuilt_at IS NOT NULL",
        shop.id,
    )
    assert checkpoint[0]["n"] == 6
