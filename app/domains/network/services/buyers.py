"""Xaridor akkaunti (Stage 3 davomi): SMS kod bilan kirish va saqlanadigan tarix — db/marketplace.md.

```
start {phone}             ──▶ SMS kod (6 raqam, 10 daqiqa; qayta yuborish 60 soniyadan keyin)
verify {request_id, code} ──▶ xaridor (birinchi kirishda yaratiladi) + sessiya tokeni (60 kun, sirpanuvchi)
Authorization: Bearer <session_id>.<sir>  ──▶ bazada faqat sirning sha256 xeshi
```

Kirish mantig'i shop ro'yxatdan o'tishi (`signup_service`) bilan bir xil: noto'g'ri kod xato sifatida
QAYTARILADI (urinish hisoblagichi commit bo'lsin). Telefon HMAC (qidirish) + shifrlangan qiymat; telefon,
kod va token logga yozilmaydi (telefonning oxirgi 4 raqamidan ko'pi emas). Tarix yozuvlari (ko'rish, qidiruv,
maslahatchi) asosiy javobni hech qachon buzmaydi: alohida qisqa tranzaksiyada, xatosi faqat logga yoziladi.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import (
    Buyer,
    BuyerAdvisorMessage,
    BuyerFavorite,
    BuyerLoginCode,
    BuyerSearch,
    BuyerSession,
    BuyerView,
)
from app.platform.sms.sender import FakeSmsSender, SmsError, SmsSender
from app.shared.clock import utcnow
from app.shared.db.encryption import search_hmac
from app.shared.db.session import Database
from app.shared.errors.base import (
    NotFoundError,
    ProviderUnavailableError,
    RateLimitedError,
    ValidationError,
)
from app.shared.phone import normalize_phone

logger = structlog.get_logger(__name__)

CODE_TTL = timedelta(minutes=10)
RESEND_AFTER = timedelta(seconds=60)
MAX_ATTEMPTS = 5
MAX_SENDS = 5  # bitta so'rovga
MAX_REQUESTS_PER_DAY = 5  # bitta telefonga
SESSION_TTL = timedelta(days=60)
SESSION_BUMP_AFTER = timedelta(days=1)
MAX_VIEWS = 200
MAX_SEARCHES = 100
MAX_FAVORITES = 200
MAX_ADVISOR_MESSAGES = 200
ADVISOR_SHOWN = 100
CODES_KEEP = timedelta(days=1)
SESSIONS_KEEP = timedelta(days=7)  # muddati o'tgan yoki bekor qilingan sessiya shuncha turadi


class BuyerStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=9, max_length=20)


class BuyerStartOut(BaseModel):
    request_id: UUID
    resend_after_seconds: int
    expires_in_seconds: int
    dev_code: str | None  # faqat FakeSmsSender (lokal, e2e); haqiqiy SMS'da doim null


class BuyerVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class BuyerOut(BaseModel):
    id: UUID
    phone_masked: str
    name: str | None
    locale: str
    created_at: datetime


class BuyerVerifyOut(BaseModel):
    session_token: str
    expires_at: datetime
    buyer: BuyerOut


class BuyerPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=80)
    locale: str | None = Field(default=None, pattern=r"^(uz|ru|en)$")


@dataclass(frozen=True)
class BuyerCtx:
    buyer_id: UUID
    session_id: UUID


def mask_phone(phone: str) -> str:
    """'+998901234567' → '+998 90 *** ** 67'."""
    if len(phone) != 13:
        return "***"
    return f"{phone[:4]} {phone[4:6]} *** ** {phone[-2:]}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def phone_hash(phone: str) -> str:
    return search_hmac(f"buyer-phone:{phone}")


class BuyerService:
    def __init__(self, sms: SmsSender, secret: str) -> None:
        self.sms = sms
        self.secret = secret

    def _code_hash(self, request_id: UUID, code: str) -> str:
        return hmac.new(
            self.secret.encode(), f"buyer:{request_id}:{code}".encode(), hashlib.sha256
        ).hexdigest()

    # ------------------------------------------------------------------ 1. kod
    async def start(self, db: AsyncSession, phone_raw: str, ip: str) -> BuyerStartOut:
        phone = normalize_phone(phone_raw)
        digest = phone_hash(phone)
        now = utcnow()
        today = await db.scalar(
            select(func.count()).where(
                BuyerLoginCode.phone_hash == digest, BuyerLoginCode.created_at > now - timedelta(days=1)
            )
        )
        current = (
            await db.execute(
                select(BuyerLoginCode)
                .where(
                    BuyerLoginCode.phone_hash == digest,
                    BuyerLoginCode.consumed_at.is_(None),
                    BuyerLoginCode.expires_at > now,
                    BuyerLoginCode.attempts < MAX_ATTEMPTS,
                )
                .order_by(BuyerLoginCode.created_at.desc())
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
            raise RateLimitedError("Too many login attempts", retry_after_seconds=3600)
        if current is not None and current.sends >= MAX_SENDS:
            raise RateLimitedError("Too many codes", retry_after_seconds=3600)
        code = f"{secrets.randbelow(10**6):06d}"
        if current is None:
            current = BuyerLoginCode(
                phone_hash=digest,
                phone_enc=phone,
                code_hash="",
                expires_at=now + CODE_TTL,
                ip_hash=_sha(ip)[:32],
            )
            db.add(current)
            await db.flush()
        else:
            current.sends += 1
            current.last_sent_at, current.expires_at = now, now + CODE_TTL
        current.code_hash = self._code_hash(current.id, code)
        await db.flush()
        try:
            await self.sms.send(phone, f"AI Commerce: kirish kodi {code}. Uni hech kimga bermang.")
        except SmsError as exc:
            logger.warning("buyer.sms_failed", code=exc.code)
            raise ProviderUnavailableError("SMS could not be sent", provider="sms") from exc
        return BuyerStartOut(
            request_id=current.id,
            resend_after_seconds=int(RESEND_AFTER.total_seconds()),
            expires_in_seconds=int(CODE_TTL.total_seconds()),
            dev_code=code if isinstance(self.sms, FakeSmsSender) else None,
        )

    # ------------------------------------------------------------------ 2. tasdiq
    async def verify(
        self, db: AsyncSession, request_id: UUID, code: str, user_agent: str | None
    ) -> BuyerVerifyOut | ValidationError:
        """Noto'g'ri kod — xato QAYTARILADI (tashlanmaydi): urinish hisoblagichi COMMIT bo'lishi uchun."""
        row = await db.get(BuyerLoginCode, request_id, with_for_update=True)
        now = utcnow()
        if (
            row is None
            or row.consumed_at is not None
            or row.expires_at <= now
            or row.attempts >= MAX_ATTEMPTS
            or row.phone_enc is None
        ):
            raise NotFoundError("Login request expired", reason="expired")
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
        phone = row.phone_enc
        row.consumed_at, row.phone_enc = now, None
        buyer = (
            await db.execute(select(Buyer).where(Buyer.phone_hash == row.phone_hash))
        ).scalar_one_or_none()
        if buyer is None:
            buyer = Buyer(phone_hash=row.phone_hash, phone_enc=phone, last_seen_at=now)
            db.add(buyer)
            await db.flush()
            await db.refresh(buyer)  # server_default (created_at, locale)
            logger.info("buyer.created", buyer_id=str(buyer.id))
        else:
            buyer.last_seen_at = now
        secret = secrets.token_urlsafe(32)
        session = BuyerSession(
            buyer_id=buyer.id,
            token_hash=_sha(secret),
            expires_at=now + SESSION_TTL,
            user_agent=(user_agent or "")[:300] or None,
            last_used_at=now,
        )
        db.add(session)
        await db.flush()
        return BuyerVerifyOut(
            session_token=f"{session.id}.{secret}",
            expires_at=session.expires_at,
            buyer=self._out(buyer, phone),
        )

    # ------------------------------------------------------------------ 3. sessiya
    async def authenticate(self, database: Database, token: str) -> BuyerCtx | None:
        """Yaroqli token → xaridor; yaroqsiz, muddati o'tgan yoki bekor qilingan → None (xato tashlanmaydi).
        Sirpanuvchi muddat: `last_used_at` 1 kundan eski bo'lsa, `expires_at` surilib yangilanadi."""
        sid, _, secret = token.partition(".")
        try:
            session_id = UUID(sid)
        except ValueError:
            return None
        if not secret or len(token) > 200:
            return None
        now = utcnow()
        async with database.transaction() as db:
            row = await db.get(BuyerSession, session_id)
            if (
                row is None
                or row.revoked_at is not None
                or row.expires_at <= now
                or not hmac.compare_digest(row.token_hash, _sha(secret))
            ):
                return None
            if now - row.last_used_at > SESSION_BUMP_AFTER:
                row.last_used_at, row.expires_at = now, now + SESSION_TTL
                await db.execute(update(Buyer).where(Buyer.id == row.buyer_id).values(last_seen_at=now))
            return BuyerCtx(buyer_id=row.buyer_id, session_id=row.id)

    @staticmethod
    async def logout(db: AsyncSession, ctx: BuyerCtx) -> None:
        row = await db.get(BuyerSession, ctx.session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = utcnow()

    # ------------------------------------------------------------------ 4. profil
    @staticmethod
    def _out(buyer: Buyer, phone: str) -> BuyerOut:
        return BuyerOut(
            id=buyer.id,
            phone_masked=mask_phone(phone),
            name=buyer.name,
            locale=buyer.locale,
            created_at=buyer.created_at,
        )

    async def me(self, db: AsyncSession, ctx: BuyerCtx) -> BuyerOut:
        buyer = await db.get(Buyer, ctx.buyer_id)
        if buyer is None:
            raise NotFoundError("Buyer not found")
        return self._out(buyer, buyer.phone_enc)

    async def patch(self, db: AsyncSession, ctx: BuyerCtx, data: BuyerPatchIn) -> BuyerOut:
        buyer = await db.get(Buyer, ctx.buyer_id)
        if buyer is None:
            raise NotFoundError("Buyer not found")
        fields = data.model_fields_set
        if "name" in fields:
            buyer.name = (data.name or "").strip() or None
        if "locale" in fields and data.locale is not None:
            buyer.locale = data.locale
        await db.flush()
        return self._out(buyer, buyer.phone_enc)

    @staticmethod
    async def delete_account(db: AsyncSession, ctx: BuyerCtx) -> None:
        """Qattiq o'chirish: xaridor va hamma bog'liq jadvallar (cascade). Logda shaxsiy ma'lumot yo'q."""
        await db.execute(delete(Buyer).where(Buyer.id == ctx.buyer_id))
        logger.info("buyer.deleted", buyer_id=str(ctx.buyer_id))

    # ------------------------------------------------------------------ 5. tarix yozuvlari
    async def record_view(self, database: Database, buyer_id: UUID, canonical_id: UUID) -> None:
        async def work(db: AsyncSession) -> None:
            now = utcnow()
            await db.execute(
                pg_insert(BuyerView)
                .values(buyer_id=buyer_id, canonical_id=canonical_id, viewed_at=now)
                .on_conflict_do_update(
                    index_elements=[BuyerView.buyer_id, BuyerView.canonical_id], set_={"viewed_at": now}
                )
            )
            keep = (
                select(BuyerView.canonical_id)
                .where(BuyerView.buyer_id == buyer_id)
                .order_by(BuyerView.viewed_at.desc())
                .limit(MAX_VIEWS)
            )
            await db.execute(
                delete(BuyerView).where(BuyerView.buyer_id == buyer_id, BuyerView.canonical_id.not_in(keep))
            )

        await self._safe(database, "view", work)

    async def record_search(
        self, database: Database, buyer_id: UUID, query: str, category: str | None
    ) -> None:
        async def work(db: AsyncSession) -> None:
            last = (
                await db.execute(
                    select(BuyerSearch.query, BuyerSearch.category)
                    .where(BuyerSearch.buyer_id == buyer_id)
                    .order_by(BuyerSearch.searched_at.desc(), BuyerSearch.id.desc())
                    .limit(1)
                )
            ).first()
            if last is not None and last.query == query and last.category == category:
                return
            db.add(BuyerSearch(buyer_id=buyer_id, query=query, category=category, searched_at=utcnow()))
            await db.flush()
            keep = (
                select(BuyerSearch.id)
                .where(BuyerSearch.buyer_id == buyer_id)
                .order_by(BuyerSearch.searched_at.desc(), BuyerSearch.id.desc())
                .limit(MAX_SEARCHES)
            )
            await db.execute(
                delete(BuyerSearch).where(BuyerSearch.buyer_id == buyer_id, BuyerSearch.id.not_in(keep))
            )

        await self._safe(database, "search", work)

    async def record_advisor(
        self, database: Database, buyer_id: UUID, question: str, answer: str, sources: list[dict[str, Any]]
    ) -> None:
        async def work(db: AsyncSession) -> None:
            now = utcnow()
            db.add(BuyerAdvisorMessage(buyer_id=buyer_id, role="user", text=question, created_at=now))
            db.add(
                BuyerAdvisorMessage(
                    buyer_id=buyer_id,
                    role="assistant",
                    text=answer,
                    sources=sources,
                    created_at=now + timedelta(milliseconds=1),
                )
            )
            await db.flush()
            keep = (
                select(BuyerAdvisorMessage.id)
                .where(BuyerAdvisorMessage.buyer_id == buyer_id)
                .order_by(BuyerAdvisorMessage.created_at.desc(), BuyerAdvisorMessage.id.desc())
                .limit(MAX_ADVISOR_MESSAGES)
            )
            await db.execute(
                delete(BuyerAdvisorMessage).where(
                    BuyerAdvisorMessage.buyer_id == buyer_id, BuyerAdvisorMessage.id.not_in(keep)
                )
            )

        await self._safe(database, "advisor", work)

    @staticmethod
    async def _safe(database: Database, kind: str, work: Any) -> None:
        try:
            async with database.transaction() as db:
                await work(db)
        except Exception:  # tarix yozilmasa ham asosiy javob ketadi
            logger.warning("buyer.record_failed", kind=kind, exc_info=True)

    # ------------------------------------------------------------------ 6. sevimlilar
    @staticmethod
    async def is_favorite(db: AsyncSession, buyer_id: UUID, canonical_id: UUID) -> bool:
        found = await db.scalar(
            select(func.count()).where(
                BuyerFavorite.buyer_id == buyer_id, BuyerFavorite.canonical_id == canonical_id
            )
        )
        return bool(found)

    # ------------------------------------------------------------------ 7. kunlik tozalash
    @staticmethod
    async def cleanup(db: AsyncSession) -> int:
        """Bir kundan eski kodlar; muddati o'tganiga yoki bekor qilinganiga 7 kundan oshgan sessiyalar."""
        now = utcnow()
        codes = await db.execute(delete(BuyerLoginCode).where(BuyerLoginCode.created_at < now - CODES_KEEP))
        cutoff = now - SESSIONS_KEEP
        sessions = await db.execute(
            delete(BuyerSession).where(
                (BuyerSession.expires_at < cutoff)
                | (BuyerSession.revoked_at.is_not(None) & (BuyerSession.revoked_at < cutoff))
            )
        )
        return int(codes.rowcount or 0) + int(sessions.rowcount or 0)  # type: ignore[attr-defined]
