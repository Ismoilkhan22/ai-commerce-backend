"""7b-modul (kafolat murojaatlari): FSM-11, kafolat muddati, ombor ta'siri (daftar invariantlari), ruxsatlar,
RLS/IDOR, PII shifrlanishi va event'larda PII yo'qligi, xaridorga xabarlar — PostgreSQL'da, HTTP orqali.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from tests import images
from tests.integration.helpers import World, _bearer, _code, _idem
from tests.integration.test_commerce import PHONE, Shop, _admin_sql, _fields, _hdr, _ok, _post
from tests.integration.test_jobs_events import _drain_now, _job
from tests.integration.test_messaging import Inbox, _order_from_conversation

pytestmark = pytest.mark.integration

PROBLEM = "Videokarta o'yinda ekranni o'chiryapti, juda qiziydi"
CASES = "/support/cases"


class Warranty:
    """Shop + omborda dona bor SKU; sotilgan (COMPLETED) buyurtma va murojaatlar yordamchilari."""

    def __init__(self, world: World, shop: Shop | None = None, stock: int = 5) -> None:
        self.world = world
        self.shop = shop or Shop(world)
        self.sku = self.shop.sku()
        self.shop.receive(self.sku, stock)
        self.manager, self.manager_id = self.shop.staff("MANAGER")
        self.sales, self.sales_id = self.shop.staff("SALES")
        self.warehouse, self.warehouse_id = self.shop.staff("WAREHOUSE")

    def sold(self, qty: int = 1) -> tuple[dict[str, Any], str]:
        order = self.shop.step(
            self.shop.order({self.sku: qty}), "submit", "confirm", "start-processing", "complete"
        )
        return order, order["lines"][0]["id"]

    def body(self, order: dict[str, Any], line_id: str, **extra: Any) -> dict[str, Any]:
        return {
            "source": "ORDER_LINE",
            "order_id": order["id"],
            "order_line_id": line_id,
            "problem_description": PROBLEM,
            **extra,
        }

    def open(self, body: dict[str, Any], token: str | None = None) -> Any:
        return _post(self.world, token or self.sales, CASES, body)

    def opened(self, qty: int = 1, **extra: Any) -> dict[str, Any]:
        order, line = self.sold(qty)
        return _ok(self.open(self.body(order, line, qty=qty, **extra)), 201)

    def step(
        self, case: dict[str, Any], command: str, body: Any = None, token: str | None = None
    ) -> dict[str, Any]:
        return _ok(
            _post(
                self.world, token or self.shop.owner, f"{CASES}/{case['id']}/{command}", body, case["version"]
            )
        )

    def attempt(self, case: dict[str, Any], command: str, body: Any = None, token: str | None = None) -> Any:
        return _post(
            self.world, token or self.shop.owner, f"{CASES}/{case['id']}/{command}", body, case["version"]
        )

    def to_service(self, case: dict[str, Any], resolution: str, **extra: Any) -> dict[str, Any]:
        case = self.step(case, "start-review", {"item_received": True}, self.sales)
        case = self.step(case, "approve", {"resolution": resolution, **extra}, self.manager)
        return self.step(case, "start-service", token=self.warehouse)

    def get(self, case_id: str, token: str | None = None) -> dict[str, Any]:
        return _ok(
            self.world.client.get(f"/api/v1/shop{CASES}/{case_id}", headers=_bearer(token or self.shop.owner))
        )

    def balance(self, sku: str | None = None) -> dict[str, int]:
        b = self.shop.balance(sku or self.sku)
        return {k: b[k] for k in ("on_hand", "reserved", "allocated", "quarantine_qty", "available")}

    def case_ledger(self, case_id: str) -> list[tuple[str, int, int]]:
        rows = _admin_sql(
            self.world,
            "SELECT reason, delta_on_hand, delta_quarantine FROM commerce.stock_ledger "
            "WHERE ref_type = 'SUPPORT_CASE' AND ref_id = $1 ORDER BY created_at",
            UUID(case_id),
        )
        return [(r["reason"], r["delta_on_hand"], r["delta_quarantine"]) for r in rows]

    def release(self, case: dict[str, Any], kind: str, delta: int = 1) -> Any:
        body = {
            "branch_id": self.shop.branch,
            "sku_id": self.sku,
            "kind": kind,
            "delta": delta,
            "reason": "Karantindan chiqarish",
            "support_case_id": case["id"],
        }
        return _post(self.world, self.shop.owner, "/stock/adjustments", body)

    def assert_ledger_consistent(self) -> None:
        """Daftar yig'indisi qoldiq bilan teng (12 §6.1) va hech narsa manfiy emas."""
        rows = _admin_sql(
            self.world,
            "SELECT b.on_hand, b.quarantine_qty, COALESCE(SUM(l.delta_on_hand), 0) AS led_on_hand, "
            "COALESCE(SUM(l.delta_quarantine), 0) AS led_quarantine "
            "FROM commerce.stock_balances b LEFT JOIN commerce.stock_ledger l "
            "ON l.shop_id = b.shop_id AND l.branch_id = b.branch_id AND l.sku_id = b.sku_id "
            "WHERE b.shop_id = $1 GROUP BY b.on_hand, b.quarantine_qty, b.branch_id, b.sku_id",
            self.shop.id,
        )
        for r in rows:
            assert (r["on_hand"], r["quarantine_qty"]) == (r["led_on_hand"], r["led_quarantine"])
            assert r["on_hand"] >= 0 and r["quarantine_qty"] >= 0


