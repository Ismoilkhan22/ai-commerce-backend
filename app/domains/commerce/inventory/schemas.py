"""Ombor API kontrakti: qoldiq, daftar, kirim, tuzatish (11 §9.4, db/commerce.md §1–§4)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.commerce.schemas import MemberRef
from app.shared.contracts.commerce import StockStatus
from app.shared.text import Text

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
    version: int


class AdjustmentList(BaseModel):
    items: list[AdjustmentOut]
    next_cursor: str | None
    has_more: bool
