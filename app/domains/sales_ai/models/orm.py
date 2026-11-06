"""sales_ai jadvallari (db/sales_ai.dbml; 6b qismi + 6c baholash). `prompt_versions` — keyin.

6b jadvallari shop'niki, RLS (FORCE). 6c baholash jadvallari (`eval_*`) — GLOBAL (shop_id yo'q, RLS yo'q),
faqat platforma admini API'si orqali. AI javobi matni (`reply_text_enc`) — shifrlangan va REDACT holatida
(`[PHONE_1]` tokenlari bilan); tool argumentlari va natijasi — faqat redact qilingan / ID va dalil.

DBML'dan farq (6b): `agent_settings.active_hours` (AI ishlaydigan soatlar, inbox_hours formati) va
`monthly_cost_cap_minor` (oylik chegara — tarif moduli yo'q, M06 §8) qo'shildi.
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
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.encryption import EncryptedString
from app.shared.db.mixins import IdMixin, ShopScopedMixin, VersionMixin

SCHEMA = "sales_ai"
MODES = ("OFF", "SHADOW", "SUGGEST", "AUTO")
VERSION_STATUSES = ("DRAFT", "APPROVED", "ACTIVE", "RETIRED")
KNOWLEDGE_KINDS = ("FAQ", "POLICY")
STAGES = ("IDLE", "QUALIFYING", "RECOMMENDING", "QUOTE_PENDING", "ORDER_DRAFTED", "HANDED_OFF", "STOPPED")
TURN_STATUSES = ("QUEUED", "RUNNING", "COMPLETED", "FAILED")
TURN_OUTCOMES = ("REPLY_QUEUED", "SUGGESTED", "SHADOWED", "DISCARDED", "HANDOFF", "NO_REPLY", "ERROR")
HANDOFF_REASONS = (
    "CUSTOMER_REQUEST",
    "PURCHASE_INTENT",
    "PRICE_UNKNOWN",
    "COMPATIBILITY_REVIEW",
    "DISCOUNT_REQUEST",
    "COMPLAINT",
    "WARRANTY_OR_RETURN",
    "PAYMENT_QUESTION",
    "VALIDATION_FAILED",
    "TOOL_ERROR",
    "PROVIDER_UNAVAILABLE",
    "BUDGET_EXCEEDED",
    "UNSUPPORTED_REQUEST",
    "SECURITY",
    "REFUSAL",
)
TOOL_DECISIONS = ("ALLOWED", "DENIED")
FEEDBACK_VERDICTS = ("SENT_AS_IS", "EDITED", "REJECTED", "FLAGGED")
TONES = ("FRIENDLY", "FORMAL", "CONCISE")


def _fk(columns: list[str], table: str, *, ondelete: str = "RESTRICT") -> Any:
    return ForeignKeyConstraint(
        columns, [f"{SCHEMA}.{table}.{c}" for c in ("shop_id", "id")], ondelete=ondelete
    )


class AgentSettings(VersionMixin, Base):
    """Har shopga bitta qator. Ega o'zgartiradi. Limit tugasa `mode` o'zgarmaydi — runtime speaker'ni
    PAUSED qiladi (BL-040). Chegirma haqida maydon YO'Q (DEC-110, A3)."""

    __tablename__ = "agent_settings"
    __table_args__ = (
        CheckConstraint(f"mode IN {MODES}", name="mode"),
        CheckConstraint("daily_cost_cap_minor IS NULL OR daily_cost_cap_minor >= 0", name="daily_cap"),
        CheckConstraint("monthly_cost_cap_minor IS NULL OR monthly_cost_cap_minor >= 0", name="monthly_cap"),
        {"schema": SCHEMA},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(Text, server_default="OFF")
    active_profile_version_id: Mapped[UUID | None]
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{uz,ru}'::text[]"))
    allowed_tools: Mapped[list[str]] = mapped_column(ARRAY(Text))
    handoff_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    active_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # NULL — kecha-kunduz
    daily_cost_cap_minor: Mapped[int | None] = mapped_column(BigInteger)  # USD sent
    monthly_cost_cap_minor: Mapped[int | None] = mapped_column(BigInteger)
    greeting_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    kill_switch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kill_switch_reason: Mapped[str | None] = mapped_column(Text)
    model_alias: Mapped[str | None] = mapped_column(Text)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # limit tugadi
    paused_reason: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentProfileVersion(IdMixin, ShopScopedMixin, Base):
    """O'zgarmaydi (yangi versiya — yangi qator). Promptning 2-qatlami (shop haqida)."""

    __tablename__ = "agent_profile_versions"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "version"),
        CheckConstraint(f"status IN {VERSION_STATUSES}", name="status"),
        CheckConstraint(f"tone IN {TONES}", name="tone"),
        {"schema": SCHEMA},
    )

    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    shop_display_name: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(Text, server_default="FRIENDLY")
    about_text: Mapped[str | None] = mapped_column(Text)
    extra_instructions: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeItem(IdMixin, ShopScopedMixin, Base):
    """FAQ va siyosat matnlari. APPROVED bandlar to'liq matn sifatida promptga (~6k token chegarasi, A5)."""

    __tablename__ = "knowledge_items"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        Index("ix_knowledge_items_shop_id_status_kind", "shop_id", "status", "kind"),
        _fk(["shop_id", "supersedes_id"], "knowledge_items"),
        CheckConstraint(f"kind IN {KNOWLEDGE_KINDS}", name="kind"),
        CheckConstraint(f"status IN {VERSION_STATUSES}", name="status"),
        CheckConstraint("char_length(body) <= 2000", name="body_length"),
        {"schema": SCHEMA},
    )

    kind: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    supersedes_id: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiSession(VersionMixin, Base):
    """Bitta suhbat — bitta qator: bosqich, slot'lar (PII'siz), xulosa."""

    __tablename__ = "ai_sessions"
    __table_args__ = (
        CheckConstraint(f"stage IN {STAGES}", name="stage"),
        {"schema": SCHEMA},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(Text, server_default="IDLE")
    slots: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    lead_id: Mapped[UUID | None]
    last_quote_id: Mapped[UUID | None]
    last_order_id: Mapped[UUID | None]
    summary_redacted: Mapped[str | None] = mapped_column(Text)
    summary_upto_seq: Mapped[int | None] = mapped_column(BigInteger)
    turn_count: Mapped[int] = mapped_column(Integer, server_default="0")
    handoff_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AiTurn(IdMixin, ShopScopedMixin, Base):
    """Har AI navbatining izi (14 §13). `id` = reply_id (messaging.messages.ai_reply_id)."""

    __tablename__ = "ai_turns"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "conversation_id", "trigger_message_id"),
        Index("ix_ai_turns_shop_id_created_at", "shop_id", "created_at"),
        Index("ix_ai_turns_shop_id_outcome_created_at", "shop_id", "outcome", "created_at"),
        Index("ix_ai_turns_shop_id_conversation_id", "shop_id", "conversation_id", "created_at"),
        CheckConstraint(f"mode IN {MODES}", name="mode"),
        CheckConstraint(f"status IN {TURN_STATUSES}", name="status"),
        CheckConstraint(f"outcome IS NULL OR outcome IN {TURN_OUTCOMES}", name="outcome"),
        CheckConstraint(f"handoff_reason IS NULL OR handoff_reason IN {HANDOFF_REASONS}", name="handoff"),
        CheckConstraint("rewrite_count BETWEEN 0 AND 1", name="rewrite_count"),
        {"schema": SCHEMA},
    )

    conversation_id: Mapped[UUID]
    trigger_message_id: Mapped[UUID]
    trigger_seq: Mapped[int] = mapped_column(BigInteger)
    speaker_version: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="QUEUED")
    outcome: Mapped[str | None] = mapped_column(Text)
    handoff_reason: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model_alias: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    fallback_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    prompt_version: Mapped[str | None] = mapped_column(Text)
    profile_version: Mapped[int | None] = mapped_column(Integer)
    reply_text_enc: Mapped[str | None] = mapped_column(EncryptedString)
    reply_locale: Mapped[str | None] = mapped_column(Text)
    validator_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    rewrite_count: Mapped[int] = mapped_column(Integer, server_default="0")
    tool_call_count: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_in: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_request_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    suggestion_status: Mapped[str | None] = mapped_column(Text)  # SUGGEST: PENDING | SENT | DISCARDED
    sent_message_id: Mapped[UUID | None]
    error_code: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiToolExecution(IdMixin, ShopScopedMixin, Base):
    """Tool chaqiruvi izi. Saqlash 90 kun (A10). Yozuvchi tool — idempotency_key bo'yicha bir marta."""

    __tablename__ = "ai_tool_executions"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "turn_id", "seq"),
        Index(
            "uq_ai_tool_executions_idempotency",
            "shop_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_ai_tool_executions_created_at", "created_at"),
        _fk(["shop_id", "turn_id"], "ai_turns", ondelete="CASCADE"),
        CheckConstraint(f"decision IN {TOOL_DECISIONS}", name="decision"),
        {"schema": SCHEMA},
    )

    turn_id: Mapped[UUID]
    seq: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(Text)  # ichki nom: "catalog.search"
    decision: Mapped[str] = mapped_column(Text)
    args_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_hash: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiFeedback(IdMixin, ShopScopedMixin, Base):
    """Operator bahosi. SUGGEST'da yuborish/rad etish avtomatik; FLAGGED — qo'lda (A11)."""

    __tablename__ = "ai_feedback"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "turn_id", "membership_id"),
        Index("ix_ai_feedback_shop_id_verdict_created_at", "shop_id", "verdict", "created_at"),
        _fk(["shop_id", "turn_id"], "ai_turns", ondelete="CASCADE"),
        CheckConstraint(f"verdict IN {FEEDBACK_VERDICTS}", name="verdict"),
        CheckConstraint("edit_distance_pct IS NULL OR edit_distance_pct BETWEEN 0 AND 100", name="edit_pct"),
        {"schema": SCHEMA},
    )

    turn_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    verdict: Mapped[str] = mapped_column(Text)
    error_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    sent_message_id: Mapped[UUID | None]
    edit_distance_pct: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ------------------------------------------------------------------ 6c: baholash (global, 16 §5)