# ------------------------------------------------------------------ ochish, kafolat muddati (BL-057)


def test_open_from_order_line_copies_warranty_snapshot_and_contact(world: World) -> None:
    w = Warranty(world)
    order, line = w.sold()
    case = _ok(w.open(w.body(order, line)), 201)
    assert (case["number"], case["status"], case["source"], case["type"]) == (
        1,
        "NEW",
        "ORDER_LINE",
        "WARRANTY",
    )
    assert case["within_warranty"] is True and case["warranty_months"] == 24 and case["warranty_until"]
    assert (case["qty"], case["branch_id"], case["customer_name"], case["customer_phone"]) == (
        1,
        w.shop.branch,
        "Jasur",
        PHONE,
    )
    assert case["opened_by"]["membership_id"] == w.sales_id and case["stock"]["quarantined"] == 0
    assert w.get(case["id"], w.warehouse)["id"] == case["id"]  # omborchi ko'radi
    listing = _ok(world.client.get(f"/api/v1/shop{CASES}?status=NEW&q=K-1", headers=_bearer(w.manager)))
    assert [i["id"] for i in listing["items"]] == [case["id"]]
    by_phone = _ok(world.client.get(f"/api/v1/shop{CASES}?q=%2B998901234567", headers=_bearer(w.manager)))
    assert [i["id"] for i in by_phone["items"]] == [case["id"]]


def test_warranty_window_uses_line_snapshot_not_catalog_and_manager_can_override(world: World) -> None:
    w = Warranty(world)
    order, line = w.sold()
    # Katalogda 24 oy, lekin sotuv paytidagi nusxa 1 oy va 3 oy oldin topshirilgan → muddat tugagan
    _admin_sql(world, "UPDATE commerce.order_lines SET warranty_months = 1 WHERE id = $1", UUID(line))
    long_ago = datetime.now(UTC) - timedelta(days=95)
    _admin_sql(
        world, "UPDATE commerce.orders SET completed_at = $2 WHERE id = $1", UUID(order["id"]), long_ago
    )
    expired = w.open(w.body(order, line))
    assert expired.status_code == 422 and _code(expired) == "WARRANTY_EXPIRED"
    assert expired.json()["error"]["details"]["warranty_months"] == 1
    # Operator muddat tugagan sotuvga ruxsat bera olmaydi; menejer — sabab bilan
    reason = {"warranty_override_reason": "Doimiy mijoz, istisno"}
    assert w.open(w.body(order, line, **reason), w.sales).status_code == 403
    case = _ok(w.open(w.body(order, line, **reason), w.manager), 201)
    assert case["within_warranty"] is False and case["warranty_override_reason"] == "Doimiy mijoz, istisno"
    # Kafolatdan tashqari qabul: izoh majburiy (support.md §2)
    case = w.step(case, "start-review", None, w.sales)
    missing = w.attempt(case, "approve", {"resolution": "REPAIR"}, w.manager)
    assert missing.status_code == 422 and _fields(missing) == {"decision_note": "required"}
    approved = w.step(case, "approve", {"resolution": "REPAIR", "decision_note": "Doimiy mijoz"}, w.manager)
    assert approved["status"] == "APPROVED" and approved["decision_note"] == "Doimiy mijoz"


def test_return_type_is_not_blocked_by_expired_window_and_external_needs_manager_note(world: World) -> None:
    w = Warranty(world)
    old = (datetime.now(UTC) - timedelta(days=900)).isoformat()
    external = {
        "source": "EXTERNAL",
        "external_sale_ref": "CHEK-77",
        "branch_id": w.shop.branch,
        "sku_id": w.sku,
        "sold_at": old,
        "warranty_months": 12,
        "problem_description": PROBLEM,
        "customer_name": "Bekzod",
        "customer_phone": "90 111 22 33",
    }
    assert _code(w.open(external)) == "WARRANTY_EXPIRED"
    returned = _ok(w.open({**external, "type": "RETURN"}), 201)  # qaytarishga ruxsatni odam beradi (BL-058)
    assert returned["type"] == "RETURN" and returned["within_warranty"] is False
    fresh = {**external, "sold_at": (datetime.now(UTC) - timedelta(days=30)).isoformat()}
    case = _ok(w.open(fresh), 201)
    assert case["within_warranty"] is True and case["source"] == "EXTERNAL"
    assert case["customer_phone"] == "+998901112233"
    case = w.step(case, "start-review", None, w.sales)
    # Tashqi sotuvda kafolat ichida ham izoh majburiy: qarorni doim menejer qiladi
    assert _fields(w.attempt(case, "approve", {"resolution": "REPAIR"}, w.manager)) == {
        "decision_note": "required"
    }
    bad = w.open({**external, "external_sale_ref": None, "branch_id": None})
    assert bad.status_code == 422 and {"external_sale_ref", "branch_id"} <= set(_fields(bad))


