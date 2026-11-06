"""FakeProvider — testlar va dev demo uchun (tarmoq yo'q, M06 §4.1).

Ikki rejim:
- **skript** (`script=[...]`): har chaqiruvga navbatdagi qadam — matn, tool chaqiruvlari, xato yoki refusal.
  Testlar provayderga nima yuborilganini `requests` dan tekshiradi (PII hech qachon xom ko'rinmasligi kerak).
- **demo** (skript yo'q): sodda qoidalar — mahsulot savoliga `catalog_search`, keyin topilgan birinchi
  mahsulot narxi bilan javob; "operator" so'ralsa — `messaging_request_handoff`. Kalitsiz sinov oynasi uchun.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.platform.llm.port import (
    LlmError,
    LlmRequest,
    LlmResponse,
    ProviderName,
    StopReason,
    TextPart,
    ToolCall,
    ToolResult,
    Usage,
)


@dataclass(frozen=True)
class FakeText:
    text: str


@dataclass(frozen=True)
class FakeTools:
    calls: tuple[tuple[str, dict[str, Any]], ...]


@dataclass(frozen=True)
class FakeFailure:
    code: str = "http_503"
    retryable: bool = True
    model_fallback: bool = False


@dataclass(frozen=True)
class FakeRefusal:
    pass


FakeStep = FakeText | FakeTools | FakeFailure | FakeRefusal
FAKE_JUDGE_VERDICT = '{"helpfulness": 4, "language": 4, "tone": 4, "comment": "fake judge"}'

_PRODUCT_HINT = re.compile(
    r"\b(rtx|gtx|radeon|ryzen|intel|core|i[3579]|noutbuk|laptop|ноутбук|видеокарт|videokarta|"
    r"protsessor|процессор|monitor|монитор|ssd|ram|\d{4})\b",
    re.IGNORECASE,
)
_MODEL = re.compile(r"\b(?:rtx|gtx|rx)\s*\d{3,4}(?:\s*ti)?\b|\bi[3579][-\s]?\d{4,5}\w?\b", re.IGNORECASE)
_HUMAN_HINT = re.compile(r"\b(operator|оператор|odam|человек|human|menejer|менеджер)\b", re.IGNORECASE)


@dataclass
class FakeProvider:
    script: list[FakeStep] = field(default_factory=list)
    name: ProviderName = "fake"
    requests: list[LlmRequest] = field(default_factory=list)
    models_used: list[str] = field(default_factory=list)
    # `light` roli (javob tekshiruvchisi) — alohida navbat; bo'sh bo'lsa "buzilish yo'q" (sotuvchi skriptiga
    # tegmaydi)
    light_script: list[FakeStep] = field(default_factory=list)
    light_requests: list[LlmRequest] = field(default_factory=list)
    # `judge` roli (6c baholash) — alohida navbat; bo'sh bo'lsa barqaror "4/5" baho (skriptlangan judge)
    judge_script: list[FakeStep] = field(default_factory=list)
    judge_requests: list[LlmRequest] = field(default_factory=list)

    def push(self, *steps: FakeStep) -> None:
        self.script.extend(steps)

    def push_light(self, *steps: FakeStep) -> None:
        self.light_script.extend(steps)

    def push_judge(self, *steps: FakeStep) -> None:
        self.judge_script.extend(steps)

    async def generate(self, req: LlmRequest, model_id: str) -> LlmResponse:
        if req.model_alias == "light":
            self.light_requests.append(req)
            step: FakeStep = self.light_script.pop(0) if self.light_script else FakeText('{"violations": []}')
        elif req.model_alias == "judge":
            self.judge_requests.append(req)
            step = self.judge_script.pop(0) if self.judge_script else FakeText(FAKE_JUDGE_VERDICT)
        else:
            self.requests.append(req)
            self.models_used.append(model_id)
            step = self.script.pop(0) if self.script else _demo(req)
        usage = Usage(input_tokens=_approx_tokens(req), output_tokens=40)
        if isinstance(step, FakeFailure):
            raise LlmError(step.code, retryable=step.retryable, model_fallback=step.model_fallback)
        if isinstance(step, FakeRefusal):
            return LlmResponse((), "REFUSAL", usage, model_id, "fake")
        if isinstance(step, FakeTools):
            calls = tuple(ToolCall(f"call_{uuid4().hex[:10]}", name, args) for name, args in step.calls)
            return LlmResponse(calls, "TOOL_CALLS", usage, model_id, "fake")
        stop: StopReason = "END"
        return LlmResponse((TextPart(step.text),), stop, usage, model_id, "fake")


def _approx_tokens(req: LlmRequest) -> int:
    size = sum(len(b.text) for b in req.system)
    for message in req.messages:
        for part in message.parts:
            size += len(getattr(part, "text", "") or getattr(part, "content", "") or "")
    return max(1, size // 4)


def _texts(parts: Iterable[Any]) -> str:
    return " ".join(p.text for p in parts if isinstance(p, TextPart))


def _demo(req: LlmRequest) -> FakeStep:
    if not req.messages:
        return FakeText("Assalomu alaykum! Qanday yordam bera olaman?")
    last = req.messages[-1]
    results = [p for p in last.parts if isinstance(p, ToolResult)]
    if results:
        return FakeText(_answer_from_results(results))
    text = _texts(last.parts)
    tool_names = {t.name for t in req.tools}
    if _HUMAN_HINT.search(text) and "messaging_request_handoff" in tool_names:
        return FakeTools((("messaging_request_handoff", {"reason": "CUSTOMER_REQUEST"}),))
    if _PRODUCT_HINT.search(text) and "catalog_search" in tool_names:
        return FakeTools((("catalog_search", {"query": _query(text), "max_results": 3}),))
    return FakeText("Assalomu alaykum! Qaysi mahsulot qiziqtiradi? Masalan, videokarta yoki noutbuk.")


def _query(text: str) -> str:
    """ "RTX 4060 bormi?" → "RTX 4060": model nomi bo'lsa — o'sha, aks holda birinchi kalit so'z."""
    clean = re.sub(r"<[^>]+>", " ", text)
    model = _MODEL.search(clean)
    if model:
        return " ".join(model.group().split()).upper()
    hint = _PRODUCT_HINT.search(clean)
    return hint.group() if hint else clean.strip()[:80]


def _answer_from_results(results: list[ToolResult]) -> str:
    for result in results:
        if result.is_error:
            continue
        try:
            data = json.loads(result.content)
        except ValueError:
            continue
        items = data.get("data", {}).get("items") if isinstance(data, dict) else None
        if items:
            first = items[0]
            price = first.get("price_uzs")
            if price is None:
                return f"{first.get('title')} bor. Narxini operator aniqlab beradi."
            return f"{first.get('title')} — {price:,} so'm.".replace(",", " ")
        if isinstance(data, dict) and data.get("data", {}).get("handoff"):
            return "Operatorimiz tez orada javob beradi."
    return "Afsuski, bu so'rov bo'yicha mahsulot topilmadi. Boshqa model kerakmi?"
