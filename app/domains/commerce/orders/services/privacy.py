"""Xaridor ma'lumotini anonimlashtirish — commerce qismi (engineering/26 §2, §6).

Ism, telefon (shifrlangan va xeshi), manzil, xaridor izohi va buyurtma izohlari matni tozalanadi; raqam,
qatorlar va summalar hisobot uchun qoladi. Faqat yakunlangan (topshirilgan yoki bekor qilingan) buyurtmalar:
jarayondagi buyurtmadan manzilni o'chirish yetkazishni buzadi — ular "o'tkazib yuborildi" deb qaytadi.

Muvofiqlashtirish (`platform/privacy` so'rovi → event → shu funksiya) — fon ishlari bilan (S0-06, 26 §2).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.orders.models.orm import Order, OrderNote
from app.domains.commerce.state_machine import ORDER
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.db.encryption import search_hmac
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

ERASED_NOTE = "[o'chirildi]"
FINISHED = ("COMPLETED", "CANCELLED")


@dataclass(frozen=True)
class ErasureSummary:
    erased: int  # anonimlashtirilgan buyurtmalar
    skipped_active: int  # hali yakunlanmagan — tegilmadi


class OrderPrivacyService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def erase_customer(self, db: AsyncSession, actor: ActorContext, phone: str) -> ErasureSummary:
        """Shu shopda shu telefon raqamli xaridorning yakunlangan buyurtmalari."""
        digest = search_hmac(normalize_phone(phone))
        orders = list(
            (
                await db.execute(
                    select(Order)
                    .where(
                        Order.shop_id == actor.shop_id,
                        Order.customer_phone_hmac == digest,
                        Order.pii_erased_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        finished = [o for o in orders if o.status in FINISHED]
        for order in finished:
            await self._erase(db, order)
        # Audit — faqat sonlar, mazmunsiz (26 §2)
        await self.audit.record(
            db,
            action="commerce.order.pii_erased",
            entity_type=ORDER,
            entity_id=None,
            actor=actor,
            diff={"orders": len(finished), "skipped_active": len(orders) - len(finished)},
        )
        return ErasureSummary(erased=len(finished), skipped_active=len(orders) - len(finished))

    async def _erase(self, db: AsyncSession, order: Order) -> None:
        order.customer_name = None
        order.customer_phone_enc = None
        order.customer_phone_hmac = None
        order.delivery_address_enc = None
        order.customer_comment = None
        order.pii_erased_at = utcnow()
        await db.execute(
            update(OrderNote)
            .where(OrderNote.shop_id == order.shop_id, OrderNote.order_id == order.id)
            .values(body=ERASED_NOTE)
        )
        await db.flush()


async def erase_customer_handler(db: AsyncSession, actor: ActorContext, phone: str) -> ErasureSummary:
    """`DomainManifest.privacy_handlers` uchun (26 §2): `platform/privacy` keyin shu orqali chaqiradi."""
    return await OrderPrivacyService(AuditService()).erase_customer(db, actor, phone)