def test_open_validates_sale_line_order_state_and_open_quantity(world: World) -> None:
    w = Warranty(world)
    draft = w.shop.order({w.sku: 1})  # COMPLETED emas
    assert _fields(w.open(w.body(draft, draft["lines"][0]["id"]))) == {"order_id": "order_not_completed"}
    order, line = w.sold(qty=2)
    foreign_line = w.open(w.body(order, "00000000-0000-4000-8000-000000000001"))
    assert foreign_line.status_code == 422 and _fields(foreign_line) == {"order_line_id": "invalid"}
    assert w.open({**w.body(order, line), "quick_sale_id": order["id"]}).status_code == 422
    first = _ok(w.open(w.body(order, line, qty=2)), 201)
    extra = w.open(w.body(order, line))
    assert extra.status_code == 422 and _fields(extra) == {"qty": "max_value"}  # ochiq murojaatlar yig'indisi
    rejected = w.step(
        w.step(first, "start-review", None, w.sales),
        "reject",
        {"reject_reason": "NO_DEFECT_FOUND"},
        w.manager,
    )
    assert rejected["status"] == "REJECTED"
    _ok(w.open(w.body(order, line)), 201)  # rad etilgach qty bo'shadi
    assert w.get(first["id"])["number"] == 1


def test_open_from_quick_sale_line(world: World) -> None:
    w = Warranty(world)
    sale = _ok(
        _post(
            world,
            w.shop.owner,
            "/quick-sales",
            {"branch_id": w.shop.branch, "lines": [{"sku_id": w.sku, "qty": 1}]},
        ),
        201,
    )
    body = {
        "source": "QUICK_SALE_LINE",
        "quick_sale_id": sale["id"],
        "quick_sale_line_id": sale["lines"][0]["id"],
        "problem_description": PROBLEM,
        "customer_name": "Do'kon xaridori",
        "customer_phone": PHONE,
    }
    case = _ok(w.open(body), 201)
    assert case["source"] == "QUICK_SALE_LINE" and case["warranty_months"] == 24 and case["within_warranty"]
    assert w.balance()["quarantine_qty"] == 0


# ------------------------------------------------------------------ FSM-11 (If-Match, taqiqlangan o'tishlar)


def test_fsm_repair_flow_has_no_stock_effects_and_full_timeline(world: World) -> None:
    w = Warranty(world)
    before = w.balance()
    case = w.opened()
    assert w.attempt(case, "start-service", None, w.warehouse).status_code == 409  # NEW → IN_SERVICE yo'q
    case = w.step(case, "start-review", None, w.sales)
    assert case["status"] == "IN_REVIEW" and case["item_received_at"] is None
    note = _ok(
        _post(world, w.warehouse, f"{CASES}/{case['id']}/notes", {"kind": "DIAGNOSIS", "body": "Podshipnik"}),
        201,
    )
    assert (
        note["notes"][0]["kind"] == "DIAGNOSIS"
        and note["notes"][0]["author"]["membership_id"] == w.warehouse_id
    )
    case = w.get(case["id"])
    case = w.step(case, "approve", {"resolution": "REPAIR"}, w.manager)
    assert (case["status"], case["resolution"], case["decided_by"]["membership_id"]) == (
        "APPROVED",
        "REPAIR",
        w.manager_id,
    )
    no_item = w.attempt(case, "start-service", None, w.warehouse)  # mahsulot hali kelmagan
    assert no_item.status_code == 422 and _fields(no_item) == {"item_received_at": "required"}
    case = w.step(case, "receive-item", None, w.warehouse)
    case = w.step(case, "start-service", None, w.warehouse)
    assert (case["status"], case["stock"]["quarantined"]) == ("IN_SERVICE", 0)
    case = w.step(case, "resolve", {"note": "Ta'mirlandi"}, w.warehouse)
    assert (case["status"], case["outcome"]) == ("RESOLVED", "REPAIRED")
    case = w.step(case, "close", None, w.sales)
    assert case["status"] == "CLOSED" and case["closed_by"]["membership_id"] == w.sales_id
    assert w.attempt(case, "close").status_code == 409  # yakuniy holat
    # Ta'mir omborga tegmaydi: bitta ham daftar yozuvi yo'q, qoldiq o'zgarmagan (sotuvdan tashqari)
    assert w.case_ledger(case["id"]) == []
    after = w.balance()
    assert after["quarantine_qty"] == 0 and after["on_hand"] == before["on_hand"] - 1
    commands = [t["command"] for t in case["timeline"] if t["kind"] == "TRANSITION"]
    assert commands == ["START_REVIEW", "APPROVE", "START_SERVICE", "RESOLVE", "CLOSE"]
    assert [t["kind"] for t in case["timeline"]].count("NOTE") == 1
    w.assert_ledger_consistent()


def test_if_match_idempotency_and_forbidden_transitions(world: World) -> None:
    w = Warranty(world)
    case = w.opened()
    no_header = world.client.post(
        f"/api/v1/shop{CASES}/{case['id']}/start-review", json={}, headers=_bearer(w.sales, **_idem())
    )
    assert no_header.status_code == 400
    stale = _post(world, w.sales, f"{CASES}/{case['id']}/start-review", {}, case["version"] + 5)
    assert stale.status_code == 409 and _code(stale) == "VERSION_CONFLICT"
    headers = _hdr(w.sales, case["version"])
    first = world.client.post(f"/api/v1/shop{CASES}/{case['id']}/start-review", json={}, headers=headers)
    again = world.client.post(f"/api/v1/shop{CASES}/{case['id']}/start-review", json={}, headers=headers)
    assert first.status_code == again.status_code == 200 and again.json()["id"] == case["id"]
    assert first.headers["ETag"]
    case = _ok(first)
    assert w.attempt(case, "start-review", None, w.sales).status_code == 409  # IN_REVIEW → IN_REVIEW yo'q
    needs_reason = w.attempt(case, "reject", {}, w.manager)
    assert needs_reason.status_code == 422
    rejected = w.step(case, "reject", {"reject_reason": "USER_DAMAGE", "note": "Suv tekkan"}, w.manager)
    assert (rejected["status"], rejected["reject_reason"]) == ("REJECTED", "USER_DAMAGE")
    for command in ("approve", "start-service", "resolve"):
        body = {"resolution": "REPAIR"} if command == "approve" else None
        assert w.attempt(rejected, command, body, w.manager).status_code == 409, command  # REJECTED yakuniy
    transitions = _admin_sql(
        world,
        "SELECT command FROM platform.transition_log WHERE entity_id = $1 ORDER BY occurred_at",
        UUID(case["id"]),
    )
    assert [r["command"] for r in transitions] == ["START_REVIEW", "REJECT"]


