"""3-modul (savdo) — DB'siz qismlar: PII shifrlash, qator summasi, mavjudlik holati, "own" qoidasi."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domains.commerce.common import Policy, read_cursor
from app.domains.commerce.inventory.models.orm import StockBalance
from app.domains.commerce.inventory.services.stock_service import StockService
from app.domains.commerce.orders import access
from app.domains.commerce.orders.models.orm import Order, OrderLine
from app.domains.commerce.orders.services.order_service import discount_limit
from app.domains.commerce.orders.services.pricing import discount_status, effective_discount, line_total
from app.domains.commerce.orders.services.views import allowed_actions, mask_phone, review_of
from app.domains.commerce.permissions import COMMERCE_ROLE_GRANTS
from app.shared.contracts.commerce import stock_status
from app.shared.db import encryption
from app.shared.db.encryption import (
    EncryptedString,
    PiiConfigError,
    PiiDecryptError,
    PiiKeyring,
    decrypt,
    encrypt,
    parse_keys,
    search_hmac,
)
from app.shared.errors.base import InsufficientStockError, ValidationError
from app.shared.pagination import encode_cursor
from app.shared.types.actor import ActorContext

K1, K2, HMAC_KEY = b"1" * 32, b"2" * 32, b"h" * 32


@pytest.fixture(autouse=True)
def keyring() -> Iterator[None]:
    previous = encryption._keyring
    encryption.configure_pii(PiiKeyring({"k1": K1}, "k1", HMAC_KEY))
    yield
    encryption._keyring = previous


# ------------------------------------------------------------------ PII shifrlash (26 §4)


def test_encrypt_round_trip_is_randomized_and_versioned() -> None:
    first, second = encrypt("+998901234567"), encrypt("+998901234567")
    assert first != second  # har safar yangi nonce — bir xil raqam bir xil ko'rinmaydi
    assert first.startswith("v1.k1.") and "998901234567" not in first
    assert decrypt(first) == decrypt(second) == "+998901234567"


def test_tampered_ciphertext_is_rejected() -> None:
    token = encrypt("Toshkent, Chilonzor 9")
    prefix, payload = token.rsplit(".", 1)
    flipped = payload[:-2] + ("A" if payload[-2] != "A" else "B") + payload[-1]
    with pytest.raises(PiiDecryptError):
        decrypt(f"{prefix}.{flipped}")
    with pytest.raises(PiiDecryptError):
        decrypt(token.replace("v1.k1.", "v1.k9."))  # noma'lum kalit
    with pytest.raises(PiiDecryptError):
        decrypt("ochiq matn")


def test_rotation_reads_old_keys_and_writes_with_active() -> None:
    old = encrypt("+998901112233")
    encryption.configure_pii(PiiKeyring({"k1": K1, "k2": K2}, "k2", HMAC_KEY))
    assert decrypt(old) == "+998901112233"  # eski yozuv eski kalit bilan o'qiladi
    assert encrypt("x").startswith("v1.k2.")
    encryption.configure_pii(PiiKeyring({"k2": K2}, "k2", HMAC_KEY))
    with pytest.raises(PiiDecryptError):
        decrypt(old)  # eski kalit olib tashlansa — o'qib bo'lmaydi (rotatsiyada eskisi qoladi)


def test_search_hmac_is_stable_and_keyed() -> None:
    digest = search_hmac("+998901234567")
    assert digest == search_hmac("+998901234567") and "998901234567" not in digest
    encryption.configure_pii(PiiKeyring({"k1": K1}, "k1", b"z" * 32))
    assert search_hmac("+998901234567") != digest  # kalitsiz xeshni hisoblab bo'lmaydi


def test_encrypted_string_type_handles_null() -> None:
    column = EncryptedString()
    assert column.process_bind_param(None, None) is None  # type: ignore[arg-type]
    stored = column.process_bind_param("+998901234567", None)  # type: ignore[arg-type]
    assert stored is not None and column.process_result_value(stored, None) == "+998901234567"  # type: ignore[arg-type]


def test_keyring_validation() -> None:
    assert parse_keys(f"a:{base64.b64encode(K1).decode()}, b:{base64.b64encode(K2).decode()}") == {
        "a": K1,
        "b": K2,
    }
    with pytest.raises(PiiConfigError):
        PiiKeyring({"k1": b"short"}, "k1", HMAC_KEY)
    with pytest.raises(PiiConfigError):
        PiiKeyring({"k1": K1}, "k2", HMAC_KEY)
    with pytest.raises(PiiConfigError):
        parse_keys("k1-without-separator")
    encryption._keyring = None
    with pytest.raises(PiiConfigError):
        encrypt("x")


# ------------------------------------------------------------------ narx va chegirma


@pytest.mark.parametrize(
    ("qty", "unit", "pct", "expected"),
    [
        (1, 480_000_000, Decimal(0), 480_000_000),
        (2, 145_000_000, Decimal(8), 266_800_000),
        (1, 256_000_000, Decimal("5.5"), 241_920_000),
        (3, 12_850, Decimal(0), 38_600),  # 385.50 so'm → 386 so'm (0.5 yuqoriga, DEC-133)
        (1, 100, Decimal(100), 0),
    ],
)
def test_line_total_rounds_to_whole_som(qty: int, unit: int, pct: Decimal, expected: int) -> None:
    assert line_total(qty, unit, pct) == expected


def test_pending_discount_does_not_change_total() -> None:
    line = OrderLine(discount_pct=Decimal(8), discount_requested_by=uuid4(), discount_approved_by=None)
    assert discount_status(line) == "PENDING" and effective_discount(line) == 0
    line.discount_approved_by = uuid4()
    assert discount_status(line) == "APPROVED" and effective_discount(line) == 8
    assert discount_status(OrderLine(discount_pct=Decimal(0))) == "NONE"


def _actor(role: str, *, branch_ids: frozenset | None = None) -> ActorContext:  # type: ignore[type-arg]
    return ActorContext(
        actor_type="STAFF",
        actor_id=uuid4(),
        shop_id=uuid4(),
        surface="shop",
        roles=frozenset({role}),
        permissions=COMMERCE_ROLE_GRANTS[role],
        branch_ids=branch_ids,
        membership_id=uuid4(),
    )


def test_discount_limits_follow_policy() -> None:  # DEC-110
    policy = Policy(Decimal(0), Decimal(5), 24, 2, "STATUS_ONLY")
    assert discount_limit(_actor("OWNER"), policy) == 100
    assert discount_limit(_actor("MANAGER"), policy) == 5
    assert discount_limit(_actor("SALES"), policy) == 0
    assert discount_limit(_actor("WAREHOUSE"), policy) == 0


# ------------------------------------------------------------------ mavjudlik va tuzatish


def test_stock_status_thresholds() -> None:  # 08 §4.5: threshold'dan kam — "kam qoldi"
    assert stock_status(0, 2) == "OUT_OF_STOCK"
    assert stock_status(1, 2) == "LOW_STOCK"
    assert stock_status(2, 2) == "IN_STOCK"
    assert stock_status(-1, 2) == "OUT_OF_STOCK"


def test_adjustment_cannot_go_below_reserved_or_quarantine() -> None:  # TC-CON-12
    balance = StockBalance(
        shop_id=uuid4(),
        branch_id=uuid4(),
        sku_id=uuid4(),
        on_hand=3,
        reserved=2,
        allocated=0,
        quarantine_qty=1,
    )
    StockService._check_adjustment(balance, "ADJUSTMENT", -1)
    with pytest.raises(InsufficientStockError) as below:
        StockService._check_adjustment(balance, "ADJUSTMENT", -2)
    assert below.value.details["lines"][0]["reserved"] == 2  # type: ignore[index]
    with pytest.raises(InsufficientStockError):
        StockService._check_adjustment(balance, "QUARANTINE_IN", 2)
    with pytest.raises(InsufficientStockError):
        StockService._check_adjustment(balance, "WRITE_OFF", 2)
    StockService._check_adjustment(balance, "RESTOCK", 1)
    StockService._check_adjustment(balance, "ADJUSTMENT", 5)


def test_cursor_rejects_foreign_or_broken_shapes() -> None:
    good = encode_cursor({"k": "ledger", "t": "2026-10-25T10:00:00+00:00", "id": str(uuid4())})
    assert read_cursor(good, "ledger", ("t", "id"))["t"].startswith("2026")
    for bad in (
        encode_cursor({"k": "receipt", "t": "x", "id": "y"}),
        encode_cursor({"k": "ledger", "t": 5, "id": "y"}),
        encode_cursor({"k": "ledger", "t": "a\x00", "id": "y"}),
        "%%%",
    ):
        with pytest.raises(ValidationError):
            read_cursor(bad, "ledger", ("t", "id"))


# ------------------------------------------------------------------ ko'rinish va "own" (10 §6.8)


def _order(status: str, assigned: object = None, branch: object = None) -> Order:
    return Order(
        id=uuid4(),
        shop_id=uuid4(),
        number=1,
        status=status,
        source="STAFF",
        assigned_membership_id=assigned,
        branch_id=branch,
        fulfillment_method="PICKUP",
        total_minor=0,
        version=1,
    )


def test_sales_sees_own_and_unassigned_only() -> None:
    sales, other = _actor("SALES"), uuid4()
    assert access.can_see(sales, _order("PENDING_CONFIRMATION", sales.membership_id))
    assert access.can_see(sales, _order("PENDING_CONFIRMATION"))
    assert not access.can_see(sales, _order("PENDING_CONFIRMATION", other))
    assert not access.is_own(sales, _order("PENDING_CONFIRMATION"))  # biriktirilmaganini tasdiqlay olmaydi
    assert access.can_edit(sales, _order("DRAFT"))
    assert not access.can_edit(sales, _order("CONFIRMED", sales.membership_id))  # DEC-134


def test_warehouse_sees_confirmed_orders_in_branch() -> None:
    branch = uuid4()
    warehouse = _actor("WAREHOUSE", branch_ids=frozenset({branch}))
    assert access.can_see(warehouse, _order("PROCESSING", branch=branch))
    assert not access.can_see(warehouse, _order("PROCESSING", branch=uuid4()))
    assert not access.can_see(warehouse, _order("DRAFT", branch=branch))
    assert not access.can_edit(warehouse, _order("DRAFT"))


POLICY = Policy(Decimal(0), Decimal(5), 24, 2, "STATUS_ONLY")


def test_allowed_actions_reflect_role_and_state() -> None:
    owner, sales = _actor("OWNER"), _actor("SALES")
    pending = _order("PENDING_CONFIRMATION", sales.membership_id)
    assert {"CONFIRM", "CANCEL", "ASSIGN", "EDIT"} <= set(allowed_actions(owner, pending, [], None, POLICY))
    sales_actions = set(allowed_actions(sales, pending, [], None, POLICY))
    assert "CONFIRM" in sales_actions and "CANCEL" not in sales_actions  # bekor qilish — menejer (DEC-108)
    discounted = [OrderLine(discount_pct=Decimal(8), discount_approved_by=None)]
    assert "CONFIRM" not in allowed_actions(owner, pending, discounted, None, POLICY)
    assert "APPROVE_DISCOUNT" in allowed_actions(owner, pending, discounted, None, POLICY)


def test_approve_discount_offered_only_within_own_limit() -> None:
    """QA F8: menejer limiti 5% — 8% lik chegirmani tasdiqlay olmaydi, tugma ham ko'rsatilmaydi."""
    manager = _actor("MANAGER")
    pending = _order("PENDING_CONFIRMATION", manager.membership_id)
    over = [OrderLine(discount_pct=Decimal(8), discount_approved_by=None)]
    within = [OrderLine(discount_pct=Decimal(4), discount_approved_by=None)]
    assert "APPROVE_DISCOUNT" not in allowed_actions(manager, pending, over, None, POLICY)
    assert "APPROVE_DISCOUNT" in allowed_actions(manager, pending, within, None, POLICY)


