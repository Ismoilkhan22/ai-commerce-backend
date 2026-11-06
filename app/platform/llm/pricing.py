"""Narx jadvali: model → USD × 10⁶ (micros) bir million token uchun (A7, M06 §4.2).

Provayder javobida narx yo'q, shuning uchun narx konfiguratsiyada. Claude narxlari — Anthropic narx jadvali
(2026-10); Gemini — taxminiy standart, aniq narx `LLM_PRICES` env bilan beriladi (bake-off hisobotida
qotiriladi). Noma'lum model — 0 EMAS: eng qimmat ma'lum narx (`CONSERVATIVE_PRICE`) olinadi va `ai_usage.
price_unknown` belgilanadi — limit ishlaydi, panelda "narx noma'lum" ko'rinadi (F-16).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.platform.llm.port import Usage


@dataclass(frozen=True)
class ModelPrice:
    """Bir million token narxi, USD micros: 2_000_000 = $2.00."""

    input: int
    output: int
    cache_read: int
    cache_write: int


DEFAULT_PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(2_000_000, 10_000_000, 200_000, 2_500_000),
    "claude-haiku-5-5": ModelPrice(100_000, 500_000, 10_000, 125_000),
    "claude-opus-5-5": ModelPrice(4_000_000, 20_000_000, 200_000, 5_000_000),
    "gemini-2.5-flash": ModelPrice(300_000, 2_500_000, 75_000, 300_000),
    "fake-seller": ModelPrice(1_000_000, 4_000_000, 100_000, 1_000_000),  # testlarda chegara ishlasin
}


CONSERVATIVE_PRICE = max(DEFAULT_PRICES.values(), key=lambda p: (p.output, p.input))


def cost_micros(usage: Usage, price: ModelPrice | None) -> int:
    """Narx (USD micros). Thinking tokenlari chiqish narxida (Gemini alohida beradi)."""
    if price is None:
        return 0
    total = (
        usage.input_tokens * price.input
        + (usage.output_tokens + usage.thinking_tokens) * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    )
    return -(-total // 1_000_000)  # yuqoriga yaxlitlash: kam hisoblamaslik
