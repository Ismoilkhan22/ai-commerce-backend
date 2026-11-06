"""Saytdan buyurtma so'rovi va buyurtma holati sahifasi (DEC-115, storefront.md §6–§7).

Javobda xaridorning o'z buyurtmasi haqida faqat kerakli narsa: raqam, holat, qatorlar, summa, filial.
Telefon, manzil va izoh holat sahifasida ko'rsatilmaydi — havola birovning qo'liga tushsa ham.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.domains.commerce.orders.schemas import MAX_LINE_QTY, MAX_LINES, CustomerLocale, FulfillmentMethod
from app.shared.text import CleanText

PublicOrderStatus = Literal["RECEIVED", "CONFIRMED", "PREPARING", "READY", "COMPLETED", "CANCELLED"]


class OrderRequestLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    qty: StrictInt = Field(ge=1, le=MAX_LINE_QTY)  # "2" yoki true emas — faqat butun son (QA M04 F8)


class OrderRequestIn(BaseModel):
    """Savatcha brauzerda turadi; bu yerga faqat yuborilgan so'rov keladi (commerce.md §12)."""

    model_config = ConfigDict(extra="forbid")

    lines: list[OrderRequestLineIn] = Field(min_length=1, max_length=MAX_LINES)
    customer_name: CleanText = Field(min_length=1, max_length=120)
    customer_phone: str = Field(max_length=32, description="+998 90 123 45 67")
    customer_locale: CustomerLocale = "uz"
    customer_comment: CleanText | None = Field(default=None, max_length=1000)
    fulfillment_method: FulfillmentMethod = "PICKUP"
    branch_id: UUID | None = Field(
        default=None, description="Olib ketishda majburiy — ochiq olib ketish joyi"
    )
    delivery_address: CleanText | None = Field(default=None, max_length=500)
    consent_version: str = Field(max_length=64, description="`GET /site` dagi `consent.version`")


class OrderRequestLineOut(BaseModel):
    sku_id: UUID
    title: str
    qty: int
    unit_price_uzs_minor: int
    line_total_minor: int
    available_in_branch: bool = Field(
        description="Tanlangan filialda (yetkazishda — umuman) shu miqdor bormi. Yo'q bo'lsa ham so'rov "
        "qabul "
        "qilinadi — operator muqobil taklif qiladi (DEC-135)"
    )


class OrderRequestOut(BaseModel):
    number: int
    status: PublicOrderStatus
    tracking_token: str = Field(
        description="Holat havolasi uchun — bazada faqat xeshi (bir marta ko'rsatiladi)"
    )
    tracking_path: str = Field(description="/orders/{token} — sayt manziliga qo'shiladi")
    fulfillment_method: FulfillmentMethod
    total_uzs_minor: int
    lines: list[OrderRequestLineOut]
    created_at: datetime


class TrackingBranch(BaseModel):
    name: str
    address: str
    phone: str | None


class TrackingLine(BaseModel):
    title: str
    qty: int
    unit_price_uzs_minor: int
    line_total_minor: int


class TrackingOut(BaseModel):
    number: int
    status: PublicOrderStatus
    fulfillment_method: FulfillmentMethod
    branch: TrackingBranch | None = Field(description="Olib ketish joyi (filial tanlangan bo'lsa)")
    lines: list[TrackingLine]
    total_uzs_minor: int
    created_at: datetime
    updated_at: datetime
