"""6c API sxemalari: baholash (platforma admini) va "AI sifati" (shop). Pul — USD micros (×10⁶).

Natijada xaridor ma'lumoti yo'q: to'plam sintetik, javob matni redact holatida (`[PHONE_1]`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.sales_ai.eval.scoring import Expectations
from app.domains.sales_ai.schemas import AutoReadiness
from app.shared.text import CleanText

Category = Literal[
    "SEARCH", "BUILD", "COMPAT", "STOCK", "DISCOUNT", "INJECTION", "PII", "OUT_OF_SCOPE", "ORDER", "OTHER"
]
CaseLanguage = Literal["uz", "uz-Cyrl", "ru", "en"]
Provider = Literal["fake", "gemini", "anthropic"]
RunStatus = Literal["QUEUED", "RUNNING", "PASSED", "FAILED", "ERROR", "BUDGET_EXCEEDED", "CANCELLED"]
TargetKind = Literal["DEMO", "SHOP"]
Change = Literal["REGRESSION", "IMPROVEMENT", "BOTH_PASS", "BOTH_FAIL", "ONLY_BASE", "ONLY_CANDIDATE"]

KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
MODEL_PATTERN = r"^[a-z0-9][a-z0-9.\-]{1,80}$"
MAX_CASES = 500
DEFAULT_COST_CAP_MICROS = 2_000_000  # $2 — 40 holat Sonnet bilan ~$0.5–1
MAX_COST_CAP_MICROS = 100_000_000  # $100


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ to'plamlar
class HistoryTurn(_In):
    role: Literal["customer", "assistant"]
    text: CleanText = Field(min_length=1, max_length=2000)


class CaseIn(_In):
    case_key: str = Field(pattern=KEY_PATTERN)
    category: Category
    language: CaseLanguage
    message: CleanText = Field(min_length=1, max_length=2000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=10)
    expectations: Expectations = Field(default_factory=Expectations)
    notes: CleanText | None = Field(default=None, max_length=500)


class CaseOut(BaseModel):
    id: UUID
    case_key: str
    ordinal: int
    category: Category
    language: CaseLanguage
    message: str
    history: list[HistoryTurn]
    expectations: Expectations
    notes: str | None


def _unique_keys(cases: list[CaseIn] | None) -> list[CaseIn] | None:
    if cases is not None:
        keys = [c.case_key for c in cases]
        if len(keys) != len(set(keys)):
            raise ValueError("case_key must be unique within a dataset")
    return cases


class DatasetIn(_In):
    key: str = Field(pattern=KEY_PATTERN)
    name: CleanText = Field(min_length=1, max_length=120)
    description: CleanText | None = Field(default=None, max_length=2000)
    manifest: dict[str, Any] = Field(default_factory=dict, max_length=20)
    cases: list[CaseIn] = Field(min_length=1, max_length=MAX_CASES)

    _check = field_validator("cases")(_unique_keys)


class DatasetPatch(_In):
    """Muzlatilmagan to'plam: nom, tavsif, manifest yoki holatlar (to'liq almashtiriladi). `frozen: true` —
    bir tomonlama (golden to'plam muzlatiladi, keyin faqat klon)."""

    name: CleanText | None = Field(default=None, min_length=1, max_length=120)
    description: CleanText | None = Field(default=None, max_length=2000)
    manifest: dict[str, Any] | None = Field(default=None, max_length=20)
    cases: list[CaseIn] | None = Field(default=None, min_length=1, max_length=MAX_CASES)
    frozen: Literal[True] | None = None

    _check = field_validator("cases")(_unique_keys)


class DatasetOut(BaseModel):
    id: UUID
    key: str
    version: int
    name: str
    description: str | None
    manifest: dict[str, Any]
    checksum: str
    rows: int
    frozen: bool
    archived: bool
    revision: int
    categories: dict[str, int]
    languages: dict[str, int]
    runs: int
    created_at: datetime
    updated_at: datetime


class DatasetDetail(DatasetOut):
    cases: list[CaseOut]


class DatasetList(BaseModel):
    items: list[DatasetOut]


# ------------------------------------------------------------------ yugurishlar
class RunTarget(_In):
    """`DEMO` — platforma demo shopi (katalog snapshot'i: `techpc`); `SHOP` — tanlangan faol shop katalogi
    (faqat o'qish, hech narsa yozilmaydi)."""

    kind: TargetKind = "DEMO"
    shop_id: UUID | None = None

    @model_validator(mode="after")
    def _shop(self) -> RunTarget:
        if (self.kind == "SHOP") != (self.shop_id is not None):
            raise ValueError("shop_id is required for SHOP target and forbidden for DEMO")
        return self


class ModelChoice(_In):
    provider: Provider
    model: str | None = Field(default=None, pattern=MODEL_PATTERN)  # bo'sh — provayderning `seller` modeli


class _RunOptions(_In):
    dataset_id: UUID
    target: RunTarget = Field(default_factory=RunTarget)
    judge: ModelChoice | None = None  # bo'sh — judge'siz (faqat deterministik ball)
    cost_cap_micros: int = Field(default=DEFAULT_COST_CAP_MICROS, ge=1_000, le=MAX_COST_CAP_MICROS)
    label: CleanText | None = Field(default=None, max_length=80)
    case_keys: list[str] | None = Field(default=None, min_length=1, max_length=MAX_CASES)
    min_pass_rate: int | None = Field(default=None, ge=0, le=100)


class RunIn(_RunOptions):
    provider: Provider
    model: str | None = Field(default=None, pattern=MODEL_PATTERN)


class BakeoffIn(_RunOptions):
    """Bir xil to'plam, nishon va judge — ikki provayder/model (A15). `cost_cap_micros` — har yugurishga."""

    candidates: list[ModelChoice] = Field(min_length=2, max_length=2)


class RunOut(BaseModel):
    id: UUID
    dataset_id: UUID
    dataset_key: str
    dataset_version: int
    dataset_checksum: str
    bakeoff_id: UUID | None
    label: str | None
    status: RunStatus
    provider: str
    model_id: str
    models_used: list[str]
    prompt_version: str
    ruleset_version: str | None
    git_sha: str
    target_kind: TargetKind
    target_shop_id: UUID
    judge_provider: str | None
    judge_model_id: str | None
    total_cases: int
    done_cases: int
    passed_cases: int
    pass_rate: float | None
    zero_tolerance_violations: int
    cost_cap_micros: int
    cost_micros: int
    min_pass_rate: int | None
    metrics: dict[str, Any]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunList(BaseModel):
    items: list[RunOut]


class BakeoffOut(BaseModel):
    bakeoff_id: UUID
    runs: list[RunOut]


class ResultOut(BaseModel):
    case_key: str
    ordinal: int
    category: Category
    language: CaseLanguage
    passed: bool
    outcome: Literal["REPLY", "HANDOFF", "ERROR"]
    handoff_reason: str | None
    failure_codes: list[str]
    zero_tolerance_codes: list[str]
    validator_codes: list[str]
    tools_called: list[str]
    reply_text: str | None
    judge_score: Decimal | None
    judge: dict[str, Any] | None
    transcript: list[dict[str, Any]] | None
    error_code: str | None
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_micros: int
    judge_cost_micros: int


class ResultList(BaseModel):
    items: list[ResultOut]


class Delta(BaseModel):
    base: float | None
    candidate: float | None
    delta: float | None


class CaseSide(BaseModel):
    passed: bool
    failure_codes: list[str]
    handoff_reason: str | None
    tools_called: list[str]
    judge_score: Decimal | None
    latency_ms: int
    cost_micros: int


class CaseDiff(BaseModel):
    case_key: str
    category: str
    language: str
    change: Change
    base: CaseSide | None
    candidate: CaseSide | None
    judge_delta: float | None


class CompareOut(BaseModel):
    base: RunOut
    candidate: RunOut
    aggregate: dict[str, Delta]
    by_category: dict[str, Delta]
    by_language: dict[str, Delta]
    counts: dict[str, int]
    cases: list[CaseDiff]


# ------------------------------------------------------------------ AI sifati (production)
class FeedbackStats(BaseModel):
    sent_as_is: int = 0
    edited: int = 0
    rejected: int = 0
    flagged: int = 0
    total: int = 0
    approval_rate: float | None = None  # tahrirsiz yuborilgan ulush (SENT_AS_IS / ko'rib chiqilgan)
    avg_edit_pct: float | None = None


class QualityDay(BaseModel):
    date: date
    conversations: int
    turns: int
    replies: int
    suggestions: int
    handoffs: int
    validator_hits: int
    errors: int
    cost_micros: int
    feedback: FeedbackStats


class QualityTotals(BaseModel):
    conversations: int
    turns: int
    replies: int
    suggestions: int
    shadowed: int
    handoffs: int
    handoff_rate: float | None
    validator_hits: int
    validator_hit_rate: float | None
    rewrites: int
    errors: int
    cost_micros: int
    cost_per_conversation_micros: int | None
    avg_latency_ms: int | None
    feedback: FeedbackStats


class QualityOut(BaseModel):
    shop_id: UUID
    timezone: str
    date_from: date
    date_to: date
    days: int
    totals: QualityTotals
    daily: list[QualityDay]
    handoff_reasons: dict[str, int]
    validator_codes: dict[str, int]
    error_tags: dict[str, int]
    auto_readiness: AutoReadiness
