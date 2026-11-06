"""M21: shopning o'zi ro'yxatdan o'tishi (Stage 2) — `FEATURE_SELF_SIGNUP` ostida, standart o'chiq.

```
start {phone}             ──▶ SMS kod (6 raqam, 10 daqiqa; qayta yuborish 60 soniyadan keyin)
verify {request_id, code} ──▶ imzolangan token (30 daqiqa; 5 noto'g'ri urinishdan keyin yopiladi)
complete {token, shop, STIR, ega, parol} ──▶ shop DRAFT (signup_source=SELF) + ega ACTIVE + sessiya
```

Firibgarlikdan himoya: telefon SMS bilan tasdiqlanadi; STIR majburiy va noyob; IP va telefon bo'yicha limit
(routes); shop DRAFT — ACTIVE bo'lishi uchun ega profilni to'ldirib "tekshiruvga yuboradi", platforma admini
tasdiqlaydi (FSM-01 o'zgarmagan). Telefon allaqachon ro'yxatda bo'lsa, `start` farqini oshkor qilmaydi —
xato faqat `complete` da (kod egasiga). Kod va parol logga yozilmaydi.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.passwords import validate_new_password
from app.platform.auth.services.auth_service import AuthService, IssuedTokens
from app.platform.shops.models.orm import Shop, ShopPolicy, SignupRequest
from app.platform.shops.services.shop_service import RESERVED_SLUGS
from app.platform.sms.sender import SmsError, SmsSender
from app.platform.staff.models.orm import Membership, Principal
from app.shared.clock import utcnow
from app.shared.db.session import set_identity_context
from app.shared.errors.base import (
    FeatureNotAvailableError,
    NotFoundError,
    ProviderUnavailableError,
    RateLimitedError,
    ValidationError,
)
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

CODE_TTL = timedelta(minutes=10)
RESEND_AFTER = timedelta(seconds=60)
MAX_ATTEMPTS = 5
MAX_SENDS = 5  # bitta so'rovga
MAX_REQUESTS_PER_DAY = 5  # bitta telefonga
TOKEN_TTL_SECONDS = 1800
SLUG_MAX = 40

Locale = str


class SignupStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=9, max_length=20)


class SignupStartOut(BaseModel):
    request_id: UUID
    resend_after_seconds: int
    expires_in_seconds: int


class SignupVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class SignupVerifyOut(BaseModel):
    signup_token: str
    expires_in_seconds: int


class SignupCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signup_token: str = Field(max_length=1000)
    shop_name: str = Field(min_length=2, max_length=120)
    tin: str = Field(pattern=r"^[0-9]{9}$")
    owner_full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=1, max_length=128)
    default_locale: str = Field(default="uz", pattern=r"^(uz|ru|en)$")


@dataclass(frozen=True)
class SignupConfig:
    enabled: bool
    secret: str  # signup token imzosi (jwt siri)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "j",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "x",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sh",
        "ъ": "",
        "ы": "i",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "ў": "o",
        "қ": "q",
        "ғ": "g",
        "ҳ": "h",
        "'": "",
        "`": "",
        "ʻ": "",
        "ʼ": "",
        "’": "",
    }
)


def slug_base(name: str) -> str:
    """ "Noutbuk Uz" → "noutbuk-uz"; kirill → lotin; 3…40 belgi, `_SLUG` qoidasiga mos."""
    text = unicodedata.normalize("NFKD", name.lower().translate(_TRANSLIT))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:SLUG_MAX].strip("-")
    return text if len(text) >= 3 else f"shop-{text}".strip("-")


class SignupService:
    def __init__(self, config: SignupConfig, sms: SmsSender, auth: AuthService, audit: AuditService) -> None:
        self.config = config
        self.sms = sms
        self.auth = auth
        self.audit = audit

    def _require(self) -> None:
        if not self.config.enabled:
            raise FeatureNotAvailableError("Self signup is not available")

    def _code_hash(self, request_id: UUID, code: str) -> str:
        return hmac.new(
            self.config.secret.encode(), f"signup:{request_id}:{code}".encode(), hashlib.sha256
        ).hexdigest()

    # ------------------------------------------------------------------ 1. kod
    async def start(self, db: AsyncSession, phone_raw: str, ip: str) -> SignupStartOut:
        self._require()
        phone = normalize_phone(phone_raw)
        now = utcnow()
        today = await db.scalar(
            select(func.count()).where(
                SignupRequest.phone == phone, SignupRequest.created_at > now - timedelta(days=1)
            )
        )
        current = (
            await db.execute(
                select(SignupRequest)
                .where(
                    SignupRequest.phone == phone,
                    SignupRequest.consumed_at.is_(None),
                    SignupRequest.verified_at.is_(None),
                    SignupRequest.expires_at > now,
                    SignupRequest.attempts < MAX_ATTEMPTS,
                )
                .order_by(SignupRequest.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if current is not None and now - current.last_sent_at < RESEND_AFTER:
            raise RateLimitedError(
                "Code was sent recently",
                retry_after_seconds=int((RESEND_AFTER - (now - current.last_sent_at)).total_seconds()) + 1,
            )
        if current is None and int(today or 0) >= MAX_REQUESTS_PER_DAY:
            raise RateLimitedError("Too many signup attempts", retry_after_seconds=3600)
        if current is not None and current.sends >= MAX_SENDS:
            raise RateLimitedError("Too many codes", retry_after_seconds=3600)
        code = f"{secrets.randbelow(10**6):06d}"
        if current is None:
            current = SignupRequest(
                phone=phone,
                code_hash="",
                expires_at=now + CODE_TTL,
                ip_hash=hashlib.sha256(ip.encode()).hexdigest()[:32],
            )
            db.add(current)
            await db.flush()
        else:
            current.sends += 1
            current.last_sent_at, current.expires_at = now, now + CODE_TTL
        current.code_hash = self._code_hash(current.id, code)
        await db.flush()
        try:
            await self.sms.send(phone, f"AI Commerce: tasdiqlash kodi {code}. Uni hech kimga bermang.")
        except SmsError as exc:
            logger.warning("signup.sms_failed", code=exc.code)
            raise ProviderUnavailableError("SMS could not be sent", provider="sms") from exc
        return SignupStartOut(
            request_id=current.id,
            resend_after_seconds=int(RESEND_AFTER.total_seconds()),
            expires_in_seconds=int(CODE_TTL.total_seconds()),
        )

    # ------------------------------------------------------------------ 2. tasdiq
    async def verify(
        self, db: AsyncSession, request_id: UUID, code: str
    ) -> SignupVerifyOut | ValidationError:
        """Noto'g'ri kod — xato QAYTARILADI (tashlanmaydi): urinish hisoblagichi COMMIT bo'lishi uchun."""
        self._require()
        row = await db.get(SignupRequest, request_id, with_for_update=True)
        now = utcnow()
        if (
            row is None
            or row.consumed_at is not None
            or row.expires_at <= now
            or row.attempts >= MAX_ATTEMPTS
        ):
            raise NotFoundError("Signup request expired", reason="expired")
        if not hmac.compare_digest(row.code_hash, self._code_hash(row.id, code)):
            row.attempts += 1
            return ValidationError(
                "Wrong code",
                fields=[
                    {
                        "field": "code",
                        "code": "invalid",
                        "params": {"attempts_left": MAX_ATTEMPTS - row.attempts},
                    }
                ],
            )
        row.verified_at = row.verified_at or now
        body = {"r": str(row.id), "p": row.phone, "e": int(time.time()) + TOKEN_TTL_SECONDS}
        raw = _b64(json.dumps(body, separators=(",", ":")).encode())
        mac = _b64(
            hmac.new(self.config.secret.encode(), f"signup-token:{raw}".encode(), hashlib.sha256).digest()
        )
        return SignupVerifyOut(signup_token=f"{raw}.{mac}", expires_in_seconds=TOKEN_TTL_SECONDS)

    def _read_token(self, token: str) -> tuple[UUID, str]:
        raw, _, mac = token.partition(".")
        expected = _b64(
            hmac.new(self.config.secret.encode(), f"signup-token:{raw}".encode(), hashlib.sha256).digest()
        )
        try:
            if not raw or not hmac.compare_digest(mac, expected):
                raise ValueError("bad signature")
            body = json.loads(_unb64(raw))
            if int(body["e"]) < time.time():
                raise ValueError("expired")
            return UUID(body["r"]), str(body["p"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError(
                "Signup token is invalid", fields=[{"field": "signup_token", "code": "invalid", "params": {}}]
            ) from exc

    # ------------------------------------------------------------------ 3. shop va ega
    async def complete(
        self, db: AsyncSession, data: SignupCompleteIn, user_agent: str | None
    ) -> IssuedTokens:
        self._require()
        request_id, phone = self._read_token(data.signup_token)
        row = await db.get(SignupRequest, request_id, with_for_update=True)
        if row is None or row.phone != phone or row.verified_at is None or row.consumed_at is not None:
            raise ValidationError(
                "Signup token is invalid", fields=[{"field": "signup_token", "code": "invalid", "params": {}}]
            )
        validate_new_password(data.password, phone)
        if (await db.execute(select(Principal.id).where(Principal.phone == phone))).first():
            raise ValidationError(
                "Phone already registered", fields=[{"field": "phone", "code": "not_unique", "params": {}}]
            )
        if (await db.execute(select(Shop.id).where(Shop.tin == data.tin))).first():
            raise ValidationError(
                "TIN already used", fields=[{"field": "tin", "code": "not_unique", "params": {}}]
            )
        slug = await self._free_slug(db, slug_base(data.shop_name))
        now = utcnow()
        shop = Shop(
            slug=slug,
            name=data.shop_name.strip(),
            tin=data.tin,
            default_locale=data.default_locale,
            signup_source="SELF",
        )
        db.add(shop)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError as exc:  # bir vaqtda bir xil STIR yoki slug
            raise ValidationError(
                "TIN or name already used", fields=[{"field": "tin", "code": "not_unique", "params": {}}]
            ) from exc
        await set_identity_context(db, shop_id=shop.id)
        db.add(ShopPolicy(shop_id=shop.id))
        principal = Principal(
            phone=phone,
            full_name=data.owner_full_name.strip(),
            locale=data.default_locale,
            password_hash=await self.auth.hasher.hash(data.password),
            phone_verified_at=row.verified_at,
            last_login_at=now,
        )
        db.add(principal)
        await db.flush()
        owner = Membership(
            shop_id=shop.id, principal_id=principal.id, role="OWNER", status="ACTIVE", activated_at=now
        )
        db.add(owner)
        await db.flush()
        row.consumed_at, row.shop_id = now, shop.id
        actor = ActorContext(
            actor_type="STAFF",
            actor_id=principal.id,
            shop_id=shop.id,
            surface="shop",
            roles=frozenset({"OWNER"}),
            membership_id=owner.id,
        )
        await self.audit.record(
            db, action="shops.shop.self_signup", entity_type="platform.shop", entity_id=shop.id, actor=actor
        )
        logger.info("signup.completed", shop_id=str(shop.id))
        await set_identity_context(db, principal_id=principal.id)
        return await self.auth.open_shop_session(db, principal.id, shop.id, user_agent)

    @staticmethod
    async def _free_slug(db: AsyncSession, base: str) -> str:
        candidates = [base] + [f"{base[: SLUG_MAX - 5]}-{secrets.token_hex(2)}" for _ in range(5)]
        for candidate in candidates:
            if candidate in RESERVED_SLUGS:
                continue
            if not (await db.execute(select(Shop.id).where(Shop.slug == candidate))).first():
                return candidate
        raise ValidationError(
            "Shop name is taken", fields=[{"field": "shop_name", "code": "not_unique", "params": {}}]
        )
