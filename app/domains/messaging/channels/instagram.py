"""Instagram Direct adapteri (S2-05) — DEC-116a: Meta ruxsati kelguncha feature flag ostida (o'chiq).

Hozircha faqat tuzilma: webhook tasdig'i (`hub.challenge`), imzo tekshiruvi (`X-Hub-Signature-256`,
app secret bilan), Direct xabarini `InboundMessage` ga keltirish va soxta klient. Haqiqiy Meta chaqiruvi
flag yoqilib, app review o'tgandan keyin (`HttpInstagramClient`). Izohlar (DEC-132) — keyingi modul.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.domains.messaging.channels.base import (
    ChannelConnectError,
    ChannelSendError,
    InboundMessage,
    SendResult,
)

GRAPH_BASE = "https://graph.facebook.com/v19.0"
WINDOW_HOURS = 24  # BL-033: xaridorning oxirgi xabaridan 24 soat ichida javob


@dataclass(frozen=True)
class InstagramAccount:
    id: str
    username: str | None


class InstagramClient(Protocol):
    async def get_account(self, token: str) -> InstagramAccount: ...

    async def send_message(self, token: str, account_id: str, recipient_id: str, text: str) -> SendResult: ...


class HttpInstagramClient:
    def __init__(self, *, timeout_s: float = 10.0) -> None:
        self._timeout = timeout_s

    async def get_account(self, token: str) -> InstagramAccount:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{GRAPH_BASE}/me", params={"fields": "id,username", "access_token": token}
                )
        except httpx.HTTPError as exc:
            raise ChannelConnectError("NETWORK") from exc
        if response.status_code != 200:
            raise ChannelConnectError("INVALID_TOKEN")
        body = response.json()
        return InstagramAccount(id=str(body["id"]), username=body.get("username"))

    async def send_message(self, token: str, account_id: str, recipient_id: str, text: str) -> SendResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{GRAPH_BASE}/{account_id}/messages",
                    params={"access_token": token},
                    json={"recipient": {"id": recipient_id}, "message": {"text": text[:1000]}},
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ChannelSendError("NETWORK", retryable=True) from exc
        except httpx.TimeoutException as exc:
            raise ChannelSendError("TIMEOUT", unknown=True) from exc
        if response.status_code == 200:
            return SendResult(provider_message_id=str(response.json().get("message_id") or "") or None)
        if response.status_code == 429:
            raise ChannelSendError("RATE_LIMITED", retryable=True, retry_after=60)
        if response.status_code >= 500:
            raise ChannelSendError(f"HTTP_{response.status_code}", retryable=True)
        raise ChannelSendError(
            "WINDOW_CLOSED" if response.status_code == 400 else f"HTTP_{response.status_code}"
        )


@dataclass
class FakeInstagramClient:
    accounts: dict[str, InstagramAccount] = field(default_factory=dict)
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    async def get_account(self, token: str) -> InstagramAccount:
        account = self.accounts.get(token)
        if account is None:
            raise ChannelConnectError("INVALID_TOKEN")
        return account

    async def send_message(self, token: str, account_id: str, recipient_id: str, text: str) -> SendResult:
        self.sent.append((account_id, recipient_id, text))
        return SendResult(provider_message_id=f"mid.{len(self.sent)}")


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """`X-Hub-Signature-256: sha256=<hex>` — app secret bilan HMAC, doimiy vaqtda solishtiriladi."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


def parse_webhook(payload: dict[str, Any]) -> list[tuple[str, InboundMessage]]:
    """Meta `entry[].messaging[]` → (professional akkaunt id, xabar). Faqat matnli Direct xabarlari."""
    result: list[tuple[str, InboundMessage]] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        account_id = str(entry.get("id") or "")
        for item in entry.get("messaging") or []:
            if not isinstance(item, dict):
                continue
            sender, message = item.get("sender"), item.get("message")
            if not isinstance(sender, dict) or not isinstance(message, dict):
                continue
            if not account_id or not sender.get("id") or message.get("is_echo"):
                continue
            mid = message.get("mid")
            if not isinstance(mid, str):
                continue
            stamp = item.get("timestamp")
            occurred = (
                datetime.fromtimestamp(stamp / 1000, UTC)
                if isinstance(stamp, int) and not isinstance(stamp, bool)
                else datetime.now(UTC)
            )
            text = message.get("text") if isinstance(message.get("text"), str) else None
            result.append(
                (
                    account_id,
                    InboundMessage(
                        provider_event_id=mid,
                        event_kind="MESSAGE",
                        external_user_id=str(sender["id"]),
                        occurred_at=occurred,
                        kind="TEXT" if text is not None else "UNSUPPORTED",
                        body=text,
                        provider_message_id=mid,
                    ),
                )
            )
    return result
