""" "Instagram bilan ulash" (OAuth) — do'kon egasi token nusxalamaydi.

Panel `start` dan Meta havolasini oladi → Facebook oynasida Page va Instagram'ni tanlaydi → Meta
`callback` ga `code` bilan qaytaradi → kod tokenga, token uzun muddatliga almashtiriladi → odatdagi ulash
(`connect_instagram`: Page tokeni, akkaunt, obuna) → panelga qaytish. `state` — imzolangan (HMAC), 10 daqiqa:
shop, xodim va qaytish yo'li klientdan emas, imzodan olinadi.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from uuid import UUID

import structlog

from app.domains.messaging.channels.base import ChannelConnectError
from app.domains.messaging.channels.instagram import GRAPH_BASE
from app.domains.messaging.common import ChannelAdapters, MessagingConfig
from app.domains.messaging.services.channels import ChannelService
from app.shared.db.session import Database
from app.shared.errors.base import NotFoundError, ValidationError
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

STATE_TTL_SECONDS = 600
OAUTH_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_metadata",
    "pages_messaging",
    "business_management",
    "instagram_basic",
    "instagram_manage_comments",
    "instagram_manage_messages",
)
CALLBACK_PATH = "/api/v1/webhooks/instagram/oauth"
DELETION_PATH = "/api/v1/webhooks/instagram/data-deletion"
DEFAULT_RETURN = "/"


@dataclass(frozen=True)
class OAuthState:
    shop_id: UUID
    actor_id: UUID | None
    membership_id: UUID | None
    roles: tuple[str, ...]
    return_path: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_state(key: str, state: OAuthState, *, now: float | None = None) -> str:
    body = {
        "s": str(state.shop_id),
        "a": str(state.actor_id) if state.actor_id else None,
        "m": str(state.membership_id) if state.membership_id else None,
        "r": list(state.roles),
        "p": state.return_path,
        "e": int((now or time.time()) + STATE_TTL_SECONDS),
        "n": secrets.token_urlsafe(8),
    }
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    mac = _b64(hmac.new(key.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{mac}"


def read_state(key: str, token: str, *, now: float | None = None) -> OAuthState | None:
    raw, _, mac = token.partition(".")
    expected = _b64(hmac.new(key.encode(), raw.encode(), hashlib.sha256).digest())
    if not raw or not hmac.compare_digest(mac, expected):
        return None
    try:
        body = json.loads(_unb64(raw))
        if int(body["e"]) < (now or time.time()):
            return None
        return OAuthState(
            shop_id=UUID(body["s"]),
            actor_id=UUID(body["a"]) if body.get("a") else None,
            membership_id=UUID(body["m"]) if body.get("m") else None,
            roles=tuple(str(r) for r in body.get("r") or ()),
            return_path=safe_return_path(str(body.get("p") or "")),
        )
    except (ValueError, KeyError, TypeError):
        return None


def parse_signed_request(secret: str, signed_request: str) -> str | None:
    """Meta `signed_request` (`<imzo>.<payload>`, HMAC-SHA256 app siri bilan) → `user_id`; buzuq — `None`."""
    sig, _, payload = signed_request.partition(".")
    if not sig or not payload:
        return None
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(sig), expected):
            return None
        body = json.loads(_unb64(payload))
    except (ValueError, TypeError):
        return None
    user_id = body.get("user_id") if isinstance(body, dict) else None
    if body.get("algorithm", "HMAC-SHA256").upper() != "HMAC-SHA256" or not user_id:
        return None
    return str(user_id)


def deletion_code(key: str, user_id: str) -> str:
    """Tasdiq kodi: foydalanuvchi ID'si ochilmaydi, bir xil so'rov — bir xil kod."""
    return hmac.new(key.encode(), f"meta-deletion:{user_id}".encode(), hashlib.sha256).hexdigest()[:20]


def safe_return_path(path: str) -> str:
    """Faqat panel ichidagi nisbiy yo'l (ochiq yo'naltirish yo'q)."""
    if not path.startswith("/") or path.startswith("//") or "\\" in path or len(path) > 300:
        return DEFAULT_RETURN
    return path


