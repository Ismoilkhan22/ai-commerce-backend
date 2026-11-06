"""Lead va PC taklifi API kontrakti (6a; db/commerce_quotes.md; FSM-05, FSM-06; DEC-142 taklif).

Pul — butun son, tiyinda (`*_minor`), xaridorga so'mda. Narx klientdan qabul qilinmaydi: qatorda faqat SKU,
soni va (xodim) chegirma foizi — narx katalogdan nusxa (BL-041).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.commerce.schemas import MemberRef
from app.shared.text import CleanText, Text

LeadStatus = Literal["NEW", "QUALIFIED", "QUOTED", "WON", "LOST"]
LostReason = Literal[
    "TOO_EXPENSIVE", "OUT_OF_STOCK", "NOT_COMPATIBLE", "NO_RESPONSE", "BOUGHT_ELSEWHERE", "OTHER"
]
QuoteStatus = Literal["DRAFT", "REVIEW", "APPROVED", "SENT", "ACCEPTED", "REJECTED", "EXPIRED", "CANCELLED"]
CompatDecision = Literal["PASS", "REVIEW_REQUIRED", "BLOCK"]
LineRole = Literal[
    "CPU",
    "MOTHERBOARD",
    "RAM",
    "GPU",
    "STORAGE",
    "PSU",
    "CASE",
    "CPU_COOLER",
    "MONITOR",
    "PERIPHERAL",
    "SERVICE",
    "OTHER",
]
LeadAction = Literal["EDIT", "QUALIFY", "LOSE", "REOPEN", "ASSIGN", "TAKE", "CREATE_QUOTE"]
QuoteAction = Literal["EDIT", "SUBMIT", "APPROVE", "RETURN", "SEND", "ACCEPT", "REJECT", "REVISE", "CANCEL"]
Locale = Literal["uz", "ru", "en"]

MAX_QUOTE_LINES = 15  # 14 §4.6
MAX_LINE_QTY = 99


# ------------------------------------------------------------------ lead


class Requirements(BaseModel):
    """AI slot'lari / operator yozuvi — shaxsiy ma'lumotsiz (requirements jsonb)."""

    model_config = ConfigDict(extra="forbid")

    budget_minor: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    workloads: list[Text] = Field(default_factory=list, max_length=10)
    monitor_needed: bool | None = None
    brand_prefs: list[Text] = Field(default_factory=list, max_length=10)
    notes: CleanText | None = Field(default=None, max_length=1000)


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID | None = None
    customer_name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    contact_phone: Text | None = Field(default=None, max_length=32)
    consent_contact: bool = False  # telefon faqat rozilik bilan saqlanadi (BL-042)
    requirements: Requirements = Field(default_factory=Requirements)
    assigned_membership_id: UUID | None = None


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    requirements: Requirements | None = None


class LeadLoseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: LostReason
    note: CleanText | None = Field(default=None, max_length=500)


class LeadAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID | None


class QuoteSummary(BaseModel):
    id: UUID
    number: int
    status: QuoteStatus
    total_uzs_minor: int
    current_revision_no: int
    updated_at: datetime


class LeadOrderSummary(BaseModel):
    """Lead'ning buyurtmalari (taklifdan yoki suhbatdan) — kartochkada ro'yxat."""

    id: UUID
    number: int
    status: str
    source: str
    total_minor: int
    created_at: datetime


class LeadOut(BaseModel):
    id: UUID
    number: int
    status: LeadStatus
    source: Literal["AI", "STAFF"]
    conversation_id: UUID | None
    customer_name: str | None
    contact_phone: str | None  # niqoblangan ("+998 90 *** ** 67"); to'liq — faqat lead kartochkasida
    has_contact_consent: bool
    requirements: dict[str, Any]
    budget_minor: int | None
    assigned: MemberRef | None
    lost_reason: LostReason | None
    lost_reason_inferred: bool
    lost_note: str | None
    won_order_id: UUID | None
    quotes: list[QuoteSummary]
    orders: list[LeadOrderSummary]
    allowed_actions: list[LeadAction]
    last_activity_at: datetime
    created_at: datetime
    updated_at: datetime
    version: int


class LeadListItem(BaseModel):
    id: UUID
    number: int
    status: LeadStatus
    source: Literal["AI", "STAFF"]
    customer_name: str | None
    budget_minor: int | None
    assigned: MemberRef | None
    quote_count: int
    last_activity_at: datetime
    updated_at: datetime


class LeadCounts(BaseModel):
    by_status: dict[str, int]  # faqat ochiq va yopilganlar bo'yicha (ko'rinadiganlari)
    mine: int  # menga biriktirilgan ochiq leadlar
    unassigned: int  # biriktirilmagan ochiq leadlar (navbat)


class LeadList(BaseModel):
    items: list[LeadListItem]
    next_cursor: str | None
    has_more: bool


class QuoteTransitionOut(BaseModel):
    at: datetime
    command: str
    from_status: str | None
    to_status: str
    actor_type: str
    actor_name: str | None
    reason: str | None


class History(BaseModel):
    items: list[QuoteTransitionOut]


# ------------------------------------------------------------------ taklif


class QuoteLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    qty: int = Field(default=1, ge=1, le=MAX_LINE_QTY)
    discount_pct: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=2)


class QuoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID | None = None  # bo'lmasa — lead avtomatik ochiladi (suhbatdan yoki qo'lda)
    conversation_id: UUID | None = None
    lines: list[QuoteLineIn] = Field(default_factory=list, max_length=MAX_QUOTE_LINES)
    requirements: Requirements | None = None


class QuoteLinesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[QuoteLineIn] = Field(max_length=MAX_QUOTE_LINES)


class QuoteApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: CleanText | None = Field(default=None, max_length=1000)  # REVIEW_REQUIRED da majburiy (dalil)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: CleanText = Field(min_length=3, max_length=500)


class QuoteOptionalReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: CleanText | None = Field(default=None, max_length=500)


class FindingOut(BaseModel):
    rule_id: str
    severity: Literal["BLOCK", "REVIEW_REQUIRED", "WARNING", "INFO"]
    message_key: str
    explanation: str
    hint: dict[str, Any] | None = None
    hint_text: str | None = None
    parts: list[str] = Field(default_factory=list)


class CompatibilityOut(BaseModel):
    decision: CompatDecision
    can_publish: bool
    ruleset_version: str
    estimated_power_w: int | None
    recommended_psu_w: int | None = None
    findings: list[FindingOut]
    stage: Literal["LIVE", "SUBMIT", "APPROVAL", "ACCEPT"]
    checked_at: datetime | None = None


class QuoteLineOut(BaseModel):
    id: UUID
    position: int
    role: LineRole
    sku_id: UUID
    product_id: UUID
    title: str
    sku_code: str
    qty: int
    unit_price_minor: int
    currency: Literal["UZS", "USD"]
    exchange_rate: Decimal | None
    unit_price_uzs_minor: int
    discount_pct: Decimal
    line_total_uzs_minor: int
    warranty_months: int | None
    spec_id: UUID | None
    spec_version: int | None


class RevisionSummary(BaseModel):
    id: UUID
    revision: int
    total_uzs_minor: int
    compatibility_decision: CompatDecision | None
    submitted_at: datetime | None
    approved_at: datetime | None
    returned_note: str | None
    created_at: datetime


class LineAvailability(BaseModel):
    """Xodim uchun: qatorning omborda bor-yo'qligi (DEC-100b — band qilinmaydi, faqat ma'lumot; QA 6a F14)."""

    sku_id: UUID
    qty: int
    available: int  # hamma faol filiallarda sotuvga mavjud
    enough: bool


class QuoteOut(BaseModel):
    id: UUID
    number: int
    lead_id: UUID
    lead_number: int
    conversation_id: UUID | None
    status: QuoteStatus
    created_by_kind: Literal["AI", "STAFF"]
    created_by: MemberRef | None
    revision: int
    revision_id: UUID
    requirements: dict[str, Any]
    lines: list[QuoteLineOut]
    subtotal_uzs_minor: int
    discount_uzs_minor: int
    total_uzs_minor: int
    compatibility: CompatibilityOut | None
    approval_mode: Literal["MANUAL", "AUTO_RISKY_ONLY"] | None
    approved_by: MemberRef | None
    approved_at: datetime | None
    approval_note: str | None
    returned_note: str | None
    sent_at: datetime | None
    expires_at: datetime | None
    accepted_at: datetime | None
    accepted_order_id: UUID | None
    rejected_at: datetime | None
    reject_reason: str | None
    revisions: list[RevisionSummary]
    availability: list[LineAvailability]
    # Tasdiqlangan/yuborilgan taklif: katalog narxi o'zgargan (qabulda QUOTE_CHANGED — yangi versiya kerak)
    price_changed: bool
    approver_discount_limit_pct: Decimal  # shu xodim tasdiqlay oladigan eng katta chegirma (DEC-110)
    allowed_actions: list[QuoteAction]
    created_at: datetime
    updated_at: datetime
    version: int


class RevisionOut(BaseModel):
    """Eski versiyani to'liq ko'rish (qatorlar va muzlagan moslik)."""

    id: UUID
    revision: int
    requirements: dict[str, Any]
    lines: list[QuoteLineOut]
    subtotal_uzs_minor: int
    discount_uzs_minor: int
    total_uzs_minor: int
    compatibility: list[CompatibilityOut]  # har bosqich (SUBMIT, APPROVAL, ACCEPT) natijasi
    submitted_at: datetime | None
    approved_by: MemberRef | None
    approved_at: datetime | None
    approval_mode: Literal["MANUAL", "AUTO_RISKY_ONLY"] | None
    approval_note: str | None
    returned_note: str | None
    created_at: datetime


class QuoteListItem(BaseModel):
    id: UUID
    number: int
    lead_id: UUID
    lead_number: int
    customer_name: str | None
    status: QuoteStatus
    total_uzs_minor: int
    compatibility_decision: CompatDecision | None
    created_by: MemberRef | None
    expires_at: datetime | None
    updated_at: datetime


class QuoteList(BaseModel):
    items: list[QuoteListItem]
    next_cursor: str | None
    has_more: bool


class QuoteSendOut(BaseModel):
    """Havola tokeni FAQAT shu javobda (bazada — xeshi). Takroriy yuborish — yangi havola, eskisi bekor."""

    quote: QuoteOut
    public_path: str  # "/q/{token}" — sayt manziliga qo'shiladi
    public_url: str | None  # sayt manzili ma'lum bo'lsa (STOREFRONT_PUBLIC_URL)


class QuoteAcceptOut(BaseModel):
    quote: QuoteOut
    order_id: UUID
    order_number: int


# ------------------------------------------------------------------ PC yig'ish sahifasi


class BuildLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    qty: int = Field(default=1, ge=1, le=MAX_LINE_QTY)


class BuildCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[BuildLineIn] = Field(max_length=MAX_QUOTE_LINES)
    full_build: bool = True
    branch_id: UUID | None = None


class BuildLineOut(BaseModel):
    sku_id: UUID
    qty: int
    title: str
    role: LineRole
    unit_price_uzs_minor: int | None
    line_total_uzs_minor: int | None
    sellable: bool
    available: int  # filial berilsa — shu filialda, aks holda hamma faol filiallarda


class BuildCheckOut(BaseModel):
    lines: list[BuildLineOut]
    total_uzs_minor: int
    compatibility: CompatibilityOut


class CandidatesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: LineRole
    lines: list[BuildLineIn] = Field(default_factory=list, max_length=MAX_QUOTE_LINES)
    q: Text | None = Field(default=None, max_length=100)
    branch_id: UUID | None = None
    only_compatible: bool = False
    limit: int = Field(default=12, ge=1, le=20)


class CandidateOut(BaseModel):
    sku_id: UUID
    product_id: UUID
    title: str
    sku_code: str
    unit_price_uzs_minor: int
    available: int
    decision: CompatDecision
    findings: list[FindingOut]


class CandidatesOut(BaseModel):
    role: LineRole
    items: list[CandidateOut]


# ------------------------------------------------------------------ sayt (xaridor havolasi)


class PublicQuoteLine(BaseModel):
    title: str
    role: LineRole
    qty: int
    unit_price_uzs_minor: int
    discount_pct: Decimal
    line_total_uzs_minor: int
    warranty_months: int | None


class PublicCompatibilityOut(BaseModel):
    """Xaridorga: ichki kutubxona so'zlari yo'q (QA 6a F16). REVIEW — "do'kon mutaxassisi tekshirgan" va
    qisqa izoh; faqat xaridorga foydali maslahatlar (WARNING/INFO). Tasdiqlovchining dalil izohi — ichki."""

    decision: CompatDecision
    expert_checked: bool
    note: str | None
    findings: list[FindingOut]
    estimated_power_w: int | None


class PublicQuoteOut(BaseModel):
    """Shaxsiy ma'lumotsiz: ism, telefon, xodim yo'q (BL-042)."""

    number: int
    status: Literal["SENT", "ACCEPTED", "REJECTED", "EXPIRED", "CANCELLED", "REPLACED"]
    lines: list[PublicQuoteLine]
    subtotal_uzs_minor: int
    discount_uzs_minor: int
    total_uzs_minor: int
    compatibility: PublicCompatibilityOut | None
    expires_at: datetime | None
    accepted_at: datetime | None
    order_number: int | None


class PublicAcceptOut(BaseModel):
    status: Literal["ACCEPTED"]
    order_number: int
    tracking_path: str  # "/orders/{token}" — buyurtma holati sahifasi (4-modul)


class PublicRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: CleanText | None = Field(default=None, max_length=500)
