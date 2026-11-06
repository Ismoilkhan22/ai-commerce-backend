"""Platforma boti orqali xodimga xabar (DEC-129, 20 §2). Token — muhit sozlamasida, bazada emas.

Token yo'q (lokal) — `LoggingTelegramSender`: xabar yuborilmaydi, faqat logga "yuborildi" yoziladi
(matn logga tushmaydi). Testlarda — `FakeTelegramSender`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx
import structlog

logger = structlog.get_logger(__name__)
API_BASE = "https://api.telegram.org"


class TelegramSendError(Exception):
    """`retryable` — vaqtinchalik (5xx, timeout, 429); aks holda (403 bloklangan) qayta urinilmaydi."""

    def __init__(self, code: str, *, retryable: bool, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


class TelegramSender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None: ...


class HttpTelegramSender:
    def __init__(self, token: str, *, timeout_s: float = 10.0) -> None:
        self._url = f"{API_BASE}/bot{token}/sendMessage"
        self._timeout = timeout_s

    async def send_message(self, chat_id: int, text: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
                )
        except httpx.HTTPError as exc:
            raise TelegramSendError("NETWORK", retryable=True) from exc
        if response.status_code == 200:
            return
        if response.status_code == 429:
            retry_after = int(response.json().get("parameters", {}).get("retry_after", 30))
            raise TelegramSendError("RATE_LIMITED", retryable=True, retry_after=retry_after)
        if response.status_code == 403:
            raise TelegramSendError("BLOCKED", retryable=False)  # xodim botni bloklagan
        if response.status_code >= 500:
            raise TelegramSendError(f"HTTP_{response.status_code}", retryable=True)
        raise TelegramSendError(f"HTTP_{response.status_code}", retryable=False)


class LoggingTelegramSender:
    """Bot tokeni sozlanmagan muhit (lokal): hech narsa yuborilmaydi."""

    async def send_message(self, chat_id: int, text: str) -> None:
        logger.info("telegram.dev_send", chat_id_suffix=str(chat_id)[-3:], length=len(text))


@dataclass
class FakeTelegramSender:
    """Testlar: yuborilganlar ro'yxati; `fail_with` — keyingi yuborishlar shu xato bilan."""

    sent: list[tuple[int, str]] = field(default_factory=list)
    fail_with: TelegramSendError | None = None

    async def send_message(self, chat_id: int, text: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((chat_id, text))


def build_sender(token: str | None) -> TelegramSender:
    return HttpTelegramSender(token) if token else LoggingTelegramSender()
