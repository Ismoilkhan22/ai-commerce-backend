"""support.cases, case_notes, case_attachments, case_counters — db/support.dbml (7b, DEC-145).

Xaridor ismi va telefoni — `cases` dagi alohida ustunlarda; telefon shifrlangan (`EncryptedString`, 26 §4),
qidirish — kalitli xesh. Bu ustunlar log, audit diff va outbox'ga tushmaydi. Murojaat o'chirilmaydi.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.encryption import EncryptedString
from app.shared.db.mixins import IdMixin, ShopScopedMixin, VersionMixin

CASE_TYPES = ("WARRANTY", "RETURN")
CASE_STATUSES = ("NEW", "IN_REVIEW", "APPROVED", "REJECTED", "IN_SERVICE", "RESOLVED", "CLOSED")
CASE_SOURCES = ("ORDER_LINE", "QUICK_SALE_LINE", "EXTERNAL")
CASE_RESOLUTIONS = ("REPAIR", "REPLACE", "REFUND")
CASE_OUTCOMES = ("REPAIRED", "REPLACED", "RETURNED")
REJECT_REASONS = (
    "WARRANTY_EXPIRED",
    "NO_DEFECT_FOUND",
    "USER_DAMAGE",
    "NOT_OUR_SALE",
    "RETURN_NOT_ALLOWED",
    "OTHER",
)
NOTE_KINDS = ("NOTE", "DIAGNOSIS", "CUSTOMER_CONTACT")
CREATED_VIA = ("STAFF_PANEL", "CONVERSATION", "ORDER_PAGE")
CUSTOMER_LOCALES = ("uz", "ru", "en")
OPEN_STATUSES = ("NEW", "IN_REVIEW", "APPROVED", "IN_SERVICE", "RESOLVED")  # hali yopilmagan


class CaseCounter(Base):
    """Shop ichida ketma-ket murojaat raqami ("K-12"). Yaratishda +1 — rollback bo'lsa qaytadi."""

    __tablename__ = "case_counters"
    __table_args__ = ({"schema": "support"},)

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, server_default="0")


