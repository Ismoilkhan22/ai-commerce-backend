"""reporting read model'lari (db/reporting.dbml, 7c-modul): boshqa domenlar event'laridan quriladi.

Qoidalar (19 §3, DEC-146):
- shaxsiy ma'lumot YO'Q: faqat ID, kod, son, summa, vaqt;
- har jadvalda `shop_id`, RLS ENABLE + FORCE (migratsiyada); boshqa schemaga FK yo'q;
- `*_day` ustunlari shop vaqtidagi sana (Asia/Tashkent) — proyeksiya paytida yoziladi;
- versiyali jadvallarda (`aggregate_version`, `stock_version`) katta versiya g'olib: eski event bosmaydi.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Integer, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

SCHEMA = {"schema": "reporting"}


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectionCheckpoint(Base):
    """Har proyeksiya qayergacha yangilangan (`data_as_of`, BL-066)."""

    __tablename__ = "projection_checkpoints"
    __table_args__ = SCHEMA

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    projection: Mapped[str] = mapped_column(Text, primary_key=True)
    last_event_id: Mapped[UUID | None]
    last_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rebuilt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class OrderFact(Base):
    __tablename__ = "order_facts"
    __table_args__ = (
        Index("ix_order_facts_shop_id_completed_day", "shop_id", "completed_day"),
        Index("ix_order_facts_shop_id_created_day", "shop_id", "created_day"),
        Index("ix_order_facts_shop_id_status", "shop_id", "status"),
        SCHEMA,
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)  # AI | STOREFRONT | STAFF | QUOTE
    branch_id: Mapped[UUID | None]
    assigned_staff_id: Mapped[UUID | None]
    total_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(Text, server_default="UZS")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_day: Mapped[date] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_day: Mapped[date | None] = mapped_column(Date)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_day: Mapped[date | None] = mapped_column(Date)
    cancel_reason_code: Mapped[str | None] = mapped_column(Text)
    aggregate_version: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _now()


class OrderLineFact(Base):
    """Topshirilgan buyurtma qatorlari. `unit_cost_uzs_minor` NULL — tannarx noma'lum (PARTIAL_COST_DATA)."""

    __tablename__ = "order_line_facts"
    __table_args__ = (
        Index("ix_order_line_facts_shop_id_completed_day", "shop_id", "completed_day"),
        Index("ix_order_line_facts_shop_id_sku_id_completed_day", "shop_id", "sku_id", "completed_day"),
        SCHEMA,
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_id: Mapped[UUID]
    product_id: Mapped[UUID | None]
    category_code: Mapped[str | None] = mapped_column(Text)  # sotuv paytidagi toifa (R6)
    branch_id: Mapped[UUID | None]
    source: Mapped[str] = mapped_column(Text)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_day: Mapped[date] = mapped_column(Date)
    qty: Mapped[int] = mapped_column(Integer)
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    unit_cost_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)
    cost_total_minor: Mapped[int | None] = mapped_column(BigInteger)


