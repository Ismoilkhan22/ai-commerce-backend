"""M30: hamkorlar uchun API kalitlari (BL-089) — Stage 2.

- Kalitni faqat ega yaratadi va bekor qiladi; sir faqat yaratilganda bir marta ko'rsatiladi, bazada HMAC xesh.
- Ruxsatlar: `catalog.read` (mahsulot va narx), `stock.read` (mavjudlik), `prices.write` (narx yozish).
- Har so'rov: prefix bo'yicha topiladi (`app.api_key_prefix`, RLS) → xesh doimiy vaqtda solishtiriladi →
  bekor qilingan / muddati o'tgan — 401; shop ACTIVE bo'lmasa — 403. Tezlik: kalitga 120/daqiqa (routes).
- Sizib chiqsa: ega "Bekor qilish" bosadi — keyingi so'rovdanoq ishlamaydi.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.network.models.orm import ApiKey
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.db.session import set_shop_context
from app.shared.errors.base import ForbiddenError, NotFoundError, UnauthenticatedError
from app.shared.types.actor import ActorContext

KEY = "network.api_key"
ApiScope = Literal["catalog.read", "stock.read", "prices.write", "stock.write"]
TOUCH_EVERY = timedelta(minutes=5)  # last_used_at har so'rovda yozilmaydi


class ApiKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    scopes: list[ApiScope] = Field(min_length=1, max_length=4)
    stock_auto_apply: bool = False  # M22: farq darhol qo'llansinmi (standart — tasdiqqa)
    expires_days: int | None = Field(default=365, ge=1, le=730)


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    stock_auto_apply: bool
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None
    active: bool


class ApiKeyCreatedOut(ApiKeyOut):
    secret: str  # faqat shu javobda; qayta ko'rsatilmaydi


class ApiKeyList(BaseModel):
    items: list[ApiKeyOut]


@dataclass(frozen=True)
class PartnerAuth:
    key_id: UUID
    shop_id: UUID
    scopes: frozenset[str]
    actor: ActorContext
    stock_auto_apply: bool = False
    created_by: UUID | None = None  # kalitni yaratgan ega — tashqi tuzatishlar uning nomidan (M22)


def _out(key: ApiKey) -> ApiKeyOut:
    now = utcnow()
    return ApiKeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=list(key.scopes),
        stock_auto_apply=key.stock_auto_apply,
        created_at=key.created_at.isoformat(),
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        revoked_at=key.revoked_at.isoformat() if key.revoked_at else None,
        active=key.revoked_at is None and (key.expires_at is None or key.expires_at > now),
    )


class ApiKeyService:
    def __init__(self, audit: AuditService, secret: str) -> None:
        self.audit = audit
        self._secret = secret.encode()

    def _hash(self, raw: str) -> str:
        return hmac.new(self._secret, f"api-key:{raw}".encode(), hashlib.sha256).hexdigest()

    async def create(self, db: AsyncSession, actor: ActorContext, data: ApiKeyIn) -> ApiKeyCreatedOut:
        assert actor.shop_id is not None
        prefix = secrets.token_hex(6)
        raw = f"cos_{prefix}_{secrets.token_urlsafe(32)}"
        key = ApiKey(
            shop_id=actor.shop_id,
            name=data.name.strip(),
            prefix=prefix,
            key_hash=self._hash(raw),
            scopes=sorted(set(data.scopes)),
            stock_auto_apply=data.stock_auto_apply,
            created_by=actor.membership_id,
            expires_at=utcnow() + timedelta(days=data.expires_days) if data.expires_days else None,
        )
        db.add(key)
        await db.flush()
        await db.refresh(key)
        await self.audit.record(
            db,
            action="network.api_key.created",
            entity_type=KEY,
            entity_id=key.id,
            actor=actor,
            diff={"scopes": key.scopes},
        )
        return ApiKeyCreatedOut(**_out(key).model_dump(), secret=raw)

    async def list_keys(self, db: AsyncSession, actor: ActorContext) -> ApiKeyList:
        rows = await db.execute(
            select(ApiKey).where(ApiKey.shop_id == actor.shop_id).order_by(ApiKey.created_at.desc())
        )
        return ApiKeyList(items=[_out(k) for k in rows.scalars()])

    async def revoke(
        self, db: AsyncSession, actor: ActorContext, key_id: UUID, reason: str | None
    ) -> ApiKeyOut:
        key = (
            await db.execute(
                select(ApiKey).where(ApiKey.shop_id == actor.shop_id, ApiKey.id == key_id).with_for_update()
            )
        ).scalar_one_or_none()
        if key is None:
            raise NotFoundError("API key not found")
        if key.revoked_at is None:
            key.revoked_at, key.revoke_reason = utcnow(), (reason or "OWNER").strip()[:200]
            await db.flush()
            await self.audit.record(
                db,
                action="network.api_key.revoked",
                entity_type=KEY,
                entity_id=key.id,
                actor=actor,
                reason=key.revoke_reason,
            )
        return _out(key)

    async def authenticate(self, db: AsyncSession, header: str | None) -> PartnerAuth:
        raw = (header or "").removeprefix("Bearer ").strip()
        parts = raw.split("_", 2)
        if len(parts) != 3 or parts[0] != "cos" or len(parts[1]) != 12:
            raise UnauthenticatedError("Invalid API key")
        await db.execute(text("SELECT set_config('app.api_key_prefix', :p, true)"), {"p": parts[1]})
        key = (await db.execute(select(ApiKey).where(ApiKey.prefix == parts[1]))).scalar_one_or_none()
        now = utcnow()
        if (
            key is None
            or not hmac.compare_digest(key.key_hash, self._hash(raw))
            or key.revoked_at is not None
            or (key.expires_at is not None and key.expires_at <= now)
        ):
            raise UnauthenticatedError("Invalid API key")
        await set_shop_context(db, key.shop_id)
        shop = await db.get(Shop, key.shop_id)
        if shop is None or shop.status != "ACTIVE":
            raise ForbiddenError("Shop is not active")
        if key.last_used_at is None or now - key.last_used_at > TOUCH_EVERY:
            key.last_used_at = now
        actor = ActorContext(
            actor_type="SYSTEM",
            actor_id=key.id,  # audit'da qaysi kalit qilgani ko'rinadi
            shop_id=key.shop_id,
            surface="webhooks",
            roles=frozenset(),
        )
        return PartnerAuth(
            key_id=key.id,
            shop_id=key.shop_id,
            scopes=frozenset(key.scopes),
            actor=actor,
            stock_auto_apply=key.stock_auto_apply,
            created_by=key.created_by,
        )
