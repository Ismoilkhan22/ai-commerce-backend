"""Instagram Direct adapteri (S2-05) — DEC-116a: Meta ruxsati kelguncha feature flag ostida (o'chiq).

Webhook tasdig'i (`hub.challenge`), imzo tekshiruvi (`X-Hub-Signature-256`, app secret bilan), Direct xabarini
`InboundMessage` ga keltirish va soxta klient. Haqiqiy Meta chaqiruvi flag yoqilib, app review o'tgandan keyin
(`HttpInstagramClient`). Izohlar (DEC-132, DEC-148): `entry[].changes[]` (`comments`) → `InboundComment`,
Private Reply (`send_private_reply`) va media ma'lumoti (`fetch_media`) — `InstagramCommentsPort` vazifasi shu
klientda (`ChannelPort` o'zgarmaydi). Meta xato kodlari app review paytida tekshiriladi.
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


COMMENTS_SCOPE = "instagram_manage_comments"
REPLY_WINDOW_DAYS = 7  # Private Reply: izohdan keyin 7 kun (DEC-132)
MEDIA_TYPES = frozenset({"IMAGE", "VIDEO", "CAROUSEL_ALBUM", "REELS"})


@dataclass(frozen=True)
class InstagramAccount:
    id: str
    username: str | None
    scopes: tuple[str, ...] = ()  # Meta ruxsatlari; izohlar uchun `instagram_manage_comments`


@dataclass(frozen=True)
class MediaInfo:
    media_type: str | None
    permalink: str | None
    caption: str | None
    thumbnail_url: str | None
    posted_at: datetime | None


@dataclass(frozen=True)
class InboundComment:
    """Normallashtirilgan izoh hodisasi. `provider_event_id` — dedup kaliti."""

    provider_event_id: str
    external_comment_id: str
    external_media_id: str
    author_external_id: str
    author_username: str | None
    body: str | None
    occurred_at: datetime
    media_type: str | None = None
    parent_external_comment_id: str | None = None
    removed: bool = False  # izoh o'chirildi (verb = remove)


class InstagramClient(Protocol):
    async def get_account(self, token: str) -> InstagramAccount: ...

    async def send_message(self, token: str, account_id: str, recipient_id: str, text: str) -> SendResult: ...

    async def send_private_reply(
        self, token: str, account_id: str, comment_id: str, text: str
    ) -> SendResult: ...

    async def fetch_media(self, token: str, media_id: str) -> MediaInfo | None: ...


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
        if _token_revoked(response):  # ruxsat bekor qilingan / token eskirgan: kanal "uzilgan" (UAT-M09)
            raise ChannelSendError("AUTH_REVOKED")
        raise ChannelSendError(
            "WINDOW_CLOSED" if response.status_code == 400 else f"HTTP_{response.status_code}"
        )

    async def send_private_reply(self, token: str, account_id: str, comment_id: str, text: str) -> SendResult:
        """Private Reply: `recipient.comment_id` (izohdan keyin 7 kun, bitta xabar)."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{GRAPH_BASE}/{account_id}/messages",
                    params={"access_token": token},
                    json={"recipient": {"comment_id": comment_id}, "message": {"text": text[:1000]}},
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
        if response.status_code in (401, 403):
            raise ChannelSendError("AUTH_REVOKED")
        raise ChannelSendError(_private_reply_error(response))

    async def fetch_media(self, token: str, media_id: str) -> MediaInfo | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{GRAPH_BASE}/{media_id}",
                    params={
                        "fields": "media_type,media_product_type,permalink,caption,thumbnail_url,"
                        "media_url,timestamp",
                        "access_token": token,
                    },
                )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        body = response.json()
        return MediaInfo(
            media_type=_media_type(body.get("media_product_type"), body.get("media_type")),
            permalink=body.get("permalink"),
            caption=body.get("caption"),
            thumbnail_url=body.get("thumbnail_url") or body.get("media_url"),
            posted_at=_iso(body.get("timestamp")),
        )


def _token_revoked(response: httpx.Response) -> bool:
    """401/403 yoki Graph `OAuthException` (190 — token yaroqsiz/bekor/eskirgan, 102 — sessiya tugagan)."""
    if response.status_code in (401, 403):
        return True
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    return isinstance(error, dict) and error.get("code") in (190, 102)


def _private_reply_error(response: httpx.Response) -> str:
    """400 → adapter taksonomiyasi (13 §2): 7 kun o'tdi / bu izohga allaqachon javob berilgan. Subkodlar Meta
    hujjatidan; app review paytida haqiqiy javob bilan tekshiriladi."""
    try:
        subcode = response.json().get("error", {}).get("error_subcode")
    except ValueError:
        subcode = None
    if subcode == 2534022:
        return "REPLY_WINDOW_EXPIRED"
    if subcode == 2534023:
        return "ALREADY_REPLIED"
    return f"HTTP_{response.status_code}"