# ------------------------------------------------------------------ ombor ta'siri (DEC-145, DEC-126)


def test_replace_quarantines_returned_unit_then_issues_new_unit_with_consistent_ledger(world: World) -> None:
    w = Warranty(world)
    case = w.opened()
    sold = w.balance()  # sotuvdan keyin: 4 dona
    assert sold["on_hand"] == 4
    case = w.to_service(case, "REPLACE")
    assert case["replacement_sku_id"] == w.sku  # standart — o'sha SKU
    # Qaytgan dona karantinga: on_hand o'zgarmaydi (sotilgan dona omborga qaytmaydi)
    assert w.balance() == {**sold, "quarantine_qty": 1}
    assert w.case_ledger(case["id"]) == [("RETURN_QUARANTINE", 0, 1)]
    case = w.step(case, "resolve", {"note": "Yangi dona berildi"}, w.warehouse)
    assert (case["status"], case["outcome"]) == ("RESOLVED", "REPLACED")
    assert w.balance() == {**sold, "on_hand": 3, "quarantine_qty": 1, "available": 3}
    assert w.case_ledger(case["id"]) == [("RETURN_QUARANTINE", 0, 1), ("WARRANTY_REPLACEMENT", -1, 0)]
    stock = w.get(case["id"])["stock"]
    assert stock == {"quarantined": 1, "restocked": 0, "written_off": 0, "replacement_issued": 1}
    # Karantindan chiqarish — oddiy RESTOCK (support_case_id bilan); karantindagidan ko'p chiqarib bo'lmaydi
    restock = _ok(w.release(case, "RESTOCK"), 201)
    assert restock["status"] == "APPROVED" and restock["support_case_id"] == case["id"]
    assert w.balance() == {**sold, "on_hand": 4, "quarantine_qty": 0, "available": 4}
    over = w.release(case, "RESTOCK")
    assert over.status_code == 409 and _code(over) == "INSUFFICIENT_AVAILABLE_STOCK"
    assert w.get(case["id"])["stock"]["restocked"] == 1
    w.assert_ledger_consistent()
    reasons = [e["reason"] for e in w.shop.ledger(w.sku)]
    assert reasons.count("WARRANTY_REPLACEMENT") == 1 and reasons.count("RETURN_QUARANTINE") == 1


def test_replace_with_another_sku_and_resolution_change_in_service(world: World) -> None:
    w = Warranty(world)
    other = w.shop.sku()
    w.shop.receive(other, 2)
    case = w.opened()
    case = w.to_service(case, "REPAIR")
    assert w.balance()["quarantine_qty"] == 0  # ta'mir karantinga tushmaydi
    # "Ta'mirlab bo'lmadi, almashtiramiz": faqat menejer/ega, sabab bilan; endi dona karantinga
    assert (
        w.attempt(
            case, "resolution", {"resolution": "REPLACE", "reason": "Ta'mirlab bo'lmadi"}, w.warehouse
        ).status_code
        == 403
    )
    changed = w.step(
        case,
        "resolution",
        {"resolution": "REPLACE", "replacement_sku_id": other, "reason": "Ta'mirlab bo'lmadi"},
        w.manager,
    )
    assert (changed["resolution"], changed["replacement_sku_id"]) == ("REPLACE", other)
    assert w.balance()["quarantine_qty"] == 1
    assert w.case_ledger(case["id"])[0] == ("RETURN_QUARANTINE", 0, 1)
    # Karantindagi donani ta'mirga qaytarib bo'lmaydi
    back = w.attempt(changed, "resolution", {"resolution": "REPAIR", "reason": "Fikr o'zgardi"}, w.manager)
    assert back.status_code == 422 and _fields(back) == {"resolution": "invalid_change"}
    done = w.step(changed, "resolve", None, w.warehouse)
    assert done["outcome"] == "REPLACED"
    assert w.balance(other)["on_hand"] == 1  # yangi dona boshqa SKU'dan
    assert w.balance()["on_hand"] == 4 and w.balance()["quarantine_qty"] == 1  # yangi dona boshqa SKU'dan
    assert w.case_ledger(case["id"]) == [("RETURN_QUARANTINE", 0, 1), ("WARRANTY_REPLACEMENT", -1, 0)]
    w.assert_ledger_consistent()


def test_refund_amount_is_capped_by_sold_line_total(world: World) -> None:
    w = Warranty(world)
    price = 480_000_000  # Shop.sku() narxi, tiyinda
    case = w.to_service(w.opened(), "REFUND")
    over = w.attempt(case, "resolve", {"refund_amount_minor": price + 1}, w.warehouse)
    assert over.status_code == 422 and _fields(over) == {"refund_amount_minor": "max_value"}
    exact = w.attempt(case, "resolve", {"refund_amount_minor": price}, w.warehouse)
    assert exact.status_code == 200 and w.get(case["id"])["refund_amount_minor"] == price


