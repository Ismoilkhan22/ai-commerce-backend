"""platform/llm jadvallari (db/sales_ai.dbml: platform.llm_pii_refs, platform.ai_usage).

`llm_pii_refs` — redaction xaritasi: `[PHONE_1]` ↔ shifrlangan qiymat (bir suhbatda bir qiymat — bitta token,
`value_hmac` bo'yicha). `ai_usage` — har LLM chaqiruvi (xarajat chegarasi va hisobot). Ikkalasi RLS (FORCE);
`ai_usage` ning `shop_id` siz qatorlari (eval) faqat platforma kontekstida.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
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
from app.shared.db.mixins import IdMixin, ShopScopedMixin

PII_KINDS = ("PHONE", "ADDRESS", "NAME", "EMAIL", "CARD", "ID", "LOCATION")
PURPOSES = ("SALES_TURN", "SUMMARY", "CLASSIFY", "EVAL_JUDGE", "SANDBOX", "EVAL", "COMMENT_CLASSIFY")
PROVIDERS = ("anthropic", "gemini", "fake")


class LlmPiiRef(IdMixin, ShopScopedMixin, Base):
    __tablename__ = "llm_pii_refs"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "conversation_id", "token"),
        UniqueConstraint("shop_id", "conversation_id", "value_hmac"),
        Index("ix_llm_pii_refs_expires_at", "expires_at"),
        CheckConstraint(f"kind IN {PII_KINDS}", name="kind"),
        {"schema": "platform"},
    )

    conversation_id: Mapped[UUID]
    token: Mapped[str] = mapped_column(Text)  # "PHONE_1"
    kind: Mapped[str] = mapped_column(Text)
    value_enc: Mapped[str] = mapped_column(EncryptedString)  # CARD — faqat niqob (tiklanmaydi)
    value_hmac: Mapped[str] = mapped_column(Text)
    resolved_by_commerce_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiUsage(IdMixin, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        Index("ix_ai_usage_shop_id_occurred_at", "shop_id", "occurred_at"),
        Index("ix_ai_usage_purpose_occurred_at", "purpose", "occurred_at"),
        CheckConstraint(f"purpose IN {PURPOSES}", name="purpose"),
        CheckConstraint(f"provider IN {PROVIDERS}", name="provider"),
        CheckConstraint("cost_micros >= 0", name="cost_nonnegative"),
        {"schema": "platform"},
    )

    shop_id: Mapped[UUID | None]  # EVAL / EVAL_JUDGE da NULL (platforma xarajati, 6c)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[UUID | None]  # sales_ai.ai_turns.id
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger)
    # narxi noma'lum model — ehtiyotkor (eng qimmat) narx bilan hisoblangan (F-16)
    price_unknown: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
