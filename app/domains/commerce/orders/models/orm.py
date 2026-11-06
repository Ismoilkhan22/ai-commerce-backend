"""commerce.orders, order_lines, order_notes, order_counters, reservations — db/commerce.dbml (S4, DEC-134).

Xaridor telefoni va manzili — ustun darajasida shifrlangan (`EncryptedString`, 26 §4); telefon bo'yicha
qidirish — kalitli xesh (`customer_phone_hmac`). Bu ustunlar log, audit diff va outbox'ga tushmaydi.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.encryption import EncryptedString
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

ORDER_STATUSES = (
    "DRAFT",
    "PENDING_CONFIRMATION",
    "CONFIRMED",
    "PROCESSING",
    "COMPLETED",
    "CANCELLED",
    "EXCEPTION",
)
ORDER_SOURCES = ("AI", "STOREFRONT", "STAFF", "QUOTE")  # QUOTE — PC taklifidan (6-modul)
FULFILLMENT_METHODS = ("PICKUP", "DELIVERY")
PAID_MARK_METHODS = ("CASH", "CARD", "TRANSFER", "OTHER")
NOTE_KINDS = ("NOTE", "CALL_RESULT")
RESERVATION_STATUSES = ("ACTIVE", "ALLOCATED", "CONSUMED", "RELEASED", "EXPIRED")
CUSTOMER_LOCALES = ("uz", "ru", "en")


class Order(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "number"),
        UniqueConstraint("tracking_token_hash"),
        # Takror so'rovga birinchi buyurtma qaytadi (BL-046) — faqat source_request_id bor qatorlar
        Index(
            "uq_orders_source_request",
            "shop_id",
            "source",
            "source_request_id",
            unique=True,
            postgresql_where=text("source_request_id IS NOT NULL"),
        ),
        Index("ix_orders_shop_id_status_created_at", "shop_id", "status", "created_at"),
        Index("ix_orders_shop_id_created_at", "shop_id", "created_at"),
        Index(
            "ix_orders_shop_id_assigned_membership_id_status", "shop_id", "assigned_membership_id", "status"
        ),
        Index("ix_orders_shop_id_customer_phone_hmac", "shop_id", "customer_phone_hmac"),
        Index(
            "ix_orders_shop_id_lead_id", "shop_id", "lead_id", postgresql_where=text("lead_id IS NOT NULL")
        ),
        # Taklifdan yaratilgan buyurtma (commerce_quotes.dbml, "commerce.dbml ga ta'sir")
        ForeignKeyConstraint(
            ["shop_id", "quote_id"],
            ["commerce.quotes.shop_id", "commerce.quotes.id"],
            ondelete="RESTRICT",
            name="fk_orders_quote",
        ),
        ForeignKeyConstraint(
            ["shop_id", "quote_revision_id"],
            ["commerce.quote_revisions.shop_id", "commerce.quote_revisions.id"],
            ondelete="RESTRICT",
            name="fk_orders_quote_revision",
        ),
        ForeignKeyConstraint(
            ["shop_id", "lead_id"],
            ["commerce.leads.shop_id", "commerce.leads.id"],
            ondelete="RESTRICT",
            name="fk_orders_lead",
        ),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint("total_minor >= 0", name="total_non_negative"),
        CheckConstraint("currency = 'UZS'", name="currency"),
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status"),
        CheckConstraint(f"source IN {ORDER_SOURCES}", name="source"),
        CheckConstraint(f"fulfillment_method IN {FULFILLMENT_METHODS}", name="fulfillment_method"),
        CheckConstraint(f"customer_locale IN {CUSTOMER_LOCALES}", name="customer_locale"),
        CheckConstraint(f"paid_mark_method IN {PAID_MARK_METHODS}", name="paid_mark_method"),
        CheckConstraint(
            "status NOT IN ('CONFIRMED', 'PROCESSING', 'COMPLETED', 'EXCEPTION') "
            "OR (branch_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmed_has_branch",
        ),
        CheckConstraint(
            "(paid_mark_at IS NULL AND paid_mark_by IS NULL AND paid_mark_method IS NULL) "
            "OR (paid_mark_at IS NOT NULL AND paid_mark_by IS NOT NULL AND paid_mark_method IS NOT NULL)",
            name="paid_mark_together",
        ),
        {"schema": "commerce"},
    )

    number: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    source: Mapped[str] = mapped_column(Text)
    source_request_id: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[UUID | None]  # messaging.conversations.id — FK'siz
    customer_ref: Mapped[UUID | None]  # messaging.customer_identities.id — FK'siz
    quote_id: Mapped[UUID | None]  # S3
    quote_revision_id: Mapped[UUID | None]  # S3
    lead_id: Mapped[UUID | None]  # lead WON avtomatikasi (buyurtma topshirilganda)
    branch_id: Mapped[UUID | None]  # platform.branches.id — FK'siz; bir buyurtma — bir filial (DEC-134)
    assigned_membership_id: Mapped[UUID | None]  # mas'ul operator (DEC-108)
    fulfillment_method: Mapped[str] = mapped_column(Text, server_default="PICKUP")
    customer_name: Mapped[str | None] = mapped_column(Text)
    customer_phone_enc: Mapped[str | None] = mapped_column(EncryptedString)
    customer_phone_hmac: Mapped[str | None] = mapped_column(Text)
    delivery_address_enc: Mapped[str | None] = mapped_column(EncryptedString)
    customer_locale: Mapped[str] = mapped_column(Text, server_default="uz")
    customer_comment: Mapped[str | None] = mapped_column(Text)
    consent_version: Mapped[str | None] = mapped_column(Text)
    pii_erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(Text, server_default="UZS")
    total_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[UUID | None]
    processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_by: Mapped[UUID | None]  # "olib ketishga tayyor" ni kim bosdi (QA U3)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[UUID | None]
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[UUID | None]
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    paid_mark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_mark_by: Mapped[UUID | None]
    paid_mark_method: Mapped[str | None] = mapped_column(Text)
    tracking_token_hash: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None]  # platform.memberships.id; AI va saytda NULL


class OrderLine(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint(
            "shop_id", "order_id", "id"
        ),  # band FK'i qator aynan shu buyurtmaniki ekanini kafolatlaydi
        UniqueConstraint("shop_id", "order_id", "sku_id"),  # bir buyurtmada bir SKU — bitta qator
        ForeignKeyConstraint(
            ["shop_id", "order_id"], ["commerce.orders.shop_id", "commerce.orders.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price_minor > 0 AND unit_price_uzs_minor > 0", name="price_positive"),
        CheckConstraint("line_total_minor >= 0", name="total_non_negative"),
        CheckConstraint("currency IN ('UZS', 'USD')", name="currency"),
        CheckConstraint("currency = 'UZS' OR exchange_rate_snapshot IS NOT NULL", name="usd_needs_rate"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="discount_range"),
        {"schema": "commerce"},
    )

    order_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    sku_id: Mapped[UUID]  # catalog.skus.id — FK'siz
    product_id: Mapped[UUID | None]
    title_snapshot: Mapped[str] = mapped_column(Text)
    sku_code_snapshot: Mapped[str] = mapped_column(Text)
    qty: Mapped[int] = mapped_column(Integer)
    price_version_id: Mapped[UUID]
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(Text)
    exchange_rate_id: Mapped[UUID | None]
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit_price_uzs_minor: Mapped[int] = mapped_column(BigInteger)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="0")
    discount_requested_by: Mapped[UUID | None]
    discount_approved_by: Mapped[UUID | None]
    discount_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    # COMPLETE paytida o'rtacha tannarxdan nusxa — foyda shu bilan muzlaydi (DEC-146); noma'lum — NULL
    unit_cost_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)


class OrderNote(IdMixin, ShopScopedMixin, Base):
    """Faqat qo'shiladi. Matnda PII bo'lishi mumkin — anonimlashtirishda tozalanadi (26 §2)."""

    __tablename__ = "order_notes"
    __table_args__ = (
        Index("ix_order_notes_shop_id_order_id_created_at", "shop_id", "order_id", "created_at"),
        ForeignKeyConstraint(
            ["shop_id", "order_id"], ["commerce.orders.shop_id", "commerce.orders.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"kind IN {NOTE_KINDS}", name="kind"),
        {"schema": "commerce"},
    )

    order_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text, server_default="NOTE")
    author_membership_id: Mapped[UUID]
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderCounter(Base):
    """Shop ichida ketma-ket buyurtma raqami. Yaratish tranzaksiyasida +1 — rollback bo'lsa raqam qaytadi."""

    __tablename__ = "order_counters"
    __table_args__ = ({"schema": "commerce"},)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    last_number: Mapped[int] = mapped_column(BigInteger, server_default="0")


