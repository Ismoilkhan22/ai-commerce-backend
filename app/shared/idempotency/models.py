"""platform.idempotency_keys (07 §4.1, 12 §9). Kod `shared` da, jadval `platform` schemasida."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint("request_hash LIKE 'h1:%'", name="request_hash_keyed"),  # faqat HMAC (QA M04 F2)
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)  # shopsiz amallar — NIL_SHOP_ID
    operation: Mapped[str] = mapped_column(Text, primary_key=True)  # "order.confirm"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
