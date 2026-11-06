"""Telegram adapteri (S2-02, 13 §3–4): Bot API, webhook (prod) yoki long polling (lokal),
update → `InboundMessage`.

Shop o'z botini ulaydi: ega tokenni kiritadi → `getMe` → `setWebhook` (sir bilan) yoki lokal
polling'da `deleteWebhook`. Webhook'da shop faqat URL'dagi `account_ref` bo'yicha topiladi, update
tanasidan emas (13 §3).
Testlarda tarmoq yo'q — `FakeTelegramClient`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import structlog

from app.domains.messaging.channels.base import (
    ChannelConnectError,
    ChannelSendError,
    InboundAttachment,
    InboundMessage,
    SendResult,
)

logger = structlog.get_logger(__name__)

API_BASE = "https://api.telegram.org"
MAX_TEXT = 4096  # Telegram bitta xabar chegarasi — uzun matn bo'laklarga bo'linadi
MAX_CAPTION = 1024
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
_INT64 = (-(2**63), 2**63 - 1)
LANGUAGES = {"uz": "uz", "ru": "ru", "en": "en"}


@dataclass(frozen=True)
class BotInfo:
    id: int
    username: str | None


class TelegramClient(Protocol):
    async def get_me(self, token: str) -> BotInfo: ...

    async def set_webhook(self, token: str, url: str, secret: str) -> None: ...

    async def delete_webhook(self, token: str) -> None: ...

    async def send_message(self, token: str, chat_id: int, text: str) -> SendResult: ...

    async def send_photo(
        self, token: str, chat_id: int, data: bytes, mime: str, caption: str | None
    ) -> SendResult: ...

    async def download_file(self, token: str, file_id: str) -> tuple[bytes, str | None]: ...

    async def get_updates(
        self, token: str, offset: int | None, wait_seconds: int
    ) -> list[dict[str, Any]]: ...


def split_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    """Uzun matn — so'z chegarasida bo'laklar (har biri ≤ limit)."""
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest or not parts:
        parts.append(rest)
    return parts


def _api_error(status: int, payload: dict[str, Any] | None) -> ChannelSendError:
    params = (payload or {}).get("parameters") or {}
    if status == 429:
        retry_after = params.get("retry_after")
        return ChannelSendError(
            "RATE_LIMITED",
            retryable=True,
            retry_after=int(retry_after) if isinstance(retry_after, int) else 30,
        )
    if status == 401:
        return ChannelSendError("AUTH_REVOKED")
    if status == 403:
        return ChannelSendError("BLOCKED")  # xaridor botni bloklagan
    if status >= 500:
        return ChannelSendError(f"HTTP_{status}", retryable=True)
    return ChannelSendError(f"HTTP_{status}")


class HttpTelegramClient:
    """Haqiqiy Bot API. Token URL ichida — logga yozilmaydi (httpx logi o'chiq, xato faqat kod bilan)."""

    def __init__(self, *, timeout_s: float = 10.0, api_base: str = API_BASE) -> None:
        self._timeout = timeout_s
        self._base = api_base.rstrip("/")

    def _url(self, token: str, method: str) -> str:
        return f"{self._base}/bot{token}/{method}"

    async def _call(
        self,
        token: str,
        method: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        sending: bool = False,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout_s or self._timeout) as client:
                response = await client.post(self._url(token, method), json=json, files=files, data=data)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ChannelSendError("NETWORK", retryable=True) from exc
        except httpx.TimeoutException as exc:
            # So'rov ketgan, javob kelmadi — yuborish uchun "noma'lum" (qayta yuborilmaydi, 06 §4.2)
            raise ChannelSendError("TIMEOUT", unknown=sending, retryable=not sending) from exc
        except httpx.HTTPError as exc:
            raise ChannelSendError("NETWORK", retryable=True) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code == 200 and isinstance(payload, dict) and payload.get("ok"):
            return payload.get("result")
        raise _api_error(response.status_code, payload if isinstance(payload, dict) else None)

    async def get_me(self, token: str) -> BotInfo:
        try:
            result = await self._call(token, "getMe")
        except ChannelSendError as exc:
            raise ChannelConnectError(
                "INVALID_TOKEN" if exc.code in ("AUTH_REVOKED", "HTTP_404") else exc.code
            ) from exc
        return BotInfo(id=int(result["id"]), username=result.get("username"))

    async def set_webhook(self, token: str, url: str, secret: str) -> None:
        try:
            await self._call(
                token,
                "setWebhook",
                json={
                    "url": url,
                    "secret_token": secret,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": False,
                },
            )
        except ChannelSendError as exc:
            raise ChannelConnectError("WEBHOOK_FAILED") from exc

    async def delete_webhook(self, token: str) -> None:
        try:
            await self._call(token, "deleteWebhook", json={"drop_pending_updates": False})
        except ChannelSendError as exc:
            raise ChannelConnectError("WEBHOOK_FAILED") from exc

    async def send_message(self, token: str, chat_id: int, text: str) -> SendResult:
        first: str | None = None
        parts = split_text(text)
        for part in parts:
            result = await self._call(
                token,
                "sendMessage",
                json={"chat_id": chat_id, "text": part, "disable_web_page_preview": True},
                sending=True,
            )
            if first is None and isinstance(result, dict):
                first = str(result.get("message_id"))
        return SendResult(provider_message_id=first, parts=len(parts))

    async def send_photo(
        self, token: str, chat_id: int, data: bytes, mime: str, caption: str | None
    ) -> SendResult:
        payload: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            payload["caption"] = caption[:MAX_CAPTION]
        result = await self._call(
            token, "sendPhoto", data=payload, files={"photo": ("photo", data, mime)}, sending=True
        )
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return SendResult(provider_message_id=str(message_id) if message_id is not None else None)

    async def download_file(self, token: str, file_id: str) -> tuple[bytes, str | None]:
        info = await self._call(token, "getFile", json={"file_id": file_id})
        path = info.get("file_path") if isinstance(info, dict) else None
        size = info.get("file_size") if isinstance(info, dict) else None
        if not path:
            raise ChannelSendError("FILE_UNAVAILABLE")
        if isinstance(size, int) and size > MAX_DOWNLOAD_BYTES:
            raise ChannelSendError("FILE_TOO_LARGE")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self._base}/file/bot{token}/{path}")
        except httpx.HTTPError as exc:
            raise ChannelSendError("NETWORK", retryable=True) from exc
        if response.status_code != 200:
            raise _api_error(response.status_code, None)
        if len(response.content) > MAX_DOWNLOAD_BYTES:
            raise ChannelSendError("FILE_TOO_LARGE")
        return response.content, response.headers.get("content-type")

    async def get_updates(self, token: str, offset: int | None, wait_seconds: int) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "timeout": wait_seconds,
            "allowed_updates": ["message", "edited_message", "callback_query"],
        }
        if offset is not None:
            body["offset"] = offset
        result = await self._call(token, "getUpdates", json=body, timeout_s=wait_seconds + 10)
        return [u for u in result if isinstance(u, dict)] if isinstance(result, list) else []