class InstagramOAuth:
    def __init__(self, config: MessagingConfig, adapters: ChannelAdapters, channels: ChannelService) -> None:
        self.config = config
        self.adapters = adapters  # testlar soxta klientni almashtiradi — chaqiruv paytida olinadi
        self.channels = channels

    @property
    def available(self) -> bool:
        return bool(
            self.config.instagram_enabled
            and self.config.instagram_app_id
            and self.config.instagram_app_secret
        )

    @property
    def redirect_uri(self) -> str:
        return self.config.webhook_base_url.rstrip("/") + CALLBACK_PATH

    def start(self, actor: ActorContext, return_path: str) -> str:
        if not self.config.instagram_enabled:
            raise NotFoundError("Not found")
        if not self.available:
            raise ValidationError(
                "Instagram OAuth is not configured",
                fields=[{"field": "instagram", "code": "oauth_not_configured", "params": {}}],
            )
        assert actor.shop_id is not None
        state = sign_state(
            self.config.oauth_state_key,
            OAuthState(
                shop_id=actor.shop_id,
                actor_id=actor.actor_id,
                membership_id=actor.membership_id,
                roles=tuple(sorted(actor.roles)),
                return_path=safe_return_path(return_path),
            ),
        )
        params = {
            "client_id": self.config.instagram_app_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
        }
        if self.config.instagram_oauth_config_id:
            params["config_id"] = self.config.instagram_oauth_config_id
        else:
            params["scope"] = ",".join(OAUTH_SCOPES)
        version = GRAPH_BASE.rsplit("/", 1)[-1]
        return f"https://www.facebook.com/{version}/dialog/oauth?{urlencode(params)}"

    async def complete(self, database: Database, code: str | None, state_token: str | None) -> str:
        """Panelga qaytish manzili: `?instagram=connected` yoki `?instagram=error&reason=…`."""
        state = read_state(self.config.oauth_state_key, state_token or "")
        if state is None:
            return self._back(DEFAULT_RETURN, "error", "state")
        if not code or not self.available:
            return self._back(state.return_path, "error", "denied" if not code else "config")
        assert self.config.instagram_app_id and self.config.instagram_app_secret
        user_token = await self.adapters.instagram.exchange_code(
            code,
            redirect_uri=self.redirect_uri,
            app_id=self.config.instagram_app_id,
            app_secret=self.config.instagram_app_secret,
        )
        if user_token is None:
            return self._back(state.return_path, "error", "code")
        long_token = (
            await self.adapters.instagram.extend_token(
                user_token, app_id=self.config.instagram_app_id, app_secret=self.config.instagram_app_secret
            )
            or user_token
        )
        meta_user_id = await self.adapters.instagram.get_user_id(long_token)
        actor = ActorContext(
            actor_type="STAFF",
            actor_id=state.actor_id,
            shop_id=state.shop_id,
            surface="shop",
            roles=frozenset(state.roles),
            membership_id=state.membership_id,
        )
        try:
            async with database.transaction(state.shop_id) as db:
                await self.channels.connect_instagram(db, actor, long_token, meta_user_id=meta_user_id)
        except (ValidationError, ChannelConnectError):
            logger.warning("instagram.oauth.connect_failed", shop_id=str(state.shop_id))
            return self._back(state.return_path, "error", "account")
        logger.info("instagram.oauth.connected", shop_id=str(state.shop_id))
        return self._back(state.return_path, "connected", None)

    async def revoke(self, database: Database, signed_request: str | None) -> str | None:
        """Meta "Deauthorize" va "Data deletion" callback'lari: imzo app siri bilan tekshiriladi, shu Facebook
        foydalanuvchisi ulagan Instagram akkauntlari uziladi, token o'chiriladi. Natija — tasdiq kodi
        (imzo noto'g'ri bo'lsa `None`)."""
        secret = self.config.instagram_app_secret
        user_id = parse_signed_request(secret, signed_request) if secret and signed_request else None
        if user_id is None:
            return None
        async with database.transaction() as db:
            count = await self.channels.revoke_meta_user(db, user_id)
        code = deletion_code(self.config.oauth_state_key, user_id)
        logger.info("instagram.meta_user.revoked", accounts=count, confirmation_code=code)
        return code

    def deletion_status_url(self, code: str) -> str:
        return f"{self.config.webhook_base_url.rstrip('/')}{DELETION_PATH}/{code}"

    def _back(self, path: str, result: str, reason: str | None) -> str:
        query = {"instagram": result} | ({"reason": reason} if reason else {})
        joiner = "&" if "?" in path else "?"
        return f"{self.config.app_public_url.rstrip('/')}{path}{joiner}{urlencode(query)}"
