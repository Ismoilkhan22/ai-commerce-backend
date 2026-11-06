"""commerce.leads, quotes, quote_revisions, quote_lines, quote_compatibility_snapshots, hisoblagichlar —
db/commerce_quotes.dbml (6-modul, S3-05/S3-06; DEC-142 taklif).

Narx va moslik — nusxa (BL-030, BL-041): katalog keyin o'zgarsa ham yuborilgan taklif o'zgarmaydi.
Xaridor kontakti faqat rozilik bilan va shifrlangan (BL-042, 26 §4); outbox, audit va logga tushmaydi.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.encryption import EncryptedString
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

LEAD_STATUSES = ("NEW", "QUALIFIED", "QUOTED", "WON", "LOST")
OPEN_LEAD_STATUSES = ("NEW", "QUALIFIED", "QUOTED")
LOST_REASONS = ("TOO_EXPENSIVE", "OUT_OF_STOCK", "NOT_COMPATIBLE", "NO_RESPONSE", "BOUGHT_ELSEWHERE", "OTHER")
ACTOR_KINDS = ("AI", "STAFF", "CUSTOMER", "SYSTEM")
QUOTE_STATUSES = ("DRAFT", "REVIEW", "APPROVED", "SENT", "ACCEPTED", "REJECTED", "EXPIRED", "CANCELLED")
COMPAT_DECISIONS = ("PASS", "REVIEW_REQUIRED", "BLOCK")
COMPAT_STAGES = ("SUBMIT", "APPROVAL", "ACCEPT")
LINE_ROLES = (
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
)
APPROVAL_MODES = ("MANUAL", "AUTO_RISKY_ONLY")


class Lead(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Sotuv imkoniyati (FSM-05). Bitta suhbatda bitta ochiq lead."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "number"),
        Index(
            "uq_leads_ai_request",
            "shop_id",
            "ai_request_id",
            unique=True,
            postgresql_where=text("ai_request_id IS NOT NULL"),
        ),
        Index(
            "uq_leads_open_conversation",
            "shop_id",
            "conversation_id",
            unique=True,
            postgresql_where=text(
                "status IN ('NEW', 'QUALIFIED', 'QUOTED') AND merged_into_lead_id IS NULL "
                "AND conversation_id IS NOT NULL"
            ),
        ),
        Index("ix_leads_shop_id_status_updated_at", "shop_id", "status", "updated_at"),
        Index("ix_leads_shop_id_contact_phone_hmac", "shop_id", "contact_phone_hmac"),
        Index(
            "ix_leads_shop_id_assigned_membership_id_status", "shop_id", "assigned_membership_id", "status"
        ),
        ForeignKeyConstraint(
            ["shop_id", "merged_into_lead_id"],
            ["commerce.leads.shop_id", "commerce.leads.id"],
            ondelete="RESTRICT",
            name="fk_leads_merged_into",
        ),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint(f"status IN {LEAD_STATUSES}", name="status"),
        CheckConstraint("source IN ('AI', 'STAFF')", name="source"),
        CheckConstraint(f"lost_reason IN {LOST_REASONS}", name="lost_reason"),
        CheckConstraint("status <> 'LOST' OR lost_reason IS NOT NULL", name="lost_needs_reason"),
        CheckConstraint("budget_minor IS NULL OR budget_minor >= 0", name="budget_non_negative"),
        {"schema": "commerce"},
    )

    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="NEW")
    source: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[UUID | None]  # messaging.conversations.id — FK'siz
    customer_identity_id: Mapped[UUID | None]  # messaging.customer_identities.id — FK'siz
    customer_name: Mapped[str | None] = mapped_column(Text)
    contact_phone_enc: Mapped[str | None] = mapped_column(EncryptedString)
    contact_phone_hmac: Mapped[str | None] = mapped_column(Text)
    consent_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    assigned_membership_id: Mapped[UUID | None]
    lost_reason: Mapped[str | None] = mapped_column(Text)
    lost_reason_inferred: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    lost_note: Mapped[str | None] = mapped_column(Text)
    won_order_id: Mapped[UUID | None]
    merged_into_lead_id: Mapped[UUID | None]
    ai_request_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None]
    pii_erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeadCounter(Base):
    __tablename__ = "lead_counters"
    __table_args__ = ({"schema": "commerce"},)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, server_default="0")


class QuoteCounter(Base):
    __tablename__ = "quote_counters"
    __table_args__ = ({"schema": "commerce"},)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, server_default="0")


class Quote(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """PC taklifi (FSM-06). Narxli qism — revision'da; bu yerda holat, havola va muddat."""

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "number"),
        Index("ix_quotes_shop_id_lead_id", "shop_id", "lead_id"),
        Index("ix_quotes_shop_id_status_updated_at", "shop_id", "status", "updated_at"),
        Index(
            "uq_quotes_public_token_hash",
            "public_token_hash",
            unique=True,
            postgresql_where=text("public_token_hash IS NOT NULL"),
        ),
        Index("ix_quotes_expires_at", "expires_at", postgresql_where=text("status = 'SENT'")),
        ForeignKeyConstraint(
            ["shop_id", "lead_id"], ["commerce.leads.shop_id", "commerce.leads.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint(f"status IN {QUOTE_STATUSES}", name="status"),
        CheckConstraint("created_by_kind IN ('AI', 'STAFF')", name="created_by_kind"),
        CheckConstraint(f"rejected_by_kind IN {ACTOR_KINDS}", name="rejected_by_kind"),
        CheckConstraint(
            "status <> 'SENT' OR (public_token_hash IS NOT NULL AND expires_at IS NOT NULL)",
            name="sent_has_link",
        ),
        {"schema": "commerce"},
    )

    number: Mapped[int] = mapped_column(Integer)
    lead_id: Mapped[UUID]
    conversation_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    current_revision_id: Mapped[UUID | None]
    current_revision_no: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_kind: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID | None]
    public_token_hash: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by: Mapped[UUID | None]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_order_id: Mapped[UUID | None]
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by_kind: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteRevision(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Taklif versiyasi. `submitted_at` dan keyin qatorlar, jami va kurs o'zgarmaydi (trigger)."""

    __tablename__ = "quote_revisions"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "quote_id", "revision"),
        Index(
            "uq_quote_revisions_ai_request",
            "shop_id",
            "ai_request_id",
            unique=True,
            postgresql_where=text("ai_request_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["shop_id", "quote_id"], ["commerce.quotes.shop_id", "commerce.quotes.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint(
            "subtotal_uzs_minor >= 0 AND discount_uzs_minor >= 0 AND total_uzs_minor >= 0", name="totals"
        ),
        CheckConstraint("currency = 'UZS'", name="currency"),
        CheckConstraint(f"compatibility_decision IN {COMPAT_DECISIONS}", name="compatibility_decision"),
        CheckConstraint("created_by_kind IN ('AI', 'STAFF')", name="created_by_kind"),
        CheckConstraint(f"approval_mode IN {APPROVAL_MODES}", name="approval_mode"),
        {"schema": "commerce"},
    )

    quote_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    exchange_rate_id: Mapped[UUID | None]
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    subtotal_uzs_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    discount_uzs_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    total_uzs_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    currency: Mapped[str] = mapped_column(Text, server_default="UZS")
    compatibility_decision: Mapped[str | None] = mapped_column(Text)
    ruleset_version: Mapped[str | None] = mapped_column(Text)
    created_by_kind: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID | None]
    edited_by: Mapped[UUID | None]  # qatorlarni oxirgi tahrirlagan (QA 6a F1)
    submitted_by: Mapped[UUID | None]  # tekshiruvga yuborgan
    ai_turn_id: Mapped[UUID | None]
    ai_request_id: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_mode: Mapped[str | None] = mapped_column(Text)
    approval_note: Mapped[str | None] = mapped_column(Text)
    returned_note: Mapped[str | None] = mapped_column(Text)


