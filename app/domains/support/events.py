"""support event'lari (05 §8.5) — biznes o'zgarishi bilan bitta tranzaksiyada `support.outbox_events` ga.

Payload'da faqat ID, holat va kodlar: xaridor ismi, telefoni, muammo matni, izoh YO'Q (05 §3.1).
Ombor yozuvi event orqali emas: support tranzaksiyasida commerce port'i chaqiriladi (DEC-126), shuning
uchun holat va daftar bir COMMIT'da. Event — realtime signal, xaridorga xabar (messaging) va hisobot uchun.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.support.models.orm import SupportCase
from app.shared.events.outbox import write_outbox
from app.shared.types.actor import ActorContext

SCHEMA = "support"
CASE = "support.case"

OPENED = "support.case.opened"
STATUS_CHANGED = "support.case.status_changed"
RESOLVED = "support.case.resolved"
UPDATED = "support.case.updated"  # holat o'zgarmagan o'zgarish: qabul, qaror turi, mas'ul, izoh, rasm
READY_NOTICE = "support.case.ready_notice"  # xodim "Xaridorga xabar berish" bosdi


def case_payload(case: SupportCase, **extra: Any) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "number": case.number,
        "type": case.type,
        "status": case.status,
        "source": case.source,
        "resolution": case.resolution,
        "outcome": case.outcome,
        "reject_reason": case.reject_reason,  # kod (erkin matn emas)
        "refund_amount_minor": case.refund_amount_minor,  # hisobot (7c): ma'lumot uchun summa
        "qty": case.qty,
        "sku_id": case.sku_id,
        # Xaridorga xabar matni uchun mahsulot nomi: faqat sotuvdan olingan nusxa. Tashqi sotuvda nom xodim
        # yozgan erkin matn — event'ga tushmaydi
        "item_title": case.title_snapshot if case.source != "EXTERNAL" else None,
        "replacement_sku_id": case.replacement_sku_id,
        "branch_id": case.branch_id,
        "within_warranty": case.within_warranty,
        "opened_by": case.opened_by,
        "assigned_staff_id": case.assigned_membership_id,
        # Xaridorga xabar (messaging) shu suhbat va tilda — til kodi PII emas
        "conversation_id": case.conversation_id,
        "customer_locale": case.customer_locale,
        **extra,
    }


async def case_event(
    db: AsyncSession, actor: ActorContext, case: SupportCase, event_type: str, **extra: Any
) -> None:
    await db.flush()  # `aggregate_version` — shu o'zgarishdan KEYINGI versiya (05 §6)
    await write_outbox(
        db,
        schema=SCHEMA,
        event_type=event_type,
        actor=actor,
        shop_id=case.shop_id,
        aggregate_type=CASE,
        aggregate_id=case.id,
        aggregate_version=case.version,
        payload=case_payload(case, **extra),
    )