def test_review_includes_exception_orders() -> None:
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    stuck = _order("EXCEPTION")  # muammoli buyurtma ham mahsulotni ushlab turadi (QA kuzatuvi)
    assert review_of(stuck, now - timedelta(minutes=1), POLICY, now).reason == "RESERVATION_REVIEW"  # type: ignore[union-attr]


def test_review_flags() -> None:
    policy = Policy(Decimal(0), Decimal(5), 24, 2, "STATUS_ONLY")
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    order = _order("PENDING_CONFIRMATION")
    order.submitted_at = now - timedelta(hours=25)
    assert review_of(order, None, policy, now).reason == "UNCONFIRMED"  # type: ignore[union-attr]
    order.submitted_at = now - timedelta(hours=2)
    assert review_of(order, None, policy, now) is None
    held = _order("PROCESSING")
    assert review_of(held, now - timedelta(minutes=1), policy, now).reason == "RESERVATION_REVIEW"  # type: ignore[union-attr]
    assert review_of(held, now + timedelta(hours=1), policy, now) is None


def test_mask_phone() -> None:
    assert mask_phone("+998901234567") == "+998 90 *** ** 67"
    assert mask_phone(None) is None
    assert mask_phone("+1555") == "***"


def test_commerce_grants_follow_matrix() -> None:  # 10 §6.3
    assert "commerce.order.cancel" not in COMMERCE_ROLE_GRANTS["SALES"]
    assert "commerce.discount.request" in COMMERCE_ROLE_GRANTS["SALES"]
    assert "commerce.discount.apply" not in COMMERCE_ROLE_GRANTS["SALES"]
    assert "commerce.stock.adjust_approve" not in COMMERCE_ROLE_GRANTS["WAREHOUSE"]
    assert "commerce.order.create_draft" not in COMMERCE_ROLE_GRANTS["WAREHOUSE"]
    assert "commerce.order.process" in COMMERCE_ROLE_GRANTS["WAREHOUSE"]
    assert COMMERCE_ROLE_GRANTS["OWNER"] >= COMMERCE_ROLE_GRANTS["MANAGER"]
