"""sales_ai panel API sxemalari (6b). Pul: xarajat — USD micros (×10⁶), limit — USD sent (`*_minor`).

Navbat izida xaridorning shaxsiy ma'lumoti YO'Q: matn redact holatida (`[PHONE_1]`), tool argumentlari va
natijasi — faqat ID, son, kod.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.shared.text import CleanText

AiMode = Literal["OFF", "SHADOW", "SUGGEST", "AUTO"]
Tone = Literal["FRIENDLY", "FORMAL", "CONCISE"]
Language = Literal["uz", "ru", "en"]
ToolName = Literal[
    "catalog_search",
    "catalog_get_sku_details",
    "commerce_get_stock",
    "catalog_check_compatibility",
    "commerce_capture_lead",
    "commerce_prepare_quote_draft",
    "commerce_create_order_draft",
    "messaging_request_handoff",
]
HandoffTopic = Literal["COMPLAINT", "WARRANTY_OR_RETURN", "DISCOUNT_REQUEST"]
KnowledgeKind = Literal["FAQ", "POLICY"]
KnowledgeStatus = Literal["DRAFT", "APPROVED", "RETIRED"]
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ sozlamalar
class HandoffRules(_In):
    """`always_handoff_on` bo'sh bo'lishi mumkin — DISCOUNT_REQUEST baribir har doim qo'shiladi
    (qulflangan)."""

    always_handoff_on: list[HandoffTopic] = Field(max_length=3)
    max_ai_turns_before_offer_human: StrictInt = Field(ge=0, le=50, description="0 — cheklanmagan")

    @field_validator("always_handoff_on")
    @classmethod
    def _locked(cls, value: list[str]) -> list[str]:
        return sorted({*value, "DISCOUNT_REQUEST"})


class ActiveHours(_In):
    days: list[StrictInt] = Field(min_length=1, max_length=7, description="1 = dushanba … 7 = yakshanba")
    start: str = Field(pattern=HHMM)
    end: str = Field(pattern=HHMM)

    @field_validator("days")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in value):
            raise ValueError("days must be 1..7")
        return sorted(set(value))

    @model_validator(mode="after")
    def _range(self) -> ActiveHours:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class AgentProfileIn(_In):
    shop_display_name: str = Field(min_length=1, max_length=80)
    tone: Tone = "FRIENDLY"
    about_text: str | None = Field(default=None, max_length=1000)
    extra_instructions: str | None = Field(default=None, max_length=1000)


class AgentProfileOut(BaseModel):
    version: int
    shop_display_name: str
    tone: Tone
    about_text: str | None
    extra_instructions: str | None


class ReadinessCheck(BaseModel):
    code: Literal[
        "PROVIDER_CONFIGURED", "PROFILE_SET", "KNOWLEDGE_PUBLISHED", "SUGGEST_REVIEWED", "SUGGEST_ACCEPTANCE"
    ]
    ok: bool
    value: int | None = None  # masalan: ko'rib chiqilgan takliflar soni, tahrirsiz ulush %
    required: int | None = None


class AutoReadiness(BaseModel):
    """AUTO tavsiyasi (M06 §9): maslahat — rejimni ega tanlaydi; faqat provayder sozlanmagan bo'lsa
    yoqilmaydi."""

    ready: bool
    checks: list[ReadinessCheck]


class AiSettingsOut(BaseModel):
    mode: AiMode
    languages: list[Language]
    allowed_tools: list[ToolName]
    handoff_rules: HandoffRules
    active_hours: ActiveHours | None
    daily_cost_cap_minor: int | None
    monthly_cost_cap_minor: int | None
    cost_currency: Literal["USD"] = "USD"
    greeting_enabled: bool
    kill_switch_active: bool
    kill_switch_reason: str | None
    paused_until: datetime | None
    paused_reason: str | None
    profile: AgentProfileOut | None
    provider: str
    provider_configured: bool
    auto_readiness: AutoReadiness
    version: int
    updated_at: datetime


class AiSettingsPatch(_In):
    """Faqat yuborilgan maydonlar o'zgaradi. `null` — tozalash (ish vaqti, limitlar)."""

    mode: AiMode | None = None
    languages: list[Language] | None = Field(default=None, min_length=1, max_length=3)
    allowed_tools: list[ToolName] | None = Field(
        default=None, max_length=8, description="Bo'sh — tool'larsiz (operatorga uzatish har doim qoladi)"
    )
    handoff_rules: HandoffRules | None = None
    active_hours: ActiveHours | None = None
    daily_cost_cap_minor: StrictInt | None = Field(default=None, ge=0, le=100_000_00)
    monthly_cost_cap_minor: StrictInt | None = Field(default=None, ge=0, le=1_000_000_00)

    @field_validator("allowed_tools", "languages")
    @classmethod
    def _unique(cls, value: list[str] | None) -> list[str] | None:
        return sorted(set(value), key=value.index) if value is not None else None

    greeting_enabled: bool | None = None
    kill_switch: bool | None = Field(default=None, description="true — AI darhol to'xtaydi")
    kill_switch_reason: str | None = Field(default=None, max_length=200)
    profile: AgentProfileIn | None = None