class QuickSaleFact(Base):
    """Do'kondagi tez sotuv, qator darajasida (DEC-123). Manba (source) — doim `OFFLINE`."""

    __tablename__ = "quick_sale_facts"
    __table_args__ = (
        Index("ix_quick_sale_facts_shop_id_recorded_day", "shop_id", "recorded_day"),
        Index("ix_quick_sale_facts_shop_id_sku_id_recorded_day", "shop_id", "sku_id", "recorded_day"),
        SCHEMA,
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    sale_id: Mapped[UUID] = mapped_column(primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_id: Mapped[UUID]
    product_id: Mapped[UUID | None]
    category_code: Mapped[str | None] = mapped_column(Text)
    branch_id: Mapped[UUID]
    sold_by_staff_id: Mapped[UUID | None]
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_day: Mapped[date] = mapped_column(Date)
    qty: Mapped[int] = mapped_column(Integer)
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    unit_cost_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)
    cost_total_minor: Mapped[int | None] = mapped_column(BigInteger)


class SupportCaseFact(Base):
    __tablename__ = "support_case_facts"
    __table_args__ = (
        Index("ix_support_case_facts_shop_id_opened_day", "shop_id", "opened_day"),
        Index("ix_support_case_facts_shop_id_sku_id", "shop_id", "sku_id"),
        SCHEMA,
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(Text)  # WARRANTY | RETURN
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    sku_id: Mapped[UUID | None]
    branch_id: Mapped[UUID | None]
    within_warranty: Mapped[bool | None] = mapped_column(Boolean)
    resolution: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    refund_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opened_day: Mapped[date] = mapped_column(Date)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_day: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aggregate_version: Mapped[int] = mapped_column(BigInteger)


class ProductDim(Base):
    """SKU o'lchami: nom, toifa, joriy narx. Katalogdan o'qiladi; narx soatlik ish bilan yangilanadi."""

    __tablename__ = "product_dim"
    __table_args__ = (Index("ix_product_dim_shop_id_category_code", "shop_id", "category_code"), SCHEMA)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    sku_id: Mapped[UUID] = mapped_column(primary_key=True)
    product_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(Text)
    sku_code: Mapped[str | None] = mapped_column(Text)
    category_code: Mapped[str | None] = mapped_column(Text)
    category_name: Mapped[str | None] = mapped_column(Text)
    price_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _now()


class StockFact(Base):
    __tablename__ = "stock_facts"
    __table_args__ = (Index("ix_stock_facts_shop_id_sku_id", "shop_id", "sku_id"), SCHEMA)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    sku_id: Mapped[UUID] = mapped_column(primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer)
    allocated: Mapped[int] = mapped_column(Integer)
    available: Mapped[int] = mapped_column(Integer)
    quarantine_qty: Mapped[int] = mapped_column(Integer, server_default="0")
    stock_version: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _now()


class StockValueDaily(Base):
    """Ombor qiymati kunlik tarixi. Bugungi qator soatlik qayta hisoblanadi, o'tgan kunlar qoladi."""

    __tablename__ = "stock_value_daily"
    __table_args__ = SCHEMA

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    units: Mapped[int] = mapped_column(Integer)
    quarantine_units: Mapped[int] = mapped_column(Integer, server_default="0")
    value_at_price_minor: Mapped[int] = mapped_column(BigInteger)
    value_at_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    units_without_cost: Mapped[int] = mapped_column(Integer, server_default="0")
    units_without_price: Mapped[int] = mapped_column(Integer, server_default="0")
    computed_at: Mapped[datetime] = _now()


class ConversationFact(Base):
    __tablename__ = "conversation_facts"
    __table_args__ = (Index("ix_conversation_facts_shop_id_started_day", "shop_id", "started_day"), SCHEMA)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(primary_key=True)
    channel: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_day: Mapped[date] = mapped_column(Date)
    pending_inbound_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inbound_count: Mapped[int] = mapped_column(Integer, server_default="0")
    ai_reply_count: Mapped[int] = mapped_column(Integer, server_default="0")
    staff_reply_count: Mapped[int] = mapped_column(Integer, server_default="0")
    handoff_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageFact(Base):
    """Har xabar — bitta qator, matnsiz. `staff_id` — platform.principals.id (event aktori)."""

    __tablename__ = "message_facts"
    __table_args__ = (
        Index("ix_message_facts_shop_id_day_author", "shop_id", "day", "author"),
        Index("ix_message_facts_shop_id_staff_id_day", "shop_id", "staff_id", "day"),
        SCHEMA,
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    message_id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID]
    direction: Mapped[str] = mapped_column(Text)  # IN | OUT
    author: Mapped[str] = mapped_column(Text)  # CUSTOMER | AI | STAFF | SYSTEM
    staff_id: Mapped[UUID | None]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    day: Mapped[date] = mapped_column(Date)
    hour: Mapped[int] = mapped_column(SmallInteger)
    response_seconds: Mapped[int | None] = mapped_column(Integer)


class HandoffFact(Base):
    __tablename__ = "handoff_facts"
    __table_args__ = (
        Index("ix_handoff_facts_shop_id_opened_day", "shop_id", "opened_day"),
        Index("ix_handoff_facts_shop_id_conversation_id", "shop_id", "conversation_id"),
        SCHEMA,
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    handoff_id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opened_day: Mapped[date] = mapped_column(Date)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taken_by_staff_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="OPEN")  # OPEN | TAKEN


class AiUsageDaily(Base):
    """`platform.ai_usage` dan kunlik yig'ma (soatlik ish). Xom jadval 13 oyda tozalanadi — bu qoladi."""

    __tablename__ = "ai_usage_daily"
    __table_args__ = SCHEMA

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    purpose: Mapped[str] = mapped_column(Text, primary_key=True)
    model_id: Mapped[str] = mapped_column(Text, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(BigInteger)
    tokens_out: Mapped[int] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger)
    computed_at: Mapped[datetime] = _now()
