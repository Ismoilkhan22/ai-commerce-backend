"""LlmProvider port va neytral turlar (ai/M06-architecture.md §4).

Model faqat shu turlarni ko'radi: matn, tool chaqiruvi, tool natijasi. Provayderning o'z bloklari (Claude
"thinking", Gemini "thought signature") navbat ichida `provider_state` da o'zgartirilmasdan qaytariladi —
ular bazaga yozilmaydi va keyingi navbatga o'tmaydi (M06 §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ProviderName = Literal["anthropic", "gemini", "fake"]
ModelAlias = Literal["seller", "light", "judge"]
Effort = Literal["low", "medium", "high"]
StopReason = Literal["END", "TOOL_CALLS", "MAX_TOKENS", "REFUSAL", "ERROR"]
Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str  # API nomi (snake_case): "catalog_search"
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str  # Gemini natijani nom bo'yicha bog'laydi
    content: str  # JSON matn — model uchun ma'lumot, ko'rsatma emas (M06 §6)
    is_error: bool = False


Part = TextPart | ToolCall | ToolResult


@dataclass(frozen=True)
class LlmMessage:
    role: Role
    parts: tuple[Part, ...]
    provider_state: Any = None  # assistant: provayderning xom javob bloklari (navbat ichida qaytariladi)
    provider: ProviderName | None = None  # provider_state qaysi provayderniki


@dataclass(frozen=True)
class SystemBlock:
    text: str
    cacheable: bool = True  # Claude: breakpoint; Gemini: implicit kesh


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    json_schema: dict[str, Any]  # additionalProperties: false, hamma maydon required


@dataclass(frozen=True)
class LlmRequest:
    model_alias: ModelAlias
    system: tuple[SystemBlock, ...]
    messages: tuple[LlmMessage, ...]
    tools: tuple[ToolSpec, ...] = ()
    max_output_tokens: int = 4096
    effort: Effort = "low"
    timeout_s: float = 15.0


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_tokens: int = 0  # Gemini alohida beradi; Claude'da output_tokens ichida


@dataclass(frozen=True)
class LlmResponse:
    parts: tuple[TextPart | ToolCall, ...]
    stop: StopReason
    usage: Usage
    model_id: str
    provider: ProviderName
    provider_request_id: str | None = None
    fallback_used: bool = False
    provider_state: Any = None
    pricing_model_id: str | None = None  # so'ralgan model (zaxira ishlaganda narx uchun)

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart)).strip()

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [p for p in self.parts if isinstance(p, ToolCall)]

    def as_message(self) -> LlmMessage:
        return LlmMessage(
            role="assistant", parts=self.parts, provider_state=self.provider_state, provider=self.provider
        )


class LlmError(Exception):
    """Provayder xatosi. `retryable` — 429/5xx/timeout/ulanish (bitta qayta urinish, M06 §10)."""

    def __init__(self, code: str, *, retryable: bool, model_fallback: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.model_fallback = model_fallback  # model topilmadi / ortiqcha yuklangan — keyingi modelga


@dataclass(frozen=True)
class ProviderStatus:
    """Panel uchun: qaysi provayder, kalit bormi, sozlanganmi."""

    provider: ProviderName
    configured: bool  # haqiqiy kalit bor (fake — False)
    key_present: bool
    reason: str | None = None  # "missing_key" | "fake" | None
    models: dict[str, str] = field(default_factory=dict)


class LlmProvider(Protocol):
    name: ProviderName

    async def generate(self, req: LlmRequest, model_id: str) -> LlmResponse: ...
