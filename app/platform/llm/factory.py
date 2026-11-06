"""Provayderni tanlash (M06 §4): `LLM_PROVIDER=gemini|anthropic|fake`, kalitlar env'da.

Kalit yo'q bo'lsa — provayder `disabled` (har chaqiruv `missing_key` xatosi, AI navbati operatorga uzatiladi),
panelda "sozlanmagan". `fake` — testlar va kalitsiz dev demo. Production'da bepul Gemini va `fake` taqiqlangan
(Settings validatori, A14).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.platform.llm.port import (
    LlmError,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    ProviderName,
    ProviderStatus,
)
from app.platform.llm.pricing import DEFAULT_PRICES, ModelPrice
from app.platform.llm.providers.fake import FakeProvider
from app.platform.llm.router import LlmConfig, LlmRouter

ANTHROPIC_MODELS: dict[str, tuple[str, ...]] = {
    "seller": ("claude-sonnet-5-5", "claude-opus-5-5"),
    "light": ("claude-haiku-5-5",),
    "judge": ("claude-opus-5-5",),
}
FAKE_MODELS: dict[str, tuple[str, ...]] = {
    "seller": ("fake-seller",),
    "light": ("fake-seller",),
    "judge": ("fake-seller",),
}


class DisabledProvider:
    """Tanlangan provayderning kaliti yo'q: chaqiruv darhol xato (operatorga uzatish)."""

    def __init__(self, name: ProviderName) -> None:
        self.name = name

    async def generate(self, req: LlmRequest, model_id: str) -> LlmResponse:
        raise LlmError("missing_key", retryable=False)


def build_router(
    provider: str,
    *,
    gemini_api_key: str | None,
    anthropic_api_key: str | None,
    gemini_model: str,
    model_overrides: Mapping[str, Sequence[str]] | None = None,
    prices: Mapping[str, ModelPrice] | None = None,
    backoff_s: float = 0.5,
    fake: FakeProvider | None = None,
) -> LlmRouter:
    price_table = {**DEFAULT_PRICES, **(prices or {})}
    impl: LlmProvider
    if provider == "anthropic":
        models: dict[str, Sequence[str]] = dict(ANTHROPIC_MODELS)
        if anthropic_api_key:
            from app.platform.llm.providers.anthropic_provider import AnthropicProvider

            impl = AnthropicProvider(anthropic_api_key)
            status = ProviderStatus("anthropic", configured=True, key_present=True)
        else:
            impl = DisabledProvider("anthropic")
            status = ProviderStatus("anthropic", configured=False, key_present=False, reason="missing_key")
    elif provider == "gemini":
        models = {alias: (gemini_model,) for alias in ("seller", "light", "judge")}
        if gemini_api_key:
            from app.platform.llm.providers.gemini_provider import GeminiProvider

            impl = GeminiProvider(gemini_api_key)
            status = ProviderStatus("gemini", configured=True, key_present=True)
        else:
            impl = DisabledProvider("gemini")
            status = ProviderStatus("gemini", configured=False, key_present=False, reason="missing_key")
    else:
        models = dict(FAKE_MODELS)
        impl = fake or FakeProvider()
        status = ProviderStatus("fake", configured=False, key_present=False, reason="fake")
    if model_overrides:
        models.update({k: tuple(v) for k, v in model_overrides.items()})
    status = ProviderStatus(
        status.provider,
        status.configured,
        status.key_present,
        status.reason,
        {alias: ids[0] for alias, ids in models.items() if ids},
    )
    return LlmRouter(impl, LlmConfig(models=models, prices=price_table, backoff_s=backoff_s), status)
