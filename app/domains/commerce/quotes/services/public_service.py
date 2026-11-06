"""Xaridor havolasi `/q/{token}` (sayt domenida, anonim; DEC-142 Q5).

Token bazada yo'q — faqat SHA-256 xeshi (unikal); boshqa shop sayti orqali kelsa — 404. Javobda shaxsiy
ma'lumot yo'q: ism, telefon, xodim, ichki ID'lar ko'rsatilmaydi. Qabul — narx va moslik qayta tekshiriladi.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.orders.models.orm import Order
from app.domains.commerce.orders.services.storefront_service import customer_actor
from app.domains.commerce.quotes.common import PUBLIC_TOKEN, snapshot_out, token_hash
from app.domains.commerce.quotes.models.orm import Quote, QuoteCompatibilitySnapshot
from app.domains.commerce.quotes.schemas import (
    CompatibilityOut,
    PublicAcceptOut,
    PublicCompatibilityOut,
    PublicQuoteLine,
    PublicQuoteOut,
)
from app.domains.commerce.quotes.services.quote_service import QuoteService
from app.shared.clock import utcnow
from app.shared.errors.base import InvalidTransitionError, NotFoundError
from app.shared.i18n.locale import get_display_locale
from app.shared.i18n.translator import t

ORDER_TRACKING_PATH = "/orders/"
CUSTOMER_SEVERITIES = ("WARNING", "INFO")  # xaridorga foydali maslahatlar; BLOCK/REVIEW — ichki


def public_compatibility(internal: CompatibilityOut) -> PublicCompatibilityOut:
    """Xaridorga: ichki kutubxona so'zlari (MISSING_ATTRIBUTE, UNLINKED_PART, BIOS ro'yxati...) va dalil
    ko'rsatilmaydi (QA 6a F16). Tekshiruv kerak bo'lgan yig'mani mutaxassis tasdiqlagan — shuni aytamiz."""
    expert = internal.decision == "REVIEW_REQUIRED"
    findings = [f for f in internal.findings if f.severity in CUSTOMER_SEVERITIES]
    for finding in findings:
        finding.parts = []
    return PublicCompatibilityOut(
        decision=internal.decision,
        expert_checked=expert,
        note=t("compat.public.expert_checked", get_display_locale()) if expert else None,
        findings=findings,
        estimated_power_w=internal.estimated_power_w,
    )


@dataclass(frozen=True)
class Accepted:
    """Qabul natijasi: javob va buyurtma ID'si (takror himoyasi jadvaliga faqat ID yoziladi)."""

    out: PublicAcceptOut
    order_id: UUID


class PublicQuoteService:
    def __init__(self, quotes: QuoteService) -> None:
        self.quotes = quotes

    async def find(self, db: AsyncSession, shop_id: UUID, token: str, *, for_update: bool = False) -> Quote:
        if not PUBLIC_TOKEN.fullmatch(token):
            raise NotFoundError("Quote not found")
        wanted = token_hash(token)
        query = select(Quote).where(Quote.shop_id == shop_id, Quote.public_token_hash == wanted)
        if for_update:
            query = query.with_for_update()
        quote = (await db.execute(query)).scalar_one_or_none()
        if quote is None or not hmac.compare_digest(quote.public_token_hash or "", wanted):
            raise NotFoundError("Quote not found")
        return quote

    async def view(self, db: AsyncSession, shop_id: UUID, token: str) -> PublicQuoteOut:
        quote = await self.find(db, shop_id, token)
        revision = await self.quotes.revision(db, quote)
        lines = await self.quotes.lines(db, revision)
        snapshot = (
            (
                await db.execute(
                    select(QuoteCompatibilitySnapshot)
                    .where(
                        QuoteCompatibilitySnapshot.shop_id == shop_id,
                        QuoteCompatibilitySnapshot.quote_revision_id == revision.id,
                    )
                    .order_by(QuoteCompatibilitySnapshot.checked_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        compatibility = public_compatibility(snapshot_out(snapshot)) if snapshot else None
        status = quote.status
        if status == "SENT" and quote.expires_at is not None and quote.expires_at <= utcnow():
            status = "EXPIRED"  # rejali ish hali ulgurmagan bo'lsa ham xaridor eski narxni qabul qila olmaydi
        order_number = None
        if quote.accepted_order_id is not None:
            order_number = (
                await db.execute(
                    select(Order.number).where(Order.shop_id == shop_id, Order.id == quote.accepted_order_id)
                )
            ).scalar_one_or_none()
        return PublicQuoteOut(
            number=quote.number,
            status=status,
            lines=[
                PublicQuoteLine(
                    title=line.title_snapshot,
                    role=line.role,
                    qty=line.qty,
                    unit_price_uzs_minor=line.unit_price_uzs_minor,
                    discount_pct=line.discount_pct,
                    line_total_uzs_minor=line.line_total_uzs_minor,
                    warranty_months=line.warranty_months,
                )
                for line in lines
            ],
            subtotal_uzs_minor=revision.subtotal_uzs_minor,
            discount_uzs_minor=revision.discount_uzs_minor,
            total_uzs_minor=revision.total_uzs_minor,
            compatibility=compatibility,
            expires_at=quote.expires_at,
            accepted_at=quote.accepted_at,
            order_number=order_number,
        )

    async def accept(self, db: AsyncSession, shop_id: UUID, token: str) -> Accepted:
        quote = await self.find(db, shop_id, token, for_update=True)
        lead = await self.quotes.lead_of(db, quote)
        actor = customer_actor(shop_id)
        if quote.status == "ACCEPTED" and quote.accepted_order_id is not None:
            return await self.reissue(db, shop_id, quote.accepted_order_id)
        order = await self.quotes.accept_core(db, actor, quote, lead)
        token_out = await self.quotes.tracking_token(db, order)
        return Accepted(
            out=PublicAcceptOut(
                status="ACCEPTED", order_number=order.number, tracking_path=ORDER_TRACKING_PATH + token_out
            ),
            order_id=order.id,
        )

    async def reissue(self, db: AsyncSession, shop_id: UUID, order_id: UUID) -> Accepted:
        """Takroriy qabul (ikki marta bosish) — o'sha buyurtma, yangi holat havolasi (eskisi bekor)."""
        order = (
            await db.execute(select(Order).where(Order.shop_id == shop_id, Order.id == order_id))
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError("Order not found")
        token_out = await self.quotes.tracking_token(db, order)
        return Accepted(
            out=PublicAcceptOut(
                status="ACCEPTED", order_number=order.number, tracking_path=ORDER_TRACKING_PATH + token_out
            ),
            order_id=order.id,
        )

    async def reject(self, db: AsyncSession, shop_id: UUID, token: str, reason: str | None) -> PublicQuoteOut:
        quote = await self.find(db, shop_id, token, for_update=True)
        if quote.status != "SENT":
            raise InvalidTransitionError("Quote is not open", entity="commerce.quote", command="REJECT")
        # Muddati o'tgan bo'lsa — reject_core QUOTE_EXPIRED beradi (QA 6a F15)
        await self.quotes.reject_core(db, customer_actor(shop_id), quote, reason, by="CUSTOMER")
        return await self.view(db, shop_id, token)