def test_refund_for_unknown_sale_needs_manager_and_future_sold_at_is_rejected(world: World) -> None:
    w = Warranty(world)
    external = {
        "source": "EXTERNAL",
        "external_sale_ref": "CHEK-88",
        "branch_id": w.shop.branch,
        "sku_id": w.sku,
        "warranty_months": 12,
        "problem_description": PROBLEM,
    }
    future = w.open({**external, "sold_at": (datetime.now(UTC) + timedelta(days=3)).isoformat()})
    assert future.status_code == 422 and _fields(future) == {"sold_at": "in_future"}
    sold_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    case = w.to_service(
        _ok(w.open({**external, "sold_at": sold_at}), 201), "REFUND", decision_note="Doimiy mijoz"
    )
    denied = w.attempt(case, "resolve", {"refund_amount_minor": 100_000}, w.warehouse)
    assert denied.status_code == 403
    allowed = w.attempt(case, "resolve", {"refund_amount_minor": 100_000}, w.manager)
    assert allowed.status_code == 200 and w.get(case["id"])["refund_amount_minor"] == 100_000


def test_refund_quarantines_unit_without_stock_out_and_write_off_releases_it(world: World) -> None:
    w = Warranty(world)
    case = w.opened()
    sold = w.balance()
    case = w.to_service(case, "REFUND")
    assert w.balance() == {**sold, "quarantine_qty": 1}
    wrong = w.attempt(case, "resolve", {"refund_amount_minor": 1}, w.warehouse)
    assert wrong.status_code == 200  # REFUND da summa — faqat ma'lumot
    case = w.get(case["id"])
    assert (case["status"], case["outcome"], case["refund_amount_minor"]) == ("RESOLVED", "RETURNED", 1)
    assert w.case_ledger(case["id"]) == [("RETURN_QUARANTINE", 0, 1)]  # yangi dona chiqmaydi
    assert w.balance()["on_hand"] == sold["on_hand"]
    other = w.to_service(w.opened(), "REFUND")  # boshqa murojaatning donasi ham karantinda (jami 2)
    assert w.balance()["quarantine_qty"] == 2
    writeoff = _ok(w.release(case, "WRITE_OFF"), 201)
    assert writeoff["kind"] == "WRITE_OFF" and writeoff["support_case_id"] == case["id"]
    assert w.balance()["quarantine_qty"] == 1
    again = w.release(case, "WRITE_OFF")  # shu murojaatning donasi ikki marta chiqarilmaydi
    assert again.status_code == 409 and _code(again) == "INSUFFICIENT_AVAILABLE_STOCK"
    assert w.get(other["id"])["stock"]["quarantined"] == 1
    assert w.get(case["id"])["stock"] == {
        "quarantined": 1,
        "restocked": 0,
        "written_off": 1,
        "replacement_issued": 0,
    }
    # support_case_id faqat shu murojaat karantinga yozgan SKU/filialda; boshqa murojaat uchun ham yo'q
    bogus = _post(
        world,
        w.shop.owner,
        "/stock/adjustments",
        {
            "branch_id": w.shop.branch,
            "sku_id": w.sku,
            "kind": "RESTOCK",
            "delta": 1,
            "reason": "Soxta murojaat",
            "support_case_id": w.sales_id,
        },
    )
    assert bogus.status_code == 422 and _fields(bogus) == {"support_case_id": "invalid"}
    plain = _post(
        world,
        w.shop.owner,
        "/stock/adjustments",
        {
            "branch_id": w.shop.branch,
            "sku_id": w.sku,
            "kind": "ADJUSTMENT",
            "delta": 1,
            "reason": "Oddiy",
            "support_case_id": case["id"],
        },
    )
    assert plain.status_code == 422
    w.assert_ledger_consistent()


def test_replacement_needs_available_stock_and_rolls_back_whole_resolve(world: World) -> None:
    w = Warranty(world, stock=1)
    case = w.opened()
    assert w.balance()["on_hand"] == 0  # oxirgi dona sotildi
    case = w.to_service(case, "REPLACE")
    assert w.balance()["quarantine_qty"] == 1 and w.balance()["available"] == 0
    failed = w.attempt(case, "resolve", None, w.warehouse)
    assert failed.status_code == 409 and _code(failed) == "INSUFFICIENT_AVAILABLE_STOCK"
    same = w.get(case["id"])
    assert (same["status"], same["version"], same["outcome"]) == ("IN_SERVICE", case["version"], None)
    assert w.case_ledger(case["id"]) == [("RETURN_QUARANTINE", 0, 1)]  # almashtirish yozilmadi
    # Karantindagi dona sotuvga qaytarilgach, almashtirish chiqadi (dona bor)
    _ok(w.release(case, "RESTOCK"), 201)
    done = w.step(case, "resolve", None, w.warehouse)
    assert done["outcome"] == "REPLACED" and w.balance()["on_hand"] == 0
    w.assert_ledger_consistent()


def test_stock_effects_are_idempotent_per_case(world: World) -> None:
    w = Warranty(world)
    case = w.to_service(w.opened(), "REPLACE")
    headers = _hdr(w.warehouse, case["version"])
    url = f"/api/v1/shop{CASES}/{case['id']}/resolve"
    first = world.client.post(url, json={}, headers=headers)
    again = world.client.post(url, json={}, headers=headers)
    assert first.status_code == 200 and again.status_code == 200
    assert [e[0] for e in w.case_ledger(case["id"])].count("WARRANTY_REPLACEMENT") == 1
    assert [e[0] for e in w.case_ledger(case["id"])].count("RETURN_QUARANTINE") == 1


