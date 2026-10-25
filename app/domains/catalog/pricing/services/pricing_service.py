"""Narx versiyalari va shop kursi (S1-03, BL-015, BL-016, DEC-121, DEC-133).

Narx o'zgarishi: joriy ko'rsatkich qulflanadi → `If-Match` tekshiriladi → yangi o'zgarmas qator →
ko'rsatkich yangi qatorga (CAS, 12 §3). Birinchi narx uchun `If-Match: "v0"` ("hali narx yo'q").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.pricing.models.orm import CurrentPrice, ExchangeRate, PriceVersion
from app.domains.catalog.pricing.schemas import (
    ExchangeRateIn,
    ExchangeRateList,
    ExchangeRateOut,
    PriceHistory,
    PriceHistoryItem,
)
from app.domains.catalog.products.models.orm import Product, Sku
from app.domains.catalog.products.schemas import PriceIn, PriceOut
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.errors.base import (
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from app.shared.http import check_version
from app.shared.money import Currency, to_uzs_minor
from app.shared.types.actor import ActorContext

RATE_MAX_AGE = timedelta(days=3)  # catalog.md §7: kurs 3 kundan eski bo'lsa — "eskirgan"
RATE_FUTURE_TOLERANCE = timedelta(minutes=5)
RATE_HISTORY_LIMIT = 30
PRICE_HISTORY_LIMIT = 100
SKU = "catalog.sku"


@dataclass(frozen=True)
class ActivePrice:
    current: CurrentPrice
    version: PriceVersion


def _currency(value: str) -> Currency:
    return "USD" if value == "USD" else "UZS"


def uzs_amount(pv: PriceVersion, rate: ExchangeRate | None) -> int | None:
    """Narx so'mda (tiyinda) — shop kursi bo'yicha, yaxlitlanmaydi (DEC-133). Kurs yo'q bo'lsa — None."""
    return to_uzs_minor(pv.amount_minor, _currency(pv.currency), rate.rate if rate else None)


def price_out(active: ActivePrice, rate: ExchangeRate | None) -> PriceOut:
    pv = active.version
    return PriceOut(
        price_version_id=pv.id,
        amount_minor=pv.amount_minor,
        currency=_currency(pv.currency),
        uzs_amount_minor=uzs_amount(pv, rate),
        version=active.current.version,
        updated_at=active.current.updated_at,
    )


def rate_out(rate: ExchangeRate, now: datetime) -> ExchangeRateOut:
    return ExchangeRateOut(
        id=rate.id,
        base="USD",
        quote="UZS",
        rate=rate.rate,
        source="CBU" if rate.source == "CBU" else "MANUAL",
        effective_at=rate.effective_at,
        created_at=rate.created_at,
        is_stale=rate.effective_at < now - RATE_MAX_AGE,
    )


class PricingService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    # ------------------------------------------------------------------ o'qish
    async def active_prices(
        self, db: AsyncSession, shop_id: UUID | None, sku_ids: list[UUID]
    ) -> dict[UUID, ActivePrice]:
        if not sku_ids or shop_id is None:
            return {}
        rows = await db.execute(
            select(CurrentPrice, PriceVersion)
            .join(
                PriceVersion,
                (PriceVersion.shop_id == CurrentPrice.shop_id)
                & (PriceVersion.id == CurrentPrice.price_version_id),
            )
            .where(CurrentPrice.shop_id == shop_id, CurrentPrice.sku_id.in_(sku_ids))
        )
        return {current.sku_id: ActivePrice(current, version) for current, version in rows}

    async def current_rate(self, db: AsyncSession, shop_id: UUID | None) -> ExchangeRate | None:
        """Joriy kurs — kuchga kirgan eng oxirgisi."""
        if shop_id is None:
            return None
        return (
            await db.execute(
                select(ExchangeRate)
                .where(ExchangeRate.shop_id == shop_id, ExchangeRate.effective_at <= utcnow())
                .order_by(ExchangeRate.effective_at.desc(), ExchangeRate.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def history(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> PriceHistory:
        await self._sku(db, actor, sku_id)
        rows = await db.execute(
            select(PriceVersion)
            .where(PriceVersion.shop_id == actor.shop_id, PriceVersion.sku_id == sku_id)
            .order_by(PriceVersion.created_at.desc(), PriceVersion.id.desc())
            .limit(PRICE_HISTORY_LIMIT)
        )
        return PriceHistory(items=[PriceHistoryItem.model_validate(r) for r in rows.scalars()])

    async def rates(self, db: AsyncSession, actor: ActorContext) -> ExchangeRateList:
        now = utcnow()
        rows = await db.execute(
            select(ExchangeRate)
            .where(ExchangeRate.shop_id == actor.shop_id)
            .order_by(ExchangeRate.effective_at.desc(), ExchangeRate.id.desc())
            .limit(RATE_HISTORY_LIMIT)
        )
        items = [rate_out(r, now) for r in rows.scalars()]
        current = next((r for r in items if r.effective_at <= now), None)
        return ExchangeRateList(
            current=current, items=items, max_age_hours=int(RATE_MAX_AGE.total_seconds() // 3600)
        )

    async def rate(self, db: AsyncSession, actor: ActorContext, rate_id: UUID) -> ExchangeRateOut:
        rate = (
            await db.execute(
                select(ExchangeRate).where(ExchangeRate.id == rate_id, ExchangeRate.shop_id == actor.shop_id)
            )
        ).scalar_one_or_none()
        if rate is None:
            raise NotFoundError("Exchange rate not found")
        return rate_out(rate, utcnow())

    # ------------------------------------------------------------------ yozish
    async def set_price(
        self, db: AsyncSession, actor: ActorContext, sku_id: UUID, expected_version: int, data: PriceIn
    ) -> PriceOut:
        sku = await self._sku(db, actor, sku_id)
        product = await db.get(Product, sku.product_id)
        if sku.status != "ACTIVE" or product is None or product.status == "ARCHIVED":
            raise InvalidTransitionError(
                "SKU is archived", entity=SKU, **{"from": "ARCHIVED"}, command="SET_PRICE"
            )
        active = await self.apply_price(db, actor, sku, data, expected_version)
        return price_out(active, await self.current_rate(db, actor.shop_id))

    async def apply_price(
        self, db: AsyncSession, actor: ActorContext, sku: Sku, data: PriceIn, expected_version: int
    ) -> ActivePrice:
        """Yangi narx versiyasi va joriy ko'rsatkich — mahsulot yaratishda ham shu yo'l (v0)."""
        current = (
            await db.execute(
                select(CurrentPrice)
                .where(CurrentPrice.shop_id == sku.shop_id, CurrentPrice.sku_id == sku.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        check_version(current.version if current else 0, expected_version)
        if current is not None:
            old = await db.get(PriceVersion, current.price_version_id)
            assert old is not None
            if old.amount_minor == data.amount_minor and old.currency == data.currency:
                return ActivePrice(current, old)  # narx o'zgarmadi — yangi versiya yozilmaydi
            changed = [
                name for name in ("amount_minor", "currency") if getattr(old, name) != getattr(data, name)
            ]
        else:
            changed = ["amount_minor", "currency"]
        version = PriceVersion(
            shop_id=sku.shop_id,
            sku_id=sku.id,
            amount_minor=data.amount_minor,
            currency=data.currency,
            reason=(data.reason or "").strip() or None,
            created_by=actor.membership_id,
        )
        db.add(version)
        await db.flush()
        if current is None:
            current = CurrentPrice(shop_id=sku.shop_id, sku_id=sku.id, price_version_id=version.id)
            db.add(current)
        else:
            current.price_version_id = version.id
        try:
            await db.flush()
        except IntegrityError as exc:  # ikki kishi bir vaqtda birinchi narxni qo'ydi
            raise VersionConflictError("Price changed concurrently", your_version=expected_version) from exc
        await db.refresh(current)
        await self.audit.record(
            db,
            action="catalog.price.changed",
            entity_type=SKU,
            entity_id=sku.id,
            actor=actor,
            entity_version=current.version,
            reason=version.reason,
            diff={"changed": changed},
        )
        # TODO(S0-06): outbox — `catalog.price.changed` event'i (05-events). Outbox jadvali fon ishlari
        # bilan qo'shiladi; ungacha sayt va AI narxni to'g'ridan catalog'dan o'qiydi.
        return ActivePrice(current, version)

    async def add_rate(self, db: AsyncSession, actor: ActorContext, data: ExchangeRateIn) -> ExchangeRateOut:
        now = utcnow()
        effective_at = data.effective_at or now
        if effective_at > now + RATE_FUTURE_TOLERANCE:
            raise ValidationError(
                "Rate cannot start in the future",
                fields=[{"field": "effective_at", "code": "max_value", "params": {"max": now.isoformat()}}],
            )
        rate = ExchangeRate(
            shop_id=actor.shop_id,
            rate=Decimal(data.rate),
            effective_at=effective_at,
            created_by=actor.membership_id,
        )
        db.add(rate)
        await db.flush()
        await db.refresh(rate)
        await self.audit.record(
            db,
            action="catalog.exchange_rate.set",
            entity_type="catalog.exchange_rate",
            entity_id=rate.id,
            actor=actor,
        )
        # TODO(S0-06): outbox — `catalog.exchange_rate.changed` (dollar narxlari so'mda qayta hisoblanadi)
        return rate_out(rate, now)

    async def _sku(self, db: AsyncSession, actor: ActorContext, sku_id: UUID) -> Sku:
        sku = (
            await db.execute(select(Sku).where(Sku.id == sku_id, Sku.shop_id == actor.shop_id))
        ).scalar_one_or_none()
        if sku is None:
            raise NotFoundError("SKU not found")
        return sku