def _media_type(product_type: Any, media_type: Any) -> str | None:
    for value in (product_type, media_type):
        if isinstance(value, str) and value.upper() in MEDIA_TYPES:
            return value.upper()
    return None


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None


@dataclass
class FakeInstagramClient:
    accounts: dict[str, InstagramAccount] = field(default_factory=dict)
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    private_replies: list[tuple[str, str, str]] = field(default_factory=list)  # (akkaunt, izoh id, matn)
    private_reply_errors: list[ChannelSendError] = field(
        default_factory=list
    )  # navbat: har chaqiruvga bittadan
    media: dict[str, MediaInfo] = field(default_factory=dict)
    send_errors: list[ChannelSendError] = field(default_factory=list)  # navbat: DM yuborishga bittadan

    async def get_account(self, token: str) -> InstagramAccount:
        account = self.accounts.get(token)
        if account is None:
            raise ChannelConnectError("INVALID_TOKEN")
        return account

    async def send_message(self, token: str, account_id: str, recipient_id: str, text: str) -> SendResult:
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.sent.append((account_id, recipient_id, text))
        return SendResult(provider_message_id=f"mid.{len(self.sent)}")

    async def send_private_reply(self, token: str, account_id: str, comment_id: str, text: str) -> SendResult:
        if self.private_reply_errors:
            raise self.private_reply_errors.pop(0)
        self.private_replies.append((account_id, comment_id, text))
        return SendResult(provider_message_id=f"pr.{len(self.private_replies)}")

    async def fetch_media(self, token: str, media_id: str) -> MediaInfo | None:
        return self.media.get(media_id)


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """`X-Hub-Signature-256: sha256=<hex>` — app secret bilan HMAC, doimiy vaqtda solishtiriladi."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


COMMENT_TEXT_MAX = 2200  # Instagram izohining chegarasi


def _from_epoch(stamp: object, *, millis: bool = False) -> datetime | None:
    """Epoch → UTC vaqt; bo'sh/noto'g'ri berilsa hozir, hayotiy bo'lmagan (juda katta) qiymat — `None`."""
    if not isinstance(stamp, int | float) or isinstance(stamp, bool):
        return datetime.now(UTC)
    try:
        return datetime.fromtimestamp(stamp / 1000 if millis else stamp, UTC)
    except (OverflowError, OSError, ValueError):
        return None


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
            occurred = _from_epoch(stamp, millis=True)
            if occurred is None:
                continue  # hayotiy bo'lmagan vaqt: hodisa e'tiborsiz, yetkazib berish 200
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


def parse_comment_events(payload: dict[str, Any]) -> list[tuple[str, InboundComment]]:
    """Meta `entry[].changes[]` (`field = comments`) → (professional akkaunt id, izoh). Dedup kaliti — izoh
    id'si (o'chirish alohida kalit). Buzuq element e'tiborsiz."""
    result: list[tuple[str, InboundComment]] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        account_id = str(entry.get("id") or "")
        entry_time = entry.get("time")
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "comments":
                continue
            value = change.get("value")
            if not isinstance(value, dict) or not account_id:
                continue
            author, media = value.get("from"), value.get("media")
            comment_id = value.get("id")
            if not isinstance(author, dict) or not isinstance(media, dict) or not isinstance(comment_id, str):
                continue
            if not author.get("id") or not media.get("id"):
                continue
            stamp = value.get("created_time") or entry_time
            occurred = _from_epoch(stamp)
            if occurred is None:
                continue  # hayotiy bo'lmagan created_time: faqat shu izoh e'tiborsiz (200)
            text = value.get("text") if isinstance(value.get("text"), str) else None
            parent = value.get("parent_id")
            username = author.get("username") if isinstance(author.get("username"), str) else None
            raw_fields = (comment_id, str(author["id"]), str(media["id"]), username, text)
            if any(f is not None and "\x00" in f for f in raw_fields):
                continue  # NUL baytni PostgreSQL saqlamaydi: faqat shu izoh tushiriladi
            if text is not None:
                text = text[:COMMENT_TEXT_MAX]
            removed = value.get("verb") == "remove"
            result.append(
                (
                    account_id,
                    InboundComment(
                        provider_event_id=f"comment_removed:{comment_id}"
                        if removed
                        else f"comment:{comment_id}",
                        external_comment_id=comment_id,
                        external_media_id=str(media["id"]),
                        author_external_id=str(author["id"]),
                        author_username=username,
                        body=text,
                        occurred_at=occurred,
                        media_type=_media_type(media.get("media_product_type"), None),
                        parent_external_comment_id=parent if isinstance(parent, str) else None,
                        removed=removed,
                    ),
                )
            )
    return result
