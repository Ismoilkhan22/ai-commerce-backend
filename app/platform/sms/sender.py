"""SMS yuborish porti (M21 — shopning o'zi ro'yxatdan o'tishi, telefon tasdig'i).

- `FakeSmsSender` — dev va testlar: xabar xotirada (`sent`), logga faqat raqamning oxirgi 4 belgisi. Prod'da
  ishlatib bo'lmaydi (settings tekshiradi).
- `EskizSmsSender` — notify.eskiz.uz: `POST /api/auth/login` (email + parol) → token (30 kun, keshda), so'ng
  `POST /api/message/sms/send`. Matn Eskiz'da oldindan tasdiqlangan shablonga mos bo'lishi kerak.
Matn va kod logga yozilmaydi.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import structlog

logger = structlog.get_logger(__name__)

ESKIZ_BASE = "https://notify.eskiz.uz/api"


class SmsError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SmsSender(Protocol):
    async def send(self, phone: str, text: str) -> None:
        """`phone` — E.164 (+998…). Yuborib bo'lmasa — `SmsError`."""
        ...


@dataclass
class FakeSmsSender:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def send(self, phone: str, text: str) -> None:
        self.sent.append((phone, text))
        logger.info("sms.fake_sent", phone_tail=phone[-4:])


class EskizSmsSender:
    def __init__(self, email: str, password: str, sender: str, *, timeout_s: float = 10.0) -> None:
        self._email = email
        self._password = password
        self._from = sender
        self._timeout = timeout_s
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def _login(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{ESKIZ_BASE}/auth/login", data={"email": self._email, "password": self._password}
        )
        if response.status_code != 200:
            raise SmsError("SMS_AUTH_FAILED")
        try:
            token = (response.json().get("data") or {}).get("token")
        except (ValueError, AttributeError) as exc:  # HTML yoki kutilmagan JSON
            raise SmsError("SMS_AUTH_FAILED") from exc
        if not token:
            raise SmsError("SMS_AUTH_FAILED")
        return str(token)

    async def send(self, phone: str, text: str) -> None:
        data = {"mobile_phone": phone.lstrip("+"), "message": text, "from": self._from}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with self._lock:
                    if self._token is None:
                        self._token = await self._login(client)
                response = await client.post(
                    f"{ESKIZ_BASE}/message/sms/send",
                    data=data,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if response.status_code == 401:  # token eskirgan — bir marta yangilanadi
                    async with self._lock:
                        self._token = await self._login(client)
                    response = await client.post(
                        f"{ESKIZ_BASE}/message/sms/send",
                        data=data,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
        except httpx.HTTPError as exc:
            raise SmsError("SMS_UNAVAILABLE") from exc
        if response.status_code != 200:
            logger.warning("sms.rejected", status=response.status_code)
            raise SmsError("SMS_REJECTED")
