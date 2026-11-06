"""SalesDraftsPort (6b): AI sotuvchi tool'lari commerce qoralamalarini shu orqali yaratadi.

Faqat QORALAMA: lead (yangi yoki suhbatning ochiq leadi — talablar qo'shiladi), PC taklifi DRAFT
(narx katalogdan,
moslik commerce'da tekshiriladi), buyurtma DRAFT (band qilish yo'q). Tasdiqlash, yuborish, chegirma — yo'q
(BL-110, DEC-142 Q4). Aktor `AI_AGENT`: ruxsatlarsiz, faqat shu suhbat bo'yicha.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.orders.schemas import OrderCreate, OrderLineIn
from app.domains.commerce.orders.services.order_service import OrderService
from app.domains.commerce.quotes.schemas import LeadCreate, QuoteCreate, QuoteLineIn, Requirements
from app.domains.commerce.quotes.services.lead_service import LeadService
from app.domains.commerce.quotes.services.quote_service import QuoteService
from app.shared.contracts.commerce import DraftLine, DraftRef
from app.shared.types.actor import ActorContext

_REQUIREMENT_KEYS = ("budget_minor", "workloads", "monitor_needed", "brand_prefs", "notes")


class SalesDraftsPortImpl:
    def __init__(self, leads: LeadService, quotes: QuoteService, orders: OrderService) -> None:
        self.leads = leads
        self.quotes = quotes
        self.orders = orders

    async def capture_lead(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        requirements: dict[str, Any],
        idempotency_key: str,
    ) -> DraftRef:
        assert actor.shop_id is not None
        req = Requirements.model_validate({k: v for k, v in requirements.items() if k in _REQUIREMENT_KEYS})
        existing = await self.leads.open_for_conversation(db, actor.shop_id, conversation_id)
        if existing is not None:
            merged = {**(existing.requirements or {}), **req.model_dump(mode="json", exclude_none=True)}
            existing.requirements = merged
            if merged.get("budget_minor") is not None:
                existing.budget_minor = merged["budget_minor"]
            await db.flush()
            return DraftRef("LEAD", existing.id, existing.number, existing.status, f"L-{existing.number}")
        lead = await self.leads.create(
            db,
            actor,
            LeadCreate(conversation_id=conversation_id, requirements=req),
            source="AI",
            ai_request_id=idempotency_key[:120],
        )
        return DraftRef("LEAD", lead.id, lead.number, lead.status, f"L-{lead.number}")

    async def prepare_quote_draft(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        lines: Sequence[DraftLine],
    ) -> DraftRef:
        out = await self.quotes.create(
            db,
            actor,
            QuoteCreate(
                conversation_id=conversation_id,
                lines=[QuoteLineIn(sku_id=line.sku_id, qty=line.qty) for line in lines],
            ),
        )
        return DraftRef("QUOTE", out.id, out.number, out.status, f"T-{out.number}")

    async def create_order_draft(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        conversation_id: UUID,
        customer_ref: UUID,
        customer_phone: str | None,
        customer_locale: str,
        lines: Sequence[DraftLine],
        fulfillment_method: str,
        branch_id: UUID | None,
    ) -> DraftRef:
        out = await self.orders.create(
            db,
            actor,
            OrderCreate(
                customer_phone=customer_phone,
                customer_locale=customer_locale if customer_locale in ("uz", "ru", "en") else "uz",
                fulfillment_method=fulfillment_method,
                branch_id=branch_id,
                lines=[OrderLineIn(sku_id=line.sku_id, qty=line.qty) for line in lines],
            ),
            conversation_id=conversation_id,
            customer_ref=customer_ref,
        )
        return DraftRef("ORDER", out.id, out.number, out.status, f"#{out.number}")
