"""Katalog importi API kontrakti (18 §13)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.shared.text import Text

ImportStatus = Literal[
    "PARSING",
    "UPLOADED",
    "MAPPED",
    "VALIDATING",
    "VALIDATED",
    "COMMITTING",
    "STOCK_PENDING",
    "COMPLETED",
    "FAILED",
    "EXPIRED",
    "CANCELLED",
]
ConflictPolicy = Literal["CREATE_ONLY", "UPDATE_EXISTING", "UPDATE_PRICE_ONLY", "STOCK_ONLY"]
RowAction = Literal["CREATE", "UPDATE", "SKIP", "ERROR"]
RowResult = Literal["CREATED", "UPDATED", "SKIPPED", "ERROR"]
SpecMatch = Literal["MPN", "MODEL", "MULTIPLE", "NONE", "NOT_APPLICABLE"]
ImportField = Literal[
    "sku_code",
    "title",
    "category",
    "brand",
    "model",
    "mpn",
    "variant_name",
    "condition",
    "price",
    "currency",
    "quantity",
    "branch",
    "warranty_months",
    "description",
    "attributes",
    "image_urls",
    "barcode",
]


class DetectedColumn(BaseModel):
    index: int
    header: str
    suggested_field: ImportField | None
    samples: list[str]  # birinchi qatorlardan 3 tagacha qiymat (moslash ekrani uchun)


class ImportCreateIn(BaseModel):
    """`POST /shop/files?purpose=IMPORT_FILE` dan olingan fayl."""

    model_config = ConfigDict(extra="forbid")

    file_id: UUID


class ImportMappingIn(BaseModel):
    """Maydon → fayldagi ustun indeksi (`detected_columns[].index`). Yoki `mapping_id` — saqlangan shablon
    sarlavha nomlari bo'yicha shu faylga qo'llanadi (QA F13); ikkalasi berilsa — `mapping` ustun."""

    model_config = ConfigDict(extra="forbid")

    mapping: dict[ImportField, int] = Field(default_factory=dict)
    mapping_id: UUID | None = None
    conflict_policy: ConflictPolicy = "UPDATE_EXISTING"
    default_branch_id: UUID | None = None
    save_as: Text | None = Field(default=None, min_length=1, max_length=100)  # shablon nomi (ixtiyoriy)

    @model_validator(mode="after")
    def _mapping_or_template(self) -> ImportMappingIn:
        if not self.mapping and self.mapping_id is None:
            raise ValueError("mapping or mapping_id is required")
        return self


class ImportRowUpdate(BaseModel):
    """Ko'rib chiqishda: qatorni yozishdan chiqarish yoki bir nechta nomzoddan kutubxona modelini tanlash."""

    model_config = ConfigDict(extra="forbid")

    selected: bool | None = None
    spec_id: UUID | None = None


class ImportStats(BaseModel):
    create: int = 0
    update: int = 0
    skip: int = 0
    error: int = 0
    with_stock: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    stock_applied: int = 0
    stock_no_change: int = 0
    stock_pending: int = 0
    stock_errors: int = 0


class ImportOut(BaseModel):
    id: UUID
    status: ImportStatus
    file_format: Literal["XLSX", "CSV"]
    original_filename: str
    sheet_name: str | None
    conflict_policy: ConflictPolicy
    mapping: dict[str, int] | None
    detected_columns: list[DetectedColumn]
    warnings: list[str]  # CSV_CP1251, STOCK_SKIPPED_NO_PERMISSION, …
    default_branch_id: UUID | None
    has_stock_rows: bool
    total_rows: int
    processed_rows: int
    stats: ImportStats
    error_code: str | None
    created_by: UUID
    created_by_name: str | None  # tarix ro'yxati uchun
    committed_by: UUID | None
    validated_at: datetime | None
    committed_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    version: int


class ImportList(BaseModel):
    items: list[ImportOut]


class ImportRowError(BaseModel):
    field: str
    code: str


class ImportRowOut(BaseModel):
    row_number: int
    action: RowAction
    values: dict[str, Any]  # tozalangan qiymatlar (asl qiymatlar xatolar CSV'sida)
    # Yangilanishda nima o'zgaradi: {"fields": {nom: {old, new}}, "price": {old, new, currency}} —
    # ko'rib chiqish ekrani uchun (sinov paytidagi holat)
    changes: dict[str, Any] | None
    stock: dict[str, Any] | None  # {branch_id, current, new} — joriy qoldiq commerce'dan
    errors: list[ImportRowError]
    spec_match: SpecMatch
    spec_id: UUID | None
    selected: bool
    result: RowResult | None
    product_id: UUID | None
    sku_id: UUID | None
    stock_result: str | None  # commerce natijasi: APPLIED | NO_CHANGE | PENDING_APPROVAL | ERROR
    stock_error: str | None


class ImportRowPage(BaseModel):
    items: list[ImportRowOut]
    next_cursor: str | None
    has_more: bool


class ImportMappingOut(BaseModel):
    id: UUID
    name: str
    mapping: dict[str, str]  # maydon → sarlavha nomi (keyingi faylda ustun tartibi o'zgarsa ham topiladi)
    conflict_policy: ConflictPolicy
    created_at: datetime
    version: int


class ImportMappingList(BaseModel):
    items: list[ImportMappingOut]


class ImportReportOut(BaseModel):
    """Xatolar CSV'si — yopiq fayl, vaqtinchalik imzoli havola."""

    file_id: UUID
    url: str
    url_expires_at: datetime | None
    rows: int