def test_resolved_case_closes_after_seven_days_by_system(world: World) -> None:
    w = Warranty(world)
    case = w.step(w.to_service(w.opened(), "REPAIR"), "resolve", None, w.warehouse)
    assert _job(world, "support_case_auto_close").affected == 0  # hali 7 kun o'tmagan
    _admin_sql(
        world,
        "UPDATE support.cases SET resolved_at = now() - interval '8 days' WHERE id = $1",
        UUID(case["id"]),
    )
    assert _job(world, "support_case_auto_close").affected >= 1
    closed = w.get(case["id"])
    assert closed["status"] == "CLOSED" and closed["closed_by"] is None and closed["closed_at"]
    system = _admin_sql(
        world,
        "SELECT actor_type, reason FROM platform.transition_log WHERE entity_id = $1 AND command = 'CLOSE'",
        UUID(case["id"]),
    )
    assert [(r["actor_type"], r["reason"]) for r in system] == [("SYSTEM", "AUTO_CLOSE_7_DAYS")]


# ------------------------------------------------------------------ ruxsatlar (business/04)


def test_permissions_per_role(world: World) -> None:
    w = Warranty(world)
    order, line = w.sold()
    body = w.body(order, line)
    assert w.open(body, w.warehouse).status_code == 403  # omborchi ochmaydi, ko'radi
    case = _ok(w.open(body, w.sales), 201)
    assert w.get(case["id"], w.warehouse)["id"] == case["id"]
    assert world.client.get(f"/api/v1/shop{CASES}", headers=_bearer(w.warehouse)).status_code == 200
    case = w.step(case, "start-review", None, w.sales)
    # Qaror — faqat menejer/ega
    for token in (w.sales, w.warehouse):
        assert w.attempt(case, "approve", {"resolution": "REPAIR"}, token).status_code == 403
        assert w.attempt(case, "reject", {"reject_reason": "OTHER"}, token).status_code == 403
        assert (
            w.attempt(case, "resolution", {"resolution": "REFUND", "reason": "Sabab bor"}, token).status_code
            == 403
        )
        assert (
            _post(
                world, token, f"{CASES}/{case['id']}/assign", {"membership_id": None}, case["version"]
            ).status_code
            == 403
        )
    approved = w.step(case, "approve", {"resolution": "REPAIR"}, w.manager)
    # Xizmat/hal qilish — ega, menejer, omborchi; operator emas
    approved = w.step(approved, "receive-item", None, w.sales)
    assert w.attempt(approved, "start-service", None, w.sales).status_code == 403
    in_service = w.step(approved, "start-service", None, w.warehouse)
    assert w.attempt(in_service, "resolve", None, w.sales).status_code == 403
    resolved = w.step(in_service, "resolve", None, w.warehouse)
    assert w.attempt(resolved, "close", None, w.warehouse).status_code == 200
    unauthenticated = world.client.get(f"/api/v1/shop{CASES}")
    assert unauthenticated.status_code == 401
    owner_case = _ok(w.open(w.body(*w.sold()), w.shop.owner), 201)
    assert owner_case["number"] == 2


def test_manager_decision_creates_task_and_notification_and_resolving_closes_task(world: World) -> None:
    w = Warranty(world)
    case = w.opened()
    tasks = _ok(world.client.get("/api/v1/shop/tasks?status=OPEN", headers=_bearer(w.manager)))["items"]
    task = next(t for t in tasks if t["type"] == "SUPPORT_CASE_DECISION")
    assert task["subject_id"] == case["id"]
    notes = _ok(world.client.get("/api/v1/shop/notifications", headers=_bearer(w.manager)))
    assert any("K-1" in n["title"] for n in notes["items"])
    started = w.step(case, "start-review", None, w.sales)
    w.step(started, "approve", {"resolution": "REPAIR"}, w.manager)
    open_after = _ok(world.client.get("/api/v1/shop/tasks?status=OPEN", headers=_bearer(w.manager)))["items"]
    assert not [t for t in open_after if t["type"] == "SUPPORT_CASE_DECISION"]


# ------------------------------------------------------------------ RLS / IDOR (TC-ISO)


def test_other_shop_cannot_see_or_touch_cases_files_or_adjustment_links(world: World) -> None:
    a, b = Warranty(world), Warranty(world)
    case = a.opened()
    path = f"/api/v1/shop{CASES}/{case['id']}"
    assert world.client.get(path, headers=_bearer(b.shop.owner)).status_code == 404
    assert _ok(world.client.get(f"/api/v1/shop{CASES}", headers=_bearer(b.shop.owner)))["items"] == []
    for command, body in (("start-review", {}), ("receive-item", None), ("notify-ready", None)):
        res = _post(world, b.shop.owner, f"{CASES}/{case['id']}/{command}", body, case["version"])
        assert res.status_code == 404, command
    assert _post(world, b.shop.owner, f"{CASES}/{case['id']}/notes", {"body": "x"}).status_code == 404
    # B shopning sotuv qatoriga A buyurtmasidan murojaat ochib bo'lmaydi
    order_a, line_a = a.sold()
    cross = b.open(b.body(order_a, line_a), b.sales)
    assert cross.status_code == 422 and _fields(cross) == {"order_line_id": "invalid"}
    # A shopning faylini B murojaatiga biriktirib bo'lmaydi (fayl ID'sini taxmin qilish)
    mine = b.opened()
    foreign_file = _ok(
        world.client.post(
            "/api/v1/shop/files?purpose=SUPPORT_EVIDENCE&filename=a.png",
            content=images.png(),
            headers=_bearer(a.sales, **_idem(), **{"Content-Type": "application/octet-stream"}),
        ),
        201,
    )
    res = _post(world, b.sales, f"{CASES}/{mine['id']}/attachments", {"file_id": foreign_file["id"]})
    assert res.status_code == 422 and _fields(res) == {"file_id": "invalid"}
    # Ombor tuzatishida boshqa shop murojaati ID'si karantin tarixi yo'qligi uchun rad etiladi
    res = b.release(case, "RESTOCK")
    assert res.status_code == 422 and _fields(res) == {"support_case_id": "invalid"}