class Reservation(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Buyurtma qatori uchun band (FSM-07). Har o'tish qoldiq va daftar bilan bitta tranzaksiyada."""

    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "order_line_id"),  # bir qatorga bitta band
        Index("ix_reservations_shop_id_order_id", "shop_id", "order_id"),
        # "Bekor qilinsinmi?" navbati (DEC-104, DEC-134) — faqat band va ajratilganlar
        Index(
            "ix_reservations_shop_id_review_at",
            "shop_id",
            "review_at",
            postgresql_where=text("status IN ('ACTIVE', 'ALLOCATED')"),
        ),
        ForeignKeyConstraint(
            ["shop_id", "order_id"], ["commerce.orders.shop_id", "commerce.orders.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["shop_id", "order_id", "order_line_id"],
            ["commerce.order_lines.shop_id", "commerce.order_lines.order_id", "commerce.order_lines.id"],
            ondelete="RESTRICT",
            name="fk_reservations_order_line",
        ),
        ForeignKeyConstraint(
            ["shop_id", "branch_id", "sku_id"],
            [
                "commerce.stock_balances.shop_id",
                "commerce.stock_balances.branch_id",
                "commerce.stock_balances.sku_id",
            ],
            ondelete="RESTRICT",
            name="fk_reservations_balance",
        ),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint(f"status IN {RESERVATION_STATUSES}", name="status"),
        {"schema": "commerce"},
    )

    order_id: Mapped[UUID]
    order_line_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    sku_id: Mapped[UUID]
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    allocated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
