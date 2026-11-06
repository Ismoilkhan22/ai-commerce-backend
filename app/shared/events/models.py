"""`outbox_events` va `consumer_receipts` — har domen schemasida bir xil ikki jadval (db/jobs.md §1–2).

Jadvallar shu yerda (ORM klassi emas, Core `Table`): biznes kodi ularga faqat `write_outbox()` va
`app.workers` orqali tegadi. Yangi schema outbox oladigan bo'lsa — `OUTBOX_SCHEMAS` ga qo'shiladi va o'sha
schemaning migratsiyasi jadvallarni yaratadi (`app.db.models` shu modulni har schema uchun yuklaydi).

RLS yo'q: worker shoplararo poll qiladi, ichida PII yo'q (05 §3.1).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.shared.db.base import Base

# 5-modul: shu beshtasi (messaging — 5b); sales_ai/support/reporting — o'z modullari bilan
OUTBOX_SCHEMAS: tuple[str, ...] = ("platform", "catalog", "commerce", "storefront", "messaging")
STATUSES = ("PENDING", "PUBLISHED", "DEAD")


def _outbox(schema: str) -> Table:
    return Table(
        "outbox_events",
        Base.metadata,
        Column("event_id", Uuid(), nullable=False),
        Column("event_type", Text(), nullable=False),
        Column("shop_id", Uuid(), nullable=True),
        Column("aggregate_type", Text(), nullable=False),
        Column("aggregate_id", Uuid(), nullable=False),
        Column("aggregate_version", BigInteger(), nullable=False),
        Column("envelope", JSONB(), nullable=False),
        Column("status", Text(), server_default="PENDING", nullable=False),
        Column("attempts", Integer(), server_default="0", nullable=False),
        Column("next_attempt_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        Column("last_error", Text(), nullable=True),
        Column("occurred_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        Column("published_at", DateTime(timezone=True), nullable=True),
        PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
        CheckConstraint("status IN ('PENDING', 'PUBLISHED', 'DEAD')", name="status"),
        # outbox_worker: FOR UPDATE SKIP LOCKED bilan navbatdagilar (05 §5)
        Index(
            "ix_outbox_events_pending",
            "next_attempt_at",
            "event_id",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id", "aggregate_version"),
        # 14 kunlik tozalash va rekonsilyatsiya
        Index("ix_outbox_events_published", "published_at", postgresql_where=text("status = 'PUBLISHED'")),
        schema=schema,
    )


def _receipts(schema: str) -> Table:
    return Table(
        "consumer_receipts",
        Base.metadata,
        Column("consumer", Text(), nullable=False),
        Column("event_id", Uuid(), nullable=False),
        Column("applied_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        PrimaryKeyConstraint("consumer", "event_id", name="pk_consumer_receipts"),
        Index("ix_consumer_receipts_applied_at", "applied_at"),
        schema=schema,
    )


OUTBOX_TABLES: dict[str, Table] = {schema: _outbox(schema) for schema in OUTBOX_SCHEMAS}
RECEIPT_TABLES: dict[str, Table] = {schema: _receipts(schema) for schema in OUTBOX_SCHEMAS}


def outbox_table(schema: str) -> Table:
    try:
        return OUTBOX_TABLES[schema]
    except KeyError as exc:
        raise ValueError(f"{schema!r} schemasida outbox yo'q (OUTBOX_SCHEMAS)") from exc


def receipts_table(schema: str) -> Table:
    try:
        return RECEIPT_TABLES[schema]
    except KeyError as exc:
        raise ValueError(f"{schema!r} schemasida consumer_receipts yo'q (OUTBOX_SCHEMAS)") from exc
