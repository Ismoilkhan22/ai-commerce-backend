"""Kafolat murojaatlari API kontrakti (db/support.md, DEC-145)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.text import CleanText, Text

CaseType = Literal["WARRANTY", "RETURN"]
CaseStatus = Literal["NEW", "IN_REVIEW", "APPROVED", "REJECTED", "IN_SERVICE", "RESOLVED", "CLOSED"]
CaseSource = Literal["ORDER_LINE", "QUICK_SALE_LINE", "EXTERNAL"]
Resolution = Literal["REPAIR", "REPLACE", "REFUND"]
Outcome = Literal["REPAIRED", "REPLACED", "RETURNED"]
RejectReason = Literal[
    "WARRANTY_EXPIRED", "NO_DEFECT_FOUND", "USER_DAMAGE", "NOT_OUR_SALE", "RETURN_NOT_ALLOWED", "OTHER"
]
NoteKind = Literal["NOTE", "DIAGNOSIS", "CUSTOMER_CONTACT"]
CreatedVia = Literal["STAFF_PANEL", "CONVERSATION", "ORDER_PAGE"]
Locale = Literal["uz", "ru", "en"]

MAX_QTY = 1000


# ------------------------------------------------------------------ kirish


class CaseOpenIn(BaseModel):
    """Murojaat ochish. `ORDER_LINE` / `QUICK_SALE_LINE`: kafolat va xaridor nusxasi sotuvdan olinadi;
    `EXTERNAL` (tizimdan oldingi sotuv, chek bo'yicha): xodim yozadi, qarorni doim menejer qiladi."""

    model_config = ConfigDict(extra="forbid")

    source: CaseSource
    type: CaseType = "WARRANTY"
    created_via: CreatedVia = "STAFF_PANEL"
    order_id: UUID | None = None
    order_line_id: UUID | None = None
    quick_sale_id: UUID | None = None
    quick_sale_line_id: UUID | None = None
    # EXTERNAL
    external_sale_ref: CleanText | None = Field(default=None, min_length=1, max_length=100)
    branch_id: UUID | None = None  # EXTERNAL da majburiy; sotuvdan ochilganda sotuv filiali
    sku_id: UUID | None = None
    title: CleanText | None = Field(default=None, min_length=1, max_length=200)
    sold_at: datetime | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=120)

    qty: int = Field(default=1, ge=1, le=MAX_QTY)
    serial_number: CleanText | None = Field(default=None, max_length=100)
    problem_description: CleanText = Field(min_length=3, max_length=2000)

    customer_name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    customer_phone: Text | None = Field(default=None, max_length=40)
    conversation_id: UUID | None = None
    customer_locale: Locale | None = None
    # Muddat tugagan sotuvga murojaat: faqat menejer/ega, sabab bilan (DEC-145)
    warranty_override_reason: CleanText | None = Field(default=None, min_length=3, max_length=500)


class CaseStartReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_received: bool = False  # mahsulot shu paytda do'konga topshirildi


class CaseApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Resolution
    replacement_sku_id: UUID | None = None  # REPLACE: boshqa model bo'lsa; bo'sh — o'sha SKU
    decision_note: CleanText | None = Field(default=None, min_length=3, max_length=500)


class CaseRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reject_reason: RejectReason
    note: CleanText | None = Field(default=None, min_length=3, max_length=500)


class CaseResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refund_amount_minor: int | None = Field(default=None, ge=0, le=10**13)  # REFUND: faqat ma'lumot (DEC-100)
    note: CleanText | None = Field(default=None, min_length=3, max_length=500)


class CaseResolutionChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Resolution
    replacement_sku_id: UUID | None = None
    reason: CleanText = Field(min_length=3, max_length=500)


class CaseReceiveItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: CleanText | None = Field(default=None, min_length=1, max_length=500)


class CaseAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID | None


class CaseNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NoteKind = "NOTE"
    body: CleanText = Field(min_length=1, max_length=2000)


class CaseAttachmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID  # POST /files?purpose=SUPPORT_EVIDENCE
    caption: CleanText | None = Field(default=None, min_length=1, max_length=200)
    source_message_id: UUID | None = None


# ------------------------------------------------------------------ chiqish


class CaseMemberRef(BaseModel):
    membership_id: UUID
    full_name: str | None


class CaseListItem(BaseModel):
    id: UUID
    number: int
    type: CaseType
    status: CaseStatus
    source: CaseSource
    created_via: CreatedVia
    branch_id: UUID
    branch_name: str | None
    sku_id: UUID | None
    title: str
    sku_code: str | None
    qty: int
    sold_at: datetime
    warranty_months: int | None
    warranty_until: date | None
    within_warranty: bool
    warranty_override_reason: str | None
    problem_description: str
    customer_name: str | None
    conversation_id: UUID | None
    resolution: Resolution | None
    outcome: Outcome | None
    reject_reason: RejectReason | None
    item_received_at: datetime | None
    opened_by: CaseMemberRef | None
    assigned_to: CaseMemberRef | None
    created_at: datetime
    updated_at: datetime
    version: int


class CaseList(BaseModel):
    items: list[CaseListItem]
    next_cursor: str | None
    has_more: bool


class CaseNoteOut(BaseModel):
    id: UUID
    kind: NoteKind
    body: str
    author: CaseMemberRef | None
    created_at: datetime


class CaseAttachmentOut(BaseModel):
    id: UUID
    file_id: UUID
    mime_type: str | None
    url: str | None  # yopiq fayl — qisqa muddatli imzoli havola
    url_expires_at: datetime | None
    caption: str | None
    source_message_id: UUID | None
    added_by: CaseMemberRef | None
    created_at: datetime


class CaseTimelineItem(BaseModel):
    """Murojaat tarixi: holat o'tishlari (`platform.transition_log`) va izohlar, eskisi birinchi."""

    at: datetime
    kind: Literal["TRANSITION", "NOTE"]
    command: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    note_kind: NoteKind | None = None
    body: str | None = None  # izoh matni yoki o'tish sababi
    actor_type: str | None = None
    actor_name: str | None = None


class CaseStockOut(BaseModel):
    quarantined: int
    restocked: int
    written_off: int
    replacement_issued: int


class CaseDetail(CaseListItem):
    order_id: UUID | None
    order_line_id: UUID | None
    quick_sale_id: UUID | None
    quick_sale_line_id: UUID | None
    external_sale_ref: str | None
    serial_number: str | None
    customer_phone: str | None  # shifrlangan saqlanadi; faqat xodimga ochiladi
    customer_locale: Locale
    diagnosed_at: datetime | None
    replacement_sku_id: UUID | None
    decided_by: CaseMemberRef | None
    decided_at: datetime | None
    decision_note: str | None
    service_started_at: datetime | None
    refund_amount_minor: int | None
    resolved_at: datetime | None
    resolved_by: CaseMemberRef | None
    closed_at: datetime | None
    closed_by: CaseMemberRef | None  # bo'sh va closed_at bor — 7 kundan keyin tizim yopdi
    stock: CaseStockOut | None
    notes: list[CaseNoteOut]
    attachments: list[CaseAttachmentOut]
    timeline: list[CaseTimelineItem]
