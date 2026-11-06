"""GeminiProvider — Google Gemini (lokal va dev uchun, M06 §4.1). Rasmiy `google-genai` SDK, async klient.

- tizim bloklari `system_instruction` ga qo'shiladi (kesh — Gemini'ning implicit keshi);
- tool'lar `function_declarations` (`parameters_json_schema`), SDK'ning avtomatik chaqiruvi o'chiq —
  tool'larni
  bizning broker bajaradi; majburiy rejim yo'q (`auto`), Claude bilan bir xil xulq;
- `function_call.id` bo'lmasa adapter o'zi yaratadi; natija `function_response` — nom bo'yicha bog'lanadi;
- navbat ichida modelning `Content` obyekti (thought signature bilan) o'zgartirilmasdan qaytariladi.
Bepul kalit bilan faqat sintetik ma'lumot (A14) — production'da `GEMINI_TIER=paid` bo'lmasa ilova ishga
tushmaydi.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
from google import genai
from google.genai import errors, types

from app.platform.llm.port import (
    LlmError,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    MediaPart,
    ProviderName,
    StopReason,
    TextPart,
    ToolCall,
    ToolResult,
    Usage,
)

_STOP: dict[str, StopReason] = {
    "STOP": "END",
    "MAX_TOKENS": "MAX_TOKENS",
    "SAFETY": "REFUSAL",
    "PROHIBITED_CONTENT": "REFUSAL",
    "BLOCKLIST": "REFUSAL",
    "SPII": "REFUSAL",
    "RECITATION": "REFUSAL",
}


class GeminiProvider:
    name: ProviderName = "gemini"

    def __init__(self, api_key: str, *, client: genai.Client | None = None) -> None:
        self.client = client or genai.Client(api_key=api_key)

    async def generate(self, req: LlmRequest, model_id: str) -> LlmResponse:
        config = types.GenerateContentConfig(
            system_instruction="\n\n".join(block.text for block in req.system),
            max_output_tokens=req.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            http_options=types.HttpOptions(timeout=int(req.timeout_s * 1000)),
        )
        if req.tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name, description=t.description, parameters_json_schema=t.json_schema
                        )
                        for t in req.tools
                    ]
                )
            ]
        try:
            response = await self.client.aio.models.generate_content(
                model=model_id, contents=[_content(m) for m in req.messages], config=config
            )
        except errors.APIError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            if code == 404:
                raise LlmError("model_not_found", retryable=False, model_fallback=True) from exc
            raise LlmError(f"http_{code}", retryable=code in (408, 429) or code >= 500) from exc
        except (httpx.TimeoutException, TimeoutError) as exc:  # SDK httpx ustida (aiohttp yo'q) — F-15
            raise LlmError("timeout", retryable=True) from exc
        except (httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError, OSError) as exc:
            raise LlmError("network", retryable=True) from exc
        except Exception as exc:  # SDK'ning boshqa xatolari navbatni RUNNING'da qoldirmasin
            raise LlmError(f"provider_{type(exc).__name__}"[:60].lower(), retryable=False) from exc
        return _response(response, model_id)


def _content(message: LlmMessage) -> types.Content:
    if message.role == "assistant":
        if message.provider == "gemini" and isinstance(message.provider_state, types.Content):
            return message.provider_state
        parts: list[types.Part] = []
        for part in message.parts:
            if isinstance(part, TextPart) and part.text:
                parts.append(types.Part(text=part.text))
            elif isinstance(part, ToolCall):
                parts.append(
                    types.Part(function_call=types.FunctionCall(id=part.id, name=part.name, args=part.args))
                )
        return types.Content(role="model", parts=parts)
    out: list[types.Part] = []
    for part in message.parts:
        if isinstance(part, ToolResult):
            response: dict[str, Any] = {"error" if part.is_error else "result": _json(part.content)}
            out.append(types.Part.from_function_response(name=part.name, response=response))
        elif isinstance(part, TextPart):
            out.append(types.Part(text=part.text))
        elif isinstance(part, MediaPart):
            out.append(types.Part.from_bytes(data=part.data, mime_type=part.mime))
    return types.Content(role="user", parts=out)


def _json(content: str) -> Any:
    try:
        return json.loads(content)
    except ValueError:
        return content


def _response(response: Any, model_id: str) -> LlmResponse:
    candidates = getattr(response, "candidates", None) or []
    meta = getattr(response, "usage_metadata", None)
    cached = int(getattr(meta, "cached_content_token_count", 0) or 0)
    usage = Usage(  # prompt_token_count keshlanganlarni ham o'z ichiga oladi — ikki marta sanalmaydi (F-35)
        input_tokens=max(0, int(getattr(meta, "prompt_token_count", 0) or 0) - cached),
        output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0),
        cache_read_tokens=cached,
        thinking_tokens=int(getattr(meta, "thoughts_token_count", 0) or 0),
    )
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None)
        stop: StopReason = "REFUSAL" if getattr(feedback, "block_reason", None) else "ERROR"
        return LlmResponse((), stop, usage, model_id, "gemini")
    candidate = candidates[0]
    content = getattr(candidate, "content", None)
    parts: list[TextPart | ToolCall] = []
    for part in getattr(content, "parts", None) or []:
        if getattr(part, "thought", False):
            continue
        call = getattr(part, "function_call", None)
        if call is not None:
            parts.append(
                ToolCall(call.id or f"call_{uuid4().hex[:12]}", call.name or "", dict(call.args or {}))
            )
        elif getattr(part, "text", None):
            parts.append(TextPart(part.text))
    reason = getattr(candidate, "finish_reason", None)
    name = getattr(reason, "name", None) or str(reason or "STOP")
    stop = "TOOL_CALLS" if any(isinstance(p, ToolCall) for p in parts) else _STOP.get(name, "ERROR")
    return LlmResponse(
        parts=tuple(parts),
        stop=stop,
        usage=usage,
        model_id=model_id,  # narx sozlangan model bo'yicha ("gemini-2.5-flash-002" emas) — F-16
        provider="gemini",
        provider_request_id=getattr(response, "response_id", None),
        provider_state=content,
    )