def test_database_rls_is_forced_and_isolates_shops(world: World) -> None:
    a = Warranty(world)
    a.opened()
    flags = _admin_sql(
        world,
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'support' "
        "AND c.relname IN ('cases', 'case_notes', 'case_attachments')",
    )
    assert len(flags) == 3 and all(r["relrowsecurity"] and r["relforcerowsecurity"] for r in flags)
    from tests.integration.helpers import _sql

    assert (
        _sql(world.urls.runtime, "SELECT count(*) AS n FROM support.cases")[0]["n"] == 0
    )  # kontekstsiz — hech narsa
    privileges = _sql(
        world.urls.runtime,
        "SELECT has_table_privilege('app_runtime', 'support.cases', 'DELETE') AS d",
    )
    assert privileges[0]["d"] is False  # murojaat o'chirilmaydi


# ------------------------------------------------------------------ PII (26 §4)


def test_customer_phone_is_encrypted_and_pii_stays_out_of_events_audit_and_idempotency(world: World) -> None:
    w = Warranty(world)
    order, line = w.sold()
    case = _ok(
        w.open(w.body(order, line, customer_name="Jasur Karimov", customer_phone="+998 90 777 66 55")), 201
    )
    assert case["customer_phone"] == "+998907776655"
    [row] = _admin_sql(
        world,
        "SELECT contact_phone_enc, contact_phone_hmac, customer_name FROM support.cases WHERE id = $1",
        UUID(case["id"]),
    )
    assert row["contact_phone_enc"].startswith("v1.") and "907776655" not in row["contact_phone_enc"]
    assert row["contact_phone_hmac"] and "907776655" not in row["contact_phone_hmac"]
    case = w.step(case, "start-review", None, w.sales)
    _ok(
        _post(
            world,
            w.sales,
            f"{CASES}/{case['id']}/notes",
            {"kind": "CUSTOMER_CONTACT", "body": "Qo'ng'iroq +998907776655"},
        ),
        201,
    )
    w.step(w.get(case["id"]), "approve", {"resolution": "REPAIR"}, w.manager)
    events = _admin_sql(
        world,
        "SELECT event_type, envelope::text AS e FROM support.outbox_events WHERE shop_id = $1",
        w.shop.id,
    )
    types = {r["event_type"] for r in events}
    assert {"support.case.opened", "support.case.status_changed", "support.case.updated"} <= types
    for secret in ("907776655", "Jasur", "Karimov", "ekranni", "o'chiryapti", "Qo'ng'iroq"):
        assert all(secret not in r["e"] for r in events), secret
    for r in events:
        payload = json.loads(r["e"])["payload"]
        assert payload["case_id"] == case["id"] and "number" in payload
    audit = _admin_sql(
        world,
        "SELECT coalesce(diff::text, '') || coalesce(reason, '') AS d "
        "FROM audit.audit_entries WHERE entity_id = $1",
        UUID(case["id"]),
    )
    assert audit and all(
        "907776655" not in r["d"] and "Jasur" not in r["d"] and "ekranni" not in r["d"] for r in audit
    )
    stored = _admin_sql(
        world, "SELECT response_body::text AS b FROM platform.idempotency_keys WHERE shop_id = $1", w.shop.id
    )
    assert all("907776655" not in r["b"] and "Jasur" not in r["b"] for r in stored)


def test_privacy_erasure_clears_finished_cases_only(world: World) -> None:
    import asyncio

    from app.domains.support.services.privacy import erase_customer_handler
    from app.shared.db.session import Database
    from app.shared.types.actor import ActorContext

    w = Warranty(world)
    rejected = w.step(
        w.step(w.opened(), "start-review", None, w.sales), "reject", {"reject_reason": "OTHER"}, w.manager
    )
    open_case = w.opened()

    async def go() -> Any:
        db = Database(world.settings.database_config())
        try:
            async with db.transaction(w.shop.id) as session:
                return await erase_customer_handler(session, ActorContext.system(w.shop.id), PHONE)
        finally:
            await db.dispose()

    summary = asyncio.run(go())
    assert (summary.erased, summary.skipped_active) == (1, 1)
    erased, kept = w.get(rejected["id"]), w.get(open_case["id"])
    assert erased["customer_name"] is None and erased["customer_phone"] is None and erased["number"] == 1
    assert kept["customer_phone"] == PHONE


# ------------------------------------------------------------------ rasmlar (private, SUPPORT_EVIDENCE)


