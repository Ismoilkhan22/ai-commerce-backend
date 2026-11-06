"""Buyurtma API kontrakti (11 §9.4, §9.11; db/commerce.md §7–§11; FSM-08, FSM-07, DEC-134).

Pul — butun son, tiyinda (`*_minor`), xaridorga doim so'mda. Kasr son (chegirma foizi, kurs) — matn.
Javobda `allowed_actions` — shu xodim hozir qaysi tugmalarni bosa oladi (UI uchun qulaylik; haqiqiy
tekshiruv baribir server'da).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.commerce.schemas import MemberRef
from app.shared.text import CleanText, Text

OrderStatus = Literal[
    "DRAFT", "PENDING_CONFIRMATION", "CONFIRMED", "PROCESSING", "COMPLETED", "CANCELLED", "EXCEPTION"
]
OrderSource = Literal["AI", "STOREFRONT", "STAFF"]
FulfillmentMethod = Literal["PICKUP", "DELIVERY"]
CustomerLocale = Literal["uz", "ru", "en"]
PaidMarkMethod = Literal["CASH", "CARD", "TRANSFER", "OTHER"]
NoteKind = Literal["NOTE", "CALL_RESULT"]
ReservationStatus = Literal["ACTIVE", "ALLOCATED", "CONSUMED", "RELEASED", "EXPIRED"]
DiscountStatus = Literal["NONE", "PENDING", "APPROVED"]
ReviewReason = Literal["UNCONFIRMED", "RESERVATION_REVIEW"]
OrderSort = Literal["-created_at", "-updated_at"]
OrderAction = Literal[
    "EDIT",
    "SUBMIT",
    "CONFIRM",
    "REFRESH_PRICES",
    "START_PROCESSING",
    "MARK_READY",
    "COMPLETE",
    "CANCEL",
    "RAISE_EXCEPTION",
    "RESOLVE_EXCEPTION",
    "REVIEW_DECISION",
    "PAID_MARK",
    "NOTE",
    "TAKE",
    "ASSIGN",
    "DISCOUNT",
    "APPROVE_DISCOUNT",
]

MAX_LINES = 50
MAX_LINE_QTY = 999


# ------------------------------------------------------------------ kiritish


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    qty: int = Field(ge=1, le=MAX_LINE_QTY)


class OrderCreate(BaseModel):
    """Xodim yaratgan qoralama (chat yoki telefon orqali kelgan xaridor). Mahsulot band qilinmaydi."""

    model_config = ConfigDict(extra="forbid")

    customer_name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=32, description="+998 90 123 45 67")
    customer_locale: CustomerLocale = "uz"
    customer_comment: CleanText | None = Field(default=None, max_length=1000)
    fulfillment_method: FulfillmentMethod = "PICKUP"
    delivery_address: Text | None = Field(default=None, max_length=500)
    branch_id: UUID | None = None  # tasdiqlashdan oldin majburiy; bir buyurtma — bir filial (DEC-134)
    lines: list[OrderLineIn] = Field(default_factory=list, max_length=MAX_LINES)


class OrderUpdate(BaseModel):
    """Faqat qoralama va tasdiq kutilayotgan holatda. Yuborilmagan maydon o'zgarmaydi."""

    model_config = ConfigDict(extra="forbid")

    customer_name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=32)
    customer_locale: CustomerLocale | None = None
    customer_comment: CleanText | None = Field(default=None, max_length=1000)
    fulfillment_method: FulfillmentMethod | None = None
    delivery_address: Text | None = Field(default=None, max_length=500)
    branch_id: UUID | None = None


class LineQtyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int = Field(ge=1, le=MAX_LINE_QTY)


class DiscountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 0 — chegirmani olib tashlash. Limit — shop_policies (DEC-110)
    discount_pct: Decimal = Field(ge=0, le=100, decimal_places=2)


class DiscountDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Text | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Text = Field(min_length=3, max_length=500)


class OptionalReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Text | None = Field(default=None, min_length=3, max_length=500)


class ResolveExceptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["PROCESSING", "CANCELLED"]
    reason: Text | None = Field(default=None, min_length=3, max_length=500)  # bekor qilishda majburiy