@dataclass
class FakeTelegramClient:
    """Testlar va lokal soxta akkaunt: tarmoqsiz. `bots` — token → BotInfo; `send_errors` — navbatdagi
    yuborishlar shu xatolar bilan (birinchisi birinchi urinishga); `updates` — polling uchun."""

    bots: dict[str, BotInfo] = field(default_factory=dict)
    sent: list[tuple[str, int, str]] = field(default_factory=list)
    photos: list[tuple[str, int, int, str | None]] = field(default_factory=list)
    webhooks: dict[str, tuple[str, str] | None] = field(default_factory=dict)
    send_errors: list[ChannelSendError] = field(default_factory=list)
    files: dict[str, tuple[bytes, str | None]] = field(default_factory=dict)
    updates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _next_id: int = 1000

    async def get_me(self, token: str) -> BotInfo:
        bot = self.bots.get(token)
        if bot is None:
            raise ChannelConnectError("INVALID_TOKEN")
        return bot

    async def set_webhook(self, token: str, url: str, secret: str) -> None:
        self.webhooks[token] = (url, secret)

    async def delete_webhook(self, token: str) -> None:
        self.webhooks[token] = None

    def _result(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    async def send_message(self, token: str, chat_id: int, text: str) -> SendResult:
        if self.send_errors:
            raise self.send_errors.pop(0)
        parts = split_text(text)
        for part in parts:
            self.sent.append((token, chat_id, part))
        return SendResult(provider_message_id=self._result(), parts=len(parts))

    async def send_photo(
        self, token: str, chat_id: int, data: bytes, mime: str, caption: str | None
    ) -> SendResult:
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.photos.append((token, chat_id, len(data), caption))
        return SendResult(provider_message_id=self._result())

    async def download_file(self, token: str, file_id: str) -> tuple[bytes, str | None]:
        found = self.files.get(file_id)
        if found is None:
            raise ChannelSendError("FILE_UNAVAILABLE")
        return found

    async def get_updates(self, token: str, offset: int | None, wait_seconds: int) -> list[dict[str, Any]]:
        pending = [
            u for u in self.updates.get(token, []) if offset is None or u.get("update_id", 0) >= offset
        ]
        return pending


# ------------------------------------------------------------------ update → InboundMessage
def _int64(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if _INT64[0] <= value <= _INT64[1] else None


def _occurred(raw: Any) -> datetime:
    if isinstance(raw, int) and not isinstance(raw, bool) and 0 < raw < 2**33:
        return datetime.fromtimestamp(raw, UTC)
    return datetime.fromtimestamp(time.time(), UTC)


def _str(value: Any, limit: int = 64) -> str | None:
    """Faqat matn (int, dict, ro'yxat — e'tiborsiz): buzuq update 500 bermaydi (QA 5b L1)."""
    return value[:limit] if isinstance(value, str) and value else None


def _size(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _name(user: dict[str, Any]) -> str | None:
    parts = [(_str(user.get(k), 120) or "").strip() for k in ("first_name", "last_name")]
    name = " ".join(p for p in parts if p)
    return name[:120] or None


def parse_update(update: dict[str, Any]) -> InboundMessage | None:
    """Telegram update → normallashtirilgan xabar. Tanib bo'lmaydigan update — None (dedup'siz e'tiborsiz)."""
    update_id = _int64(update.get("update_id"))
    if update_id is None:
        return None
    edited = isinstance(update.get("edited_message"), dict)
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        user = callback.get("from")
        user_id = _int64(user.get("id")) if isinstance(user, dict) else None
        if user_id is None or not isinstance(user, dict):
            return None
        data = _str(callback.get("data"), 64) or ""
        return InboundMessage(
            provider_event_id=str(update_id),
            event_kind="CALLBACK",
            external_user_id=str(user_id),
            occurred_at=_occurred(None),
            kind="TEXT",
            body=None,
            display_name=_name(user),
            username=_str(user.get("username")),
            language_code=LANGUAGES.get((_str(user.get("language_code"), 8) or "")[:2]),
            intent_hint="PURCHASE_INTENT" if data.lower().startswith("buy") else None,
        )
    message = update.get("edited_message") if edited else update.get("message")
    if not isinstance(message, dict):
        return None
    chat, user = message.get("chat"), message.get("from")
    if not isinstance(chat, dict) or not isinstance(user, dict):
        return None
    user_id = _int64(user.get("id"))
    if user_id is None:
        return None
    base: dict[str, Any] = {
        "provider_event_id": str(update_id),
        "event_kind": "EDITED" if edited else "MESSAGE",
        "external_user_id": str(user_id),
        "occurred_at": _occurred(message.get("date")),
        "display_name": _name(user),
        "username": _str(user.get("username")),
        "language_code": LANGUAGES.get((_str(user.get("language_code"), 8) or "")[:2]),
        "provider_message_id": str(message.get("message_id"))
        if message.get("message_id") is not None
        else None,
    }
    if chat.get("type") != "private":
        return InboundMessage(**base, ignore_reason="GROUP_CHAT")
    if user.get("is_bot"):
        return InboundMessage(**base, ignore_reason="BOT_AUTHOR")
    text = message.get("text") if isinstance(message.get("text"), str) else None
    caption = message.get("caption") if isinstance(message.get("caption"), str) else None
    if text is not None:
        command = text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower() if text.strip() else ""
        intent = "OPERATOR_REQUEST" if command == "/operator" else None
        return InboundMessage(**base, kind="TEXT", body=text, intent_hint=intent)
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = max(
            (p for p in photos if isinstance(p, dict)),
            key=lambda p: _size(p.get("file_size")),
            default=None,
        )
        ref = _str(largest.get("file_id"), 256) if largest else None
        size = largest.get("file_size") if largest else None
        return InboundMessage(
            **base,
            kind="IMAGE",
            body=caption,
            attachments=(
                InboundAttachment("IMAGE", ref, "image/jpeg", size if isinstance(size, int) else None),
            ),
        )
    contact = message.get("contact")
    if isinstance(contact, dict):
        own = _int64(contact.get("user_id")) == user_id  # faqat o'z raqami — boshqaning raqami yozilmaydi
        phone = contact.get("phone_number") if own and isinstance(contact.get("phone_number"), str) else None
        return InboundMessage(**base, kind="CONTACT", body=None, contact_phone=phone)
    for key, kind in (("voice", "VOICE"), ("audio", "VOICE"), ("document", "FILE"), ("video", "FILE")):
        item = message.get(key)
        if isinstance(item, dict):
            duration = item.get("duration")
            size = item.get("file_size")
            return InboundMessage(
                **base,
                kind=kind,
                body=caption,
                attachments=(
                    InboundAttachment(
                        kind,
                        _str(item.get("file_id"), 256),
                        item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
                        size if isinstance(size, int) else None,
                        duration if isinstance(duration, int) else None,
                    ),
                ),
            )
    if isinstance(message.get("sticker"), dict):
        return InboundMessage(**base, kind="STICKER", body=None)
    location = message.get("location")
    if isinstance(location, dict):
        lat, lon = location.get("latitude"), location.get("longitude")
        body = f"{lat}, {lon}" if isinstance(lat, int | float) and isinstance(lon, int | float) else None
        return InboundMessage(**base, kind="LOCATION", body=body)
    return InboundMessage(**base, kind="UNSUPPORTED", body=None)