EVAL_RUN_STATUSES = ("QUEUED", "RUNNING", "PASSED", "FAILED", "ERROR", "BUDGET_EXCEEDED", "CANCELLED")
EVAL_TARGETS = ("DEMO", "SHOP")
EVAL_CATEGORIES = (
    "SEARCH",
    "BUILD",
    "COMPAT",
    "STOCK",
    "DISCOUNT",
    "INJECTION",
    "PII",
    "OUT_OF_SCOPE",
    "ORDER",
    "OTHER",
)
EVAL_LANGUAGES = ("uz", "uz-Cyrl", "ru", "en")


class EvalDataset(Base):
    """Baholash to'plami. `version` — to'plam versiyasi (key bilan unikal); `revision` — tahrir hisoblagichi
    (If-Match). Muzlatilgan (`frozen`) to'plam o'zgarmaydi — yangi versiya klon bilan."""

    __tablename__ = "eval_datasets"
    __table_args__ = (
        UniqueConstraint("key", "version"),
        CheckConstraint("rows >= 0", name="rows"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    checksum: Mapped[str] = mapped_column(Text)
    rows: Mapped[int] = mapped_column(Integer, server_default="0")
    frozen: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(BigInteger, default=1)
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __mapper_args__ = {"version_id_col": revision}  # noqa: RUF012


class EvalCase(Base):
    """To'plamdagi bitta holat: xaridor xabari (va ixtiyoriy oldingi tarix) + tuzilgan kutilmalar."""

    __tablename__ = "eval_cases"
    __table_args__ = (
        UniqueConstraint("dataset_id", "case_key"),
        Index("ix_eval_cases_dataset_id_ordinal", "dataset_id", "ordinal"),
        CheckConstraint(f"category IN {EVAL_CATEGORIES}", name="category"),
        CheckConstraint(f"language IN {EVAL_LANGUAGES}", name="language"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.eval_datasets.id", ondelete="CASCADE"))
    case_key: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    expectations: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    """Bitta yugurish: to'plam × provayder/model × nishon shop (katalog). PASSED — nol toqat buzilmasa
    (va `min_pass_rate` berilgan bo'lsa, o'tish ulushi undan past bo'lmasa)."""

    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_dataset_id_created_at", "dataset_id", "created_at"),
        Index("ix_eval_runs_status", "status"),
        Index("ix_eval_runs_bakeoff_id", "bakeoff_id"),
        CheckConstraint(f"status IN {EVAL_RUN_STATUSES}", name="status"),
        CheckConstraint(f"target_kind IN {EVAL_TARGETS}", name="target_kind"),
        CheckConstraint("cost_cap_micros > 0", name="cost_cap"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.eval_datasets.id", ondelete="RESTRICT"))
    dataset_checksum: Mapped[str] = mapped_column(Text)
    bakeoff_id: Mapped[UUID | None]
    label: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model_alias: Mapped[str] = mapped_column(Text, server_default="seller")
    model_id: Mapped[str] = mapped_column(Text)
    models_used: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    ruleset_version: Mapped[str | None] = mapped_column(Text)
    git_sha: Mapped[str] = mapped_column(Text)
    target_kind: Mapped[str] = mapped_column(Text)
    target_shop_id: Mapped[UUID]
    judge_provider: Mapped[str | None] = mapped_column(Text)
    judge_model_id: Mapped[str | None] = mapped_column(Text)
    case_keys: Mapped[list[str] | None] = mapped_column(ARRAY(Text))  # bo'sh — hamma holatlar
    min_pass_rate: Mapped[int | None] = mapped_column(Integer)  # foiz
    status: Mapped[str] = mapped_column(Text, server_default="QUEUED")
    total_cases: Mapped[int] = mapped_column(Integer, server_default="0")
    done_cases: Mapped[int] = mapped_column(Integer, server_default="0")
    passed_cases: Mapped[int] = mapped_column(Integer, server_default="0")
    zero_tolerance_violations: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_cap_micros: Mapped[int] = mapped_column(BigInteger)
    cost_micros: Mapped[int] = mapped_column(BigInteger, server_default="0")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalResult(Base):
    """Bitta holat natijasi. Javob matni — redact holatida (sintetik to'plam); tool izi (`transcript`) —
    faqat muvaffaqiyatsiz holatda (DBML: `transcript_file_id` o'rniga JSONB, 6c qarori)."""

    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.eval_runs.id", ondelete="CASCADE"))
    case_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.eval_cases.id", ondelete="RESTRICT"))
    case_key: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str] = mapped_column(Text)  # REPLY | HANDOFF | ERROR
    handoff_reason: Mapped[str | None] = mapped_column(Text)
    failure_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    zero_tolerance_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    validator_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    tools_called: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    reply_text: Mapped[str | None] = mapped_column(Text)
    judge_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    judge: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_in: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, server_default="0")
    judge_cost_micros: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