def test_attachments_are_private_support_evidence_limited_to_ten(world: World) -> None:
    w = Warranty(world)
    case = w.opened()

    def upload(purpose: str, shade: int, token: str | None = None) -> dict[str, Any]:
        return _ok(
            world.client.post(
                f"/api/v1/shop/files?purpose={purpose}&filename=f.png",
                content=images.png(rgb=(shade, 1, 2)),
                headers=_bearer(token or w.sales, **_idem(), **{"Content-Type": "application/octet-stream"}),
            ),
            201,
        )

    first = upload("SUPPORT_EVIDENCE", 1)
    assert first["is_public"] is False and first["purpose"] == "SUPPORT_EVIDENCE"
    detail = _ok(
        _post(
            world, w.sales, f"{CASES}/{case['id']}/attachments", {"file_id": first["id"], "caption": "Yoriq"}
        ),
        201,
    )
    [attachment] = detail["attachments"]
    assert (
        attachment["caption"] == "Yoriq"
        and attachment["mime_type"] == "image/png"
        and "sig=" in attachment["url"]
    )
    dup = _post(world, w.sales, f"{CASES}/{case['id']}/attachments", {"file_id": first["id"]})
    assert dup.status_code == 422 and _fields(dup) == {"file_id": "duplicate"}
    wrong = upload("STOCK_EVIDENCE", 2, w.warehouse)  # boshqa turdagi fayl
    res = _post(world, w.sales, f"{CASES}/{case['id']}/attachments", {"file_id": wrong["id"]})
    assert res.status_code == 422 and _fields(res) == {"file_id": "invalid"}
    for shade in range(10, 19):
        _ok(
            _post(
                world,
                w.sales,
                f"{CASES}/{case['id']}/attachments",
                {"file_id": upload("SUPPORT_EVIDENCE", shade)["id"]},
            ),
            201,
        )
    eleventh = _post(
        world, w.sales, f"{CASES}/{case['id']}/attachments", {"file_id": upload("SUPPORT_EVIDENCE", 99)["id"]}
    )
    assert eleventh.status_code == 422 and _fields(eleventh) == {"file_id": "max_items"}
    # Yopiq fayl: imzosiz ochiq manzildan berilmaydi
    assert world.client.get(attachment["url"].split("?")[0].replace("http://testserver", "")).status_code in (
        401,
        403,
        404,
    )


# ------------------------------------------------------------------ xaridorga xabarlar (suhbat bo'lsa)


def test_customer_gets_four_templated_messages_only_when_case_has_conversation(world: World) -> None:
    inbox = Inbox(world)
    ivan = {"id": 5001, "is_bot": False, "first_name": "Иван", "language_code": "ru"}
    inbox.send({"text": "Здравствуйте", "from": ivan})
    conversation_id = inbox.conversations()[0]["id"]
    inbox.send({"contact": {"phone_number": "+998901110022", "user_id": 5001}, "from": ivan})
    ref = _order_from_conversation(world, inbox, conversation_id)
    w = Warranty(world, inbox.shop)
    order = inbox.shop.step(inbox.shop.get(ref["id"]), "submit", "confirm", "start-processing", "complete")
    line = order["lines"][0]["id"]
    notices = lambda: [m["body"] for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]  # noqa: E731
    _drain_now(world)  # buyurtma xabarlari (tasdiqlandi, tayyor, topshirildi) avval ketadi
    base = len(notices())
    # Rad etilgan murojaat: ochildi + rad etildi (sabab kodidan, erkin izoh ketmaydi)
    case = _ok(w.open(w.body(order, line, created_via="CONVERSATION")), 201)
    assert case["conversation_id"] == conversation_id
    _drain_now(world)
    case = w.step(case, "start-review", None, w.sales)
    case = w.step(
        case, "reject", {"reject_reason": "NO_DEFECT_FOUND", "note": "Ichki izoh: +998901110022"}, w.manager
    )
    _drain_now(world)
    sent = notices()[base:]
    assert len(sent) == 2
    assert sent[0].startswith("Ваше обращение K-1 принято.") and "Товар:" in sent[0]
    assert sent[1].startswith(
        "K-1: к сожалению, по гарантии принять не удалось. При проверке дефект не найден."
    )
    assert "Ichki izoh" not in sent[1] and "998901110022" not in sent[1]
    # Ikkinchi murojaat: ochildi, qabul qilindi, "tayyor" (xodim bosadi, ikki marta bossa ham bitta xabar)
    second = _ok(w.open(w.body(order, line)), 201)
    second = w.to_service(second, "REPAIR")
    _drain_now(world)
    ready = _ok(_post(world, w.warehouse, f"{CASES}/{second['id']}/notify-ready", None))
    _ok(_post(world, w.warehouse, f"{CASES}/{second['id']}/notify-ready", None))
    _drain_now(world)
    sent = notices()[base + 2 :]
    assert len(sent) == 3 and ready["id"] == second["id"]
    assert sent[1] == "K-2: ваше обращение одобрено — отремонтируем."
    assert sent[2].startswith("K-2: ваш товар готов. Адрес:")
    # Suhbatsiz murojaat — xabar yo'q; "tayyor" tugmasi 422
    plain = Warranty(world)
    lone = plain.to_service(plain.opened(), "REPAIR")
    _drain_now(world)
    res = _post(world, plain.warehouse, f"{CASES}/{lone['id']}/notify-ready", None)
    assert res.status_code == 422 and _fields(res) == {"conversation_id": "no_conversation"}
    unknown = plain.open(plain.body(*plain.sold(), conversation_id="00000000-0000-4000-8000-000000000009"))
    assert unknown.status_code == 422 and _fields(unknown) == {"conversation_id": "invalid"}