class SupportCase(IdMixin, ShopScopedMixin, VersionMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "number"),
        Index("ix_cases_shop_id_status_created_at", "shop_id", "status", "created_at"),
        Index("ix_cases_shop_id_order_line_id", "shop_id", "order_line_id"),
        Index("ix_cases_shop_id_quick_sale_line_id", "shop_id", "quick_sale_line_id"),
        Index("ix_cases_shop_id_contact_phone_hmac", "shop_id", "contact_phone_hmac"),
        Index("ix_cases_shop_id_branch_id_status", "shop_id", "branch_id", "status"),
        Index(
            "ix_cases_shop_id_assigned_membership_id_status", "shop_id", "assigned_membership_id", "status"
        ),
        # 7 kunlik avtomatik yopish ishi faqat RESOLVED'larni qidiradi
        Index(
            "ix_cases_resolved_at",
            "shop_id",
            "resolved_at",
            postgresql_where=text("status = 'RESOLVED'"),
        ),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint(f"type IN {CASE_TYPES}", name="type"),
        CheckConstraint(f"status IN {CASE_STATUSES}", name="status"),
        CheckConstraint(f"source IN {CASE_SOURCES}", name="source"),
        CheckConstraint(f"created_via IN {CREATED_VIA}", name="created_via"),
        CheckConstraint(f"resolution IS NULL OR resolution IN {CASE_RESOLUTIONS}", name="resolution"),
        CheckConstraint(f"outcome IS NULL OR outcome IN {CASE_OUTCOMES}", name="outcome"),
        CheckConstraint(f"reject_reason IS NULL OR reject_reason IN {REJECT_REASONS}", name="reject_reason"),
        CheckConstraint(f"customer_locale IN {CUSTOMER_LOCALES}", name="customer_locale"),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint(
            "refund_amount_minor IS NULL OR refund_amount_minor >= 0", name="refund_non_negative"
        ),
        CheckConstraint("warranty_months IS NULL OR warranty_months >= 0", name="warranty_months_range"),
        CheckConstraint("char_length(problem_description) BETWEEN 3 AND 2000", name="problem_length"),
        CheckConstraint(
            "(source = 'ORDER_LINE' AND order_id IS NOT NULL AND order_line_id IS NOT NULL "
            "AND quick_sale_id IS NULL AND quick_sale_line_id IS NULL) "
            "OR (source = 'QUICK_SALE_LINE' AND quick_sale_id IS NOT NULL AND quick_sale_line_id IS NOT NULL "
            "AND order_id IS NULL AND order_line_id IS NULL) "
            "OR (source = 'EXTERNAL' AND order_id IS NULL AND order_line_id IS NULL "
            "AND quick_sale_id IS NULL "
            "AND quick_sale_line_id IS NULL AND external_sale_ref IS NOT NULL)",
            name="source_refs",
        ),
        CheckConstraint(
            "status <> 'REJECTED' OR (reject_reason IS NOT NULL AND decided_by IS NOT NULL)",
            name="rejected_has_reason",
        ),
        CheckConstraint(
            "status NOT IN ('APPROVED', 'IN_SERVICE', 'RESOLVED') OR resolution IS NOT NULL",
            name="approved_has_resolution",
        ),
        CheckConstraint(
            "status NOT IN ('RESOLVED', 'CLOSED') OR resolution IS NULL OR outcome IS NOT NULL",
            name="resolved_has_outcome",
        ),
        CheckConstraint(
            "outcome IS NULL OR (resolution = 'REPAIR' AND outcome = 'REPAIRED') "
            "OR (resolution = 'REPLACE' AND outcome = 'REPLACED') "
            "OR (resolution = 'REFUND' AND outcome = 'RETURNED')",
            name="outcome_matches_resolution",
        ),
        CheckConstraint(
            "status NOT IN ('IN_SERVICE', 'RESOLVED', 'CLOSED') OR item_received_at IS NOT NULL",
            name="service_needs_item",
        ),
        CheckConstraint(
            "warranty_override_reason IS NULL OR (warranty_override_by IS NOT NULL "
            "AND char_length(warranty_override_reason) >= 3)",
            name="override_needs_actor",
        ),
        {"schema": "support"},
    )

    number: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(Text, server_default="WARRANTY")
    status: Mapped[str] = mapped_column(Text, server_default="NEW")
    created_via: Mapped[str] = mapped_column(Text)

    source: Mapped[str] = mapped_column(Text)
    order_id: Mapped[UUID | None]  # commerce.orders.id — FK'siz (boshqa schema)
    order_line_id: Mapped[UUID | None]
    quick_sale_id: Mapped[UUID | None]
    quick_sale_line_id: Mapped[UUID | None]
    external_sale_ref: Mapped[str | None] = mapped_column(Text)

    branch_id: Mapped[UUID]  # platform.branches.id — murojaat shu filialda yuritiladi, karantin ham shu yerda
    sku_id: Mapped[UUID | None]
    product_id: Mapped[UUID | None]
    title_snapshot: Mapped[str] = mapped_column(Text)
    sku_code_snapshot: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[int] = mapped_column(Integer, server_default="1")
    serial_number: Mapped[str | None] = mapped_column(Text)

    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    warranty_months: Mapped[int | None] = mapped_column(Integer)  # sotuv qatoridagi nusxa (BL-057)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    within_warranty: Mapped[bool] = mapped_column(Boolean)
    warranty_override_reason: Mapped[str | None] = mapped_column(Text)  # muddat tugagan, menejer ochdi
    warranty_override_by: Mapped[UUID | None]

    problem_description: Mapped[str] = mapped_column(Text)

    customer_name: Mapped[str | None] = mapped_column(Text)  # PII
    contact_phone_enc: Mapped[str | None] = mapped_column(EncryptedString)  # PII, shifrlangan
    contact_phone_hmac: Mapped[str | None] = mapped_column(Text)
    customer_identity_id: Mapped[UUID | None]  # messaging.customer_identities.id
    conversation_id: Mapped[UUID | None]  # messaging.conversations.id — NULL bo'lsa xaridorga xabar yo'q
    customer_locale: Mapped[str] = mapped_column(Text, server_default="uz")
    pii_erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    item_received_by: Mapped[UUID | None]
    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnosed_by: Mapped[UUID | None]

    resolution: Mapped[str | None] = mapped_column(Text)
    replacement_sku_id: Mapped[UUID | None]
    decided_by: Mapped[UUID | None]
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)

    service_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    refund_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None]
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[UUID | None]  # NULL — 7 kundan keyin tizim yopdi

    opened_by: Mapped[UUID]  # platform.memberships.id
    assigned_membership_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CaseNote(IdMixin, ShopScopedMixin, Base):
    """Ichki izoh va diagnostika. Faqat qo'shiladi; matnda PII bo'lishi mumkin — anonimlashtiriladi."""

    __tablename__ = "case_notes"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_case_notes_shop_id_case_id_created_at", "shop_id", "case_id", "created_at"),
        ForeignKeyConstraint(
            ["shop_id", "case_id"], ["support.cases.shop_id", "support.cases.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"kind IN {NOTE_KINDS}", name="kind"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="body_length"),
        {"schema": "support"},
    )

    case_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text, server_default="NOTE")
    body: Mapped[str] = mapped_column(Text)
    author_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseAttachment(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "case_attachments"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "case_id", "file_id"),
        Index("ix_case_attachments_shop_id_case_id", "shop_id", "case_id"),
        ForeignKeyConstraint(
            ["shop_id", "case_id"], ["support.cases.shop_id", "support.cases.id"], ondelete="RESTRICT"
        ),
        {"schema": "support"},
    )

    case_id: Mapped[UUID]
    file_id: Mapped[UUID]  # platform.stored_files.id — SUPPORT_EVIDENCE, yopiq
    caption: Mapped[str | None] = mapped_column(Text)
    source_message_id: Mapped[UUID | None]  # messaging.messages.id
    added_by: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