class QuoteLine(IdMixin, ShopScopedMixin, Base):
    """Hammasi nusxa (BL-041): narx AI'dan yoki klientdan emas, katalogdan."""

    __tablename__ = "quote_lines"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "quote_revision_id", "position"),
        UniqueConstraint("shop_id", "quote_revision_id", "sku_id"),
        ForeignKeyConstraint(
            ["shop_id", "quote_revision_id"],
            ["commerce.quote_revisions.shop_id", "commerce.quote_revisions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price_minor > 0 AND unit_price_uzs_minor > 0", name="price_positive"),
        CheckConstraint("line_total_uzs_minor >= 0", name="total_non_negative"),
        CheckConstraint("currency IN ('UZS', 'USD')", name="currency"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="discount_range"),
        CheckConstraint(f"role IN {LINE_ROLES}", name="role"),
        {"schema": "commerce"},
    )

    quote_revision_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    sku_id: Mapped[UUID]
    product_id: Mapped[UUID]
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
    line_total_uzs_minor: Mapped[int] = mapped_column(BigInteger)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    spec_id: Mapped[UUID | None]
    spec_version: Mapped[int | None] = mapped_column(Integer)


class QuoteCompatibilitySnapshot(IdMixin, ShopScopedMixin, Base):
    """Moslik natijasi muzlatiladi (BL-030, 17 §7). Faqat INSERT."""

    __tablename__ = "quote_compatibility_snapshots"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "quote_revision_id", "stage"),
        ForeignKeyConstraint(
            ["shop_id", "quote_revision_id"],
            ["commerce.quote_revisions.shop_id", "commerce.quote_revisions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"stage IN {COMPAT_STAGES}", name="stage"),
        CheckConstraint(f"decision IN {COMPAT_DECISIONS}", name="decision"),
        {"schema": "commerce"},
    )

    quote_revision_id: Mapped[UUID]
    stage: Mapped[str] = mapped_column(Text)
    ruleset_version: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    can_publish: Mapped[bool] = mapped_column(Boolean)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    spec_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    estimated_power_w: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