class ReviewDecisionIn(BaseModel):
    """72 soatlik "bekor qilinsinmi?" vazifasi (DEC-104, DEC-134): kutamiz yoki bekor."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["WAIT", "CANCEL"]
    reason: Text | None = Field(default=None, min_length=3, max_length=500)  # bekor qilishda majburiy


class RefreshPricesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Xaridor yangi narxga rozi bo'lgani — buyurtmaga "qo'ng'iroq natijasi" izohi bo'lib yoziladi
    note: Text | None = Field(default=None, min_length=1, max_length=2000)


class PaidMarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: PaidMarkMethod


class OrderNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NoteKind = "NOTE"
    body: CleanText = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID | None  # None — biriktirishni olib tashlash (navbatga qaytadi)


# ------------------------------------------------------------------ javob


class ReservationOut(BaseModel):
    id: UUID
    status: ReservationStatus
    qty: int
    review_at: datetime
    allocated_at: datetime | None
    closed_at: datetime | None


class OrderLineOut(BaseModel):
    id: UUID
    position: int
    sku_id: UUID
    product_id: UUID | None
    title: str
    sku_code: str
    qty: int
    price_version_id: UUID
    unit_price_minor: int  # asl valyutada (so'm yoki dollar)
    currency: Literal["UZS", "USD"]
    exchange_rate_snapshot: Decimal | None
    unit_price_uzs_minor: int  # xaridor ko'radigan narx, so'mda
    discount_pct: Decimal
    discount_status: DiscountStatus
    discount_requested_by: MemberRef | None
    discount_approved_by: MemberRef | None
    discount_approved_at: datetime | None
    line_total_minor: int  # so'mda, faqat tasdiqlangan chegirma bilan
    warranty_months: int | None
    reservation: ReservationOut | None
    # Tanlangan filialda hozir yetadimi (qoralama va tasdiq kutilayotganda, filial tanlangan bo'lsa);
    # aks holda null. Saytdan kelgan so'rovda yo'q mahsulot — operator muqobil taklif qiladi (DEC-135)
    available_in_branch: bool | None = None
    available_qty: int | None = None  # filialdagi sotuvga mavjud (qoldiq − band − ajratilgan)
    version: int


class OrderNoteOut(BaseModel):
    id: UUID
    kind: NoteKind
    body: str
    author: MemberRef | None
    created_at: datetime


class OrderHistoryItem(BaseModel):
    """Holat tarixi (`platform.transition_log`): kim, qachon, qaysi o'tish, sabab. Xaridor ma'lumotisiz."""

    at: datetime
    command: str
    from_status: str
    to_status: str
    actor_type: str  # STAFF | CUSTOMER | AI_AGENT | SYSTEM
    actor_name: str | None
    reason: str | None


class OrderHistory(BaseModel):
    items: list[OrderHistoryItem]


class PaidMarkOut(BaseModel):
    at: datetime
    by: MemberRef | None
    method: PaidMarkMethod


class OrderReview(BaseModel):
    reason: ReviewReason
    due_at: datetime


class OrderOut(BaseModel):
    id: UUID
    number: int
    status: OrderStatus
    source: OrderSource
    fulfillment_method: FulfillmentMethod
    branch_id: UUID | None
    branch_name: str | None
    assigned: MemberRef | None
    customer_name: str | None
    customer_phone: str | None
    customer_locale: CustomerLocale
    customer_comment: str | None
    delivery_address: str | None
    consent_version: str | None
    pii_erased_at: datetime | None
    currency: Literal["UZS"]
    total_minor: int
    lines: list[OrderLineOut]
    notes: list[OrderNoteOut]
    paid_mark: PaidMarkOut | None  # "to'landi" — xodim belgisi, tizim tekshirmagan (DEC-100a)
    review: OrderReview | None
    submitted_at: datetime | None
    confirmed_at: datetime | None
    confirmed_by: MemberRef | None
    processing_at: datetime | None
    ready_at: datetime | None
    ready_by: MemberRef | None
    completed_at: datetime | None
    completed_by: MemberRef | None
    cancelled_at: datetime | None
    cancelled_by: MemberRef | None
    cancel_reason: str | None
    exception_reason: str | None
    created_by: MemberRef | None
    created_at: datetime
    updated_at: datetime
    version: int
    allowed_actions: list[OrderAction]


class OrderListItem(BaseModel):
    id: UUID
    number: int
    status: OrderStatus
    source: OrderSource
    fulfillment_method: FulfillmentMethod
    branch_id: UUID | None
    branch_name: str | None
    assigned: MemberRef | None
    customer_name: str | None
    customer_phone_masked: str | None  # "+998 90 *** ** 67" — to'liq raqam faqat kartochkada
    currency: Literal["UZS"]
    total_minor: int
    line_count: int
    paid_marked: bool
    ready: bool
    review_reason: ReviewReason | None
    submitted_at: datetime | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class OrderList(BaseModel):
    items: list[OrderListItem]
    next_cursor: str | None
    has_more: bool


class OrderCounts(BaseModel):
    by_status: dict[str, int]
    total: int
    mine: int  # menga biriktirilgan, tugallanmagan
    unassigned: int  # biriktirilmagan navbat, tugallanmagan
    review_unconfirmed: int
    review_reservations: int


class OrderReviewQueue(BaseModel):
    """ "Ko'rib chiqish kerak": tasdiqlanmagan va olib ketilmagan buyurtmalar (DEC-104, DEC-134).

    Hozir ro'yxat har so'rovda hisoblanadi; rejali ish va bildirishnoma — fon ishlari bilan (S0-06).
    """

    unconfirmed: list[OrderListItem]
    reservations: list[OrderListItem]
    unconfirmed_after_hours: int
    reservation_review_hours: int