class AiStatusOut(BaseModel):
    provider: str
    provider_configured: bool
    model: str | None
    mode: AiMode
    effective_mode: AiMode  # hozir amalda: AI to'xtagan bo'lsa (sabab `pause_reason`) — OFF
    pause_reason: (
        Literal["OFF", "KILL_SWITCH", "OUTSIDE_HOURS", "BUDGET_EXCEEDED", "NOT_CONFIGURED", "SHOP_NOT_ACTIVE"]
        | None
    )
    paused_until: datetime | None
    today_conversations: int
    today_replies: int
    today_suggestions: int
    today_handoffs: int
    today_cost_micros: int
    month_cost_micros: int
    daily_cost_cap_minor: int | None
    monthly_cost_cap_minor: int | None
    price_unknown: bool = False  # bugun narxi noma'lum model ishlatilgan — xarajat ehtiyotkor narxda (F-16)
    sandbox_today_cost_micros: int = 0  # sinov oynasi — jonli limitga kirmaydi
    sandbox_daily_cap_micros: int = 0


# ------------------------------------------------------------------ bilim bazasi
class KnowledgeIn(_In):
    kind: KnowledgeKind
    locale: Language
    title: CleanText = Field(min_length=1, max_length=120)
    body: CleanText = Field(min_length=1, max_length=2000)


class KnowledgePatch(_In):
    kind: KnowledgeKind | None = None
    locale: Language | None = None
    title: CleanText | None = Field(default=None, min_length=1, max_length=120)
    body: CleanText | None = Field(default=None, min_length=1, max_length=2000)


class KnowledgeOut(BaseModel):
    id: UUID
    kind: KnowledgeKind
    locale: Language
    title: str
    body: str
    status: KnowledgeStatus
    version: int
    approved_at: datetime | None
    created_at: datetime


class KnowledgeList(BaseModel):
    items: list[KnowledgeOut]
    published_chars: int  # promptga kiradigan (APPROVED) matn hajmi
    limit_chars: int


# ------------------------------------------------------------------ navbat izi
class ToolCallOut(BaseModel):
    seq: int
    tool: str  # ichki nom: "catalog.search"
    decision: Literal["ALLOWED", "DENIED"]
    input: dict[str, Any]  # redact qilingan
    output: dict[str, Any] | None  # faqat ID va dalil
    error_code: str | None
    latency_ms: int | None


class DraftLinkOut(BaseModel):
    kind: Literal["LEAD", "QUOTE", "ORDER"]
    id: UUID
    label: str


class TurnOut(BaseModel):
    id: UUID
    conversation_id: UUID | None
    mode: AiMode
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    outcome: str | None
    handoff_reason: str | None
    reply_text: str | None  # redact holatida
    reply_locale: str | None
    suggestion_status: Literal["PENDING", "SENT", "DISCARDED"] | None
    provider: str | None
    model: str | None
    fallback_used: bool
    prompt_version: str | None
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cost_micros: int
    latency_ms: int | None
    validator_codes: list[str]
    rewrite_count: int
    error_code: str | None
    tool_calls: list[ToolCallOut]
    drafts: list[DraftLinkOut]
    created_at: datetime | None


class TurnList(BaseModel):
    items: list[TurnOut]


# ------------------------------------------------------------------ sinov oynasi
class SandboxIn(_In):
    session_id: UUID | None = None
    text: CleanText = Field(min_length=1, max_length=2000)


class SandboxOut(BaseModel):
    session_id: UUID
    reply_text: str | None
    outcome: str
    handoff_reason: str | None
    turn: TurnOut


# ------------------------------------------------------------------ takliflar (SUGGEST)
class SuggestionOut(BaseModel):
    reply_id: UUID  # = ai_turns.id
    conversation_id: UUID
    body: str  # xaridorning ma'lumoti tiklangan holda (operator ko'radi)
    created_at: datetime
    stale: bool  # suhbat boshqa bosqichga o'tgan — yuborib bo'lmaydi
    handoff_reason: str | None
    validator_codes: list[str]


class SuggestionList(BaseModel):
    items: list[SuggestionOut]


class SuggestionSendIn(_In):
    body: CleanText | None = Field(
        default=None, min_length=1, max_length=4000, description="Tahrirlangan matn"
    )


class SuggestionSentOut(BaseModel):
    reply_id: UUID
    message_id: UUID
    verdict: Literal["SENT_AS_IS", "EDITED"]


DiscardTag = Literal[
    "WRONG_INFO", "WRONG_FACT", "WRONG_PRODUCT", "MISSED_QUESTION", "TONE", "LANGUAGE", "TOO_LONG", "OTHER"
]


class SuggestionDiscardIn(_In):
    error_tags: list[DiscardTag] = Field(default_factory=list, max_length=5)
    comment: CleanText | None = Field(default=None, max_length=500)
