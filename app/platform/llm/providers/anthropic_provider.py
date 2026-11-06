"""AnthropicProvider — Claude (production uchun tavsiya, M06 §4.1). Rasmiy `anthropic` Python SDK.

So'rov sozlamalari (claude-api ko'rsatmasi bo'yicha):
- thinking yuborilmaydi: Sonnet 5.5 / Opus 5.5 / Haiku 5.5 da adaptive standart; chuqurlik
  `output_config.effort`;
- `tool_choice` faqat `auto` (majburiy tool bu modellarda 400), tool'lar `strict: true`;
- Sonnet 5.5 va Opus 5.5 da server-side fallback: beta `server-side-fallback-2026-07-01` +
  `fallbacks: "default"`
  (Haiku 5.5 da yo'q);
- prompt kesh: barqaror tizim bloklari oxirida `cache_control` breakpoint (≤ 4);
- navbat ichida assistant javobi bloklari (thinking ham) o'zgartirilmasdan qaytariladi.
Kalit va matn logga yozilmaydi.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from app.platform.llm.port import (
    LlmError,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    ProviderName,
    StopReason,
    TextPart,
    ToolCall,
    ToolResult,
    Usage,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})
_STOP: dict[str, StopReason] = {
    "end_turn": "END",
    "stop_sequence": "END",
    "tool_use": "TOOL_CALLS",
    "max_tokens": "MAX_TOKENS",
    "refusal": "REFUSAL",
}


class AnthropicProvider:
    name: ProviderName = "anthropic"

    def __init__(self, api_key: str, *, client: AsyncAnthropic | None = None) -> None:
        # max_retries=0: qayta urinish LlmRouter'da (bitta, umumiy 20 s budget ichida)
        self.client = client or AsyncAnthropic(api_key=api_key, max_retries=0)

    async def generate(self, req: LlmRequest, model_id: str) -> LlmResponse:
        params: dict[str, Any] = {
            "model": model_id,
            "max_tokens": req.max_output_tokens,
            "system": _system(req),
            "messages": [_message(m) for m in req.messages],
            "output_config": {"effort": req.effort},
        }
        if req.tools:
            params["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.json_schema,
                    "strict": True,
                }
                for t in req.tools
            ]
            params["tool_choice"] = {"type": "auto"}
        if model_id in _FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        try:
            response = await self.client.with_options(timeout=req.timeout_s).beta.messages.create(**params)
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise LlmError(f"http_{exc.status_code}", retryable=True) from exc
        except anthropic.NotFoundError as exc:
            raise LlmError("model_not_found", retryable=False, model_fallback=True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code in (408, 409, 529) or exc.status_code >= 500
            raise LlmError(f"http_{exc.status_code}", retryable=retryable) from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise LlmError("timeout", retryable=True) from exc
        return _response(response, model_id)


def _system(req: LlmRequest) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    cacheable = [i for i, b in enumerate(req.system) if b.cacheable]
    breakpoints = set(cacheable[-2:])  # M06 §4.1: 2 ta breakpoint (platforma va shop qatlami)
    for index, block in enumerate(req.system):
        item: dict[str, Any] = {"type": "text", "text": block.text}
        if index in breakpoints:
            item["cache_control"] = {"type": "ephemeral"}
        blocks.append(item)
    return blocks


def _message(message: LlmMessage) -> dict[str, Any]:
    if message.role == "assistant":
        if message.provider == "anthropic" and message.provider_state is not None:
            return {"role": "assistant", "content": message.provider_state}
        content: list[dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart) and part.text:
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, ToolCall):
                content.append({"type": "tool_use", "id": part.id, "name": part.name, "input": part.args})
        return {"role": "assistant", "content": content}
    blocks: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, ToolResult):
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": part.call_id,
                    "content": part.content,
                    "is_error": part.is_error,
                }
            )
        elif isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
    return {"role": "user", "content": blocks}


def _response(response: Any, model_id: str) -> LlmResponse:
    parts: list[TextPart | ToolCall] = []
    for block in response.content:
        if block.type == "text":
            parts.append(TextPart(block.text))
        elif block.type == "tool_use":
            args = block.input if isinstance(block.input, dict) else json.loads(json.dumps(block.input))
            parts.append(ToolCall(block.id, block.name, dict(args)))
    usage = response.usage
    iterations = getattr(usage, "iterations", None) or []
    fallback = any(getattr(entry, "type", None) == "fallback_message" for entry in iterations)
    return LlmResponse(
        parts=tuple(parts),
        stop=_STOP.get(str(response.stop_reason), "ERROR"),
        usage=Usage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
        ),
        model_id=str(getattr(response, "model", None) or model_id),
        provider="anthropic",
        provider_request_id=getattr(response, "id", None),
        fallback_used=fallback,
        # zaxira model ishlagan bo'lsa — narx ikkalasining qimmatrog'i bo'yicha (F-35)
        pricing_model_id=model_id if fallback else None,
        # Navbat ichida bloklar o'zgartirilmasdan qaytariladi (thinking ham) — bazaga yozilmaydi.
        # by_alias: `fallback` blokidagi `from_` → `from` (aks holda keyingi so'rov 400 — F-17)
        provider_state=[block.model_dump(by_alias=True, exclude_none=True) for block in response.content],
    )
