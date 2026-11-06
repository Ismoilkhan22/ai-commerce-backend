"""LlmRouter: alias → model, qayta urinish va model zaxirasi (M06 §10).

- Vaqtinchalik xato (429/5xx/timeout) — bitta qayta urinish, kutish bilan (backoff).
- Model topilmadi / ortiqcha yuklangan — ro'yxatdagi keyingi modelga o'tiladi (`fallback_used`).
- Claude'da xavfsizlik rad etishi uchun server-side fallback adapter ichida (`fallbacks: "default"`).
Router DB'ga tegmaydi: xarajat yozuvi chaqiruvchida (`usage.record_usage`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

import structlog

from app.platform.llm.port import LlmError, LlmProvider, LlmRequest, LlmResponse, ModelAlias, ProviderStatus
from app.platform.llm.pricing import DEFAULT_PRICES, ModelPrice

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LlmConfig:
    models: Mapping[str, Sequence[str]]  # alias → [asosiy, zaxira…]
    prices: Mapping[str, ModelPrice] = field(default_factory=lambda: dict(DEFAULT_PRICES))
    retries: int = 1
    backoff_s: float = 0.5


class LlmRouter:
    def __init__(
        self,
        provider: LlmProvider,
        config: LlmConfig,
        status: ProviderStatus,
        *,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.status = status
        self._sleep = sleep

    def models_for(self, alias: ModelAlias) -> Sequence[str]:
        models = self.config.models.get(alias) or self.config.models.get("seller") or ()
        if not models:
            raise LlmError("no_model_configured", retryable=False)
        return models

    def price(self, model_id: str | None) -> ModelPrice | None:
        """Aniq ID yoki versiyali ID ("gemini-2.5-flash-002" → "gemini-2.5-flash"). Topilmasa — None
        (`record_usage` ehtiyotkor narxni oladi va `price_unknown` belgilaydi)."""
        if not model_id:
            return None
        exact = self.config.prices.get(model_id)
        if exact is not None:
            return exact
        prefixes = [known for known in self.config.prices if model_id.startswith(known)]
        return self.config.prices[max(prefixes, key=len)] if prefixes else None

    def price_for(self, response: LlmResponse) -> ModelPrice | None:
        """Javob narxi: zaxira model ishlagan bo'lsa — so'ralgan va ishlagan modelning qimmatrog'i."""
        options = [p for p in (self.price(response.model_id), self.price(response.pricing_model_id)) if p]
        return max(options, key=lambda p: (p.output, p.input)) if options else None

    async def generate(self, req: LlmRequest, *, deadline_s: float | None = None) -> LlmResponse:
        """`deadline_s` — navbatda qolgan vaqt: qayta urinish va zaxira model faqat vaqt qolsa (M06 §10)."""
        models = list(self.models_for(req.model_alias))
        last: LlmError | None = None
        deadline = time.monotonic() + deadline_s if deadline_s is not None else None
        for index, model_id in enumerate(models):
            for attempt in range(self.config.retries + 1):
                call = req
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining < 0.5:
                        raise last or LlmError("deadline_exceeded", retryable=False)
                    call = replace(req, timeout_s=min(req.timeout_s, remaining))
                try:
                    response = await self.provider.generate(call, model_id)
                except LlmError as exc:
                    last = exc
                    logger.warning(
                        "llm.call_failed",
                        provider=self.provider.name,
                        model=model_id,
                        code=exc.code,
                        attempt=attempt + 1,
                    )
                    if exc.model_fallback:
                        break  # keyingi modelga
                    if not exc.retryable or attempt >= self.config.retries:
                        if index + 1 < len(models) and exc.retryable:
                            break
                        raise
                    if deadline is not None and deadline - time.monotonic() < self._delay(attempt) + 0.5:
                        raise
                    await self._wait(attempt)
                    continue
                return replace(response, fallback_used=response.fallback_used or index > 0)
        assert last is not None
        raise last

    def _delay(self, attempt: int) -> float:
        return float(self.config.backoff_s * (2**attempt))

    async def _wait(self, attempt: int) -> None:
        delay = self._delay(attempt)
        if delay <= 0:
            return
        if self._sleep is not None:
            self._sleep(delay)
            return
        await asyncio.sleep(delay)
