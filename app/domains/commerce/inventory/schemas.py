"""Ombor API kontrakti: qoldiq, daftar, kirim, tuzatish (11 §9.4, db/commerce.md §1–§4)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.commerce.schemas import MemberRef
from app.shared.contracts.commerce import StockStatus
from app.shared.money import Currency
from app.shared.text import Text

MAX_UNIT_COST_MINOR = 10**12  # dona tannarxi uchun aql chegarasi (10 mlrd so'm/dollar), QA7 F8

AdjustmentKind = Literal["ADJUSTMENT", "QUARANTINE_IN", "RESTOCK", "WRITE_OFF"]
AdjustmentStatus = Literal["PENDING", "APPROVED", "REJECTED"]
LedgerReason = Literal[
    "RECEIPT",
    "ADJUSTMENT",
    "OFFLINE_SALE",
    "RESERVE",
    "ALLOCATE",
    "RELEASE",
    "SALE",
    "QUARANTINE_IN",
    "RETURN_QUARANTINE",
    "RESTOCK",
    "WRITE_OFF",
    "WARRANTY_REPLACEMENT",
]
LedgerRefType = Literal["RECEIPT", "ADJUSTMENT", "QUICK_SALE", "RESERVATION", "SUPPORT_CASE"]

MAX_QTY = 100_000


# ------------------------------------------------------------------ qoldiq


class StockItem(BaseModel):
    branch_id: UUID
    branch_name: str | None
    sku_id: UUID
    product_id: UUID | None
    sku_code: str | None
    title: str | None
    on_hand: int  # omborda jismonan
    reserved: int  # tasdiqlangan buyurtmalarga band
    allocated: int  # tayyorlanayotgan buyurtmalarga ajratilgan
    quarantine_qty: int  # tekshiruvda / "sotilmaydi"
    available: int  # sotuvga mavjud = on_hand − reserved − allocated (BL-019)
    stock_status: StockStatus
    updated_at: datetime
    version: int


class StockList(BaseModel):
    items: list[StockItem]
    next_cursor: str | None
    has_more: bool
    low_stock_threshold: int


# ------------------------------------------------------------------ SKU tanlash (buyurtma qatori, tez sotuv)

ProductStatus = Literal["DRAFT", "PUBLISHED", "HIDDEN", "ARCHIVED"]


class SkuPickItem(BaseModel):
    """Bitta so'rovda: nom, kod, holat, joriy narx va (filial berilsa) sotuvga mavjud son."""

    sku_id: UUID
    product_id: UUID
    title: str  # nom + variant
    product_title: str
    variant_name: str | None
    sku_code: str
    # PC roli (CPU, GPU, …) — "PC yig'ish" sahifasi qismni slotga o'zi qo'yadi; PC qismi emas — None
    spec_category: str | None = None
    product_status: ProductStatus
    sku_status: Literal["ACTIVE", "ARCHIVED"]
    orderable: bool  # buyurtmaga qo'shsa bo'ladi: chiqarilgan, narxi bor (dollar bo'lsa — kurs ham)
    quick_sellable: bool  # do'konda sotsa bo'ladi: chiqarilgan yoki yashirilgan, narxi bor
    currency: Literal["UZS", "USD"] | None
    amount_minor: int | None
    uzs_amount_minor: int | None  # xaridor ko'radigan narx, tiyinda
    exchange_rate_stale: bool
    available: int | None  # `branch_id` berilganda: shu filialda sotuvga mavjud
    stock_status: StockStatus | None


class SkuPickList(BaseModel):
    items: list[SkuPickItem]


class LedgerItem(BaseModel):
    id: UUID
    branch_id: UUID
    sku_id: UUID
    reason: LedgerReason
    delta_on_hand: int
    delta_reserved: int
    delta_allocated: int
    delta_quarantine: int
    on_hand_after: int
    reserved_after: int
    allocated_after: int
    quarantine_after: int
    ref_type: LedgerRefType
    ref_id: UUID
    actor: MemberRef | None
    created_at: datetime


class LedgerList(BaseModel):
    items: list[LedgerItem]
    next_cursor: str | None
    has_more: bool


# ------------------------------------------------------------------ kirim


class ReceiptLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    qty: int = Field(ge=1, le=MAX_QTY)
    # Tannarx (DEC-146): bitta dona narxi asl valyutada (tiyin/sent). Faqat `commerce.cost.edit` bor xodim
    # yuboradi; boshqalarda 403. Javobda tannarx qaytmaydi — uni `GET /costs` ko'rsatadi
    unit_cost_minor: int | None = Field(default=None, ge=1, le=MAX_UNIT_COST_MINOR)
    cost_currency: Currency = "UZS"


class ReceiptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    note: Text | None = Field(default=None, max_length=500)
    lines: list[ReceiptLineIn] = Field(min_length=1, max_length=100)


class ReceiptLineOut(BaseModel):
    sku_id: UUID
    sku_code: str | None
    title: str | None
    qty: int
    on_hand_after: int


class ReceiptOut(BaseModel):
    id: UUID
    branch_id: UUID
    branch_name: str | None
    note: str | None
    received_by: MemberRef | None
    created_at: datetime
    lines: list[ReceiptLineOut]


class ReceiptListItem(BaseModel):
    id: UUID
    branch_id: UUID
    branch_name: str | None
    note: str | None
    received_by: MemberRef | None
    created_at: datetime
    line_count: int
    units: int


class ReceiptList(BaseModel):
    items: list[ReceiptListItem]
    next_cursor: str | None
    has_more: bool


# ------------------------------------------------------------------ tuzatish


class AdjustmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    sku_id: UUID
    kind: AdjustmentKind = "ADJUSTMENT"
    # ADJUSTMENT: ± (sanoq farqi); qolgan turlarda — musbat miqdor
    delta: int = Field(ge=-MAX_QTY, le=MAX_QTY)
    reason: Text = Field(min_length=3, max_length=500)  # BL-022: sababsiz tuzatish yo'q
    evidence_file_id: UUID | None = None  # POST /files?purpose=STOCK_EVIDENCE
    # RESTOCK / WRITE_OFF: karantindagi dona qaysi kafolat murojaatidan (7b, DEC-145)
    support_case_id: UUID | None = None


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Text | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Text = Field(min_length=3, max_length=500)  # rad etish sababi majburiy


class EvidenceOut(BaseModel):
    file_id: UUID
    mime_type: str
    url: str  # yopiq fayl — 5 daqiqalik imzoli havola
    url_expires_at: datetime | None


class AdjustmentOut(BaseModel):
    id: UUID
    branch_id: UUID
    branch_name: str | None
    sku_id: UUID
    sku_code: str | None
    title: str | None
    kind: AdjustmentKind
    delta: int
    reason: str
    evidence: EvidenceOut | None
    status: AdjustmentStatus
    requested_by: MemberRef | None
    requested_at: datetime
    decided_by: MemberRef | None
    decided_at: datetime | None
    decision_note: str | None
    on_hand_before: int | None
    on_hand_after: int | None
    # Import tuzatishi: fayldagi absolyut qoldiq; tasdiqda farq joriy qoldiqdan qayta hisoblanadi (QA F3)
    target_on_hand: int | None = None
    support_case_id: UUID | None = None
    current_on_hand: int | None = None  # faqat PENDING uchun — "maqsad X (hozir Y)"
    version: int


class AdjustmentList(BaseModel):
    items: list[AdjustmentOut]
    next_cursor: str | None
    has_more: bool


# ------------------------------------------------------------------ tannarx (DEC-146): faqat ega


class SkuCostOut(BaseModel):
    sku_id: UUID
    sku_code: str | None
    title: str | None
    avg_unit_cost_uzs_minor: int  # joriy o'rtacha tortilgan tannarx, so'mda (tiyin)
    basis_qty: int  # shu qoldiq bo'yicha hisoblangan (hamma filial + tekshiruvda)
    cost_version: int
    last_reason: Literal["RECEIPT", "LATE_ENTRY", "MANUAL_SET", "IMPORT"]
    updated_at: datetime
    version: int


class SkuCostList(BaseModel):
    items: list[SkuCostOut]
    next_cursor: str | None
    has_more: bool


class SkuCostSetIn(BaseModel):
    """Tizimgacha bo'lgan qoldiq yoki xato o'rtachani qo'lda qo'yish."""

    model_config = ConfigDict(extra="forbid")

    avg_unit_cost_uzs_minor: int = Field(ge=1, le=MAX_UNIT_COST_MINOR)
    reason: Text = Field(min_length=3, max_length=500)  # izoh majburiy


class SkuCostChangeOut(BaseModel):
    id: UUID
    reason: Literal["RECEIPT", "LATE_ENTRY", "MANUAL_SET", "IMPORT"]
    ref_id: UUID | None
    avg_before_uzs_minor: int | None
    avg_after_uzs_minor: int
    basis_qty: int
    incoming_qty: int | None
    incoming_unit_cost_uzs_minor: int | None
    note: str | None
    actor: MemberRef | None
    created_at: datetime


class SkuCostHistory(BaseModel):
    items: list[SkuCostChangeOut]
    next_cursor: str | None
    has_more: bool
