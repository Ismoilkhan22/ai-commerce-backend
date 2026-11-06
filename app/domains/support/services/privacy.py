"""Xaridor ma'lumotini anonimlashtirish — support qismi (engineering/26 §2, db/support.md §7).

Ism, telefon (shifrlangan va xeshi) va izohlar matni tozalanadi; murojaat, raqam va holatlar hisobot uchun
qoladi. Faqat yakunlangan (rad etilgan yoki yopilgan) murojaatlar: jarayondagi murojaat ma'lumotini
o'chirish xizmatni buzadi — ular "o'tkazib yuborildi" deb qaytadi.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.support.models.orm import CaseNote, SupportCase
from app.domains.support.state_machine import CASE
from app.platform.audit.services.audit_service import AuditService
from app.shared.clock import utcnow
from app.shared.db.encryption import search_hmac
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

ERASED_NOTE = "[o'chirildi]"
FINISHED = ("REJECTED", "CLOSED")


@dataclass(frozen=True)
class ErasureSummary:
    erased: int
    skipped_active: int


class CasePrivacyService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def erase_customer(self, db: AsyncSession, actor: ActorContext, phone: str) -> ErasureSummary:
        digest = search_hmac(normalize_phone(phone))
        cases = list(
            (
                await db.execute(
                    select(SupportCase)
                    .where(
                        SupportCase.shop_id == actor.shop_id,
                        SupportCase.contact_phone_hmac == digest,
                        SupportCase.pii_erased_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        finished = [c for c in cases if c.status in FINISHED]
        for case in finished:
            case.customer_name = None
            case.contact_phone_enc = None
            case.contact_phone_hmac = None
            case.pii_erased_at = utcnow()
            await db.execute(
                update(CaseNote)
                .where(CaseNote.shop_id == case.shop_id, CaseNote.case_id == case.id)
                .values(body=ERASED_NOTE)
            )
        await db.flush()
        await self.audit.record(  # faqat sonlar, mazmunsiz (26 §2)
            db,
            action="support.case.pii_erased",
            entity_type=CASE,
            entity_id=None,
            actor=actor,
            diff={"cases": len(finished), "skipped_active": len(cases) - len(finished)},
        )
        return ErasureSummary(erased=len(finished), skipped_active=len(cases) - len(finished))


async def erase_customer_handler(db: AsyncSession, actor: ActorContext, phone: str) -> ErasureSummary:
    """`DomainManifest.privacy_handlers` uchun (26 §2)."""
    return await CasePrivacyService(AuditService()).erase_customer(db, actor, phone)
