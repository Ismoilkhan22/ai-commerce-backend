"""Lead (FSM-05) va PC taklifi (FSM-06) — db/commerce_quotes.md, DEC-142 (taklif).

AI hech qachon tasdiqlamaydi va yubormaydi (DEC-100c, BL-110): APPROVE/SEND faqat xodim. AI qoralama
yaratadi (6b) — `AI_AGENT` faqat DRAFT bosqichidagi buyruqlarda.
"""

from __future__ import annotations

from app.shared.types.actor import ActorType
from app.shared.types.state import StateMachineRule

LEAD = "commerce.lead"
QUOTE = "commerce.quote"

STAFF: frozenset[ActorType] = frozenset({"STAFF"})
STAFF_OR_AI: frozenset[ActorType] = frozenset({"STAFF", "AI_AGENT"})
SYSTEM: frozenset[ActorType] = frozenset({"SYSTEM"})
STAFF_OR_SYSTEM: frozenset[ActorType] = frozenset({"STAFF", "SYSTEM"})
CUSTOMER_OR_STAFF: frozenset[ActorType] = frozenset({"CUSTOMER", "STAFF"})


def _lead(
    command: str, src: str, dst: str, actors: frozenset[ActorType] = STAFF, *, reason: bool = False
) -> StateMachineRule:
    return StateMachineRule(
        entity_type=LEAD,
        command=command,
        from_status=src,
        to_status=dst,
        actors=actors,
        requires_reason=reason,
        business_ref="FSM-05",
    )


def _quote(
    command: str, src: str, dst: str, actors: frozenset[ActorType] = STAFF, *, reason: bool = False
) -> StateMachineRule:
    return StateMachineRule(
        entity_type=QUOTE,
        command=command,
        from_status=src,
        to_status=dst,
        actors=actors,
        requires_reason=reason,
        business_ref="FSM-06",
    )


LEAD_RULES = [
    _lead("QUALIFY", "NEW", "QUALIFIED", STAFF_OR_AI),
    # Birinchi taklif yuborilganda — avtomatik (taklif yuborgan xodim nomidan)
    _lead("MARK_QUOTED", "NEW", "QUOTED"),
    _lead("MARK_QUOTED", "QUALIFIED", "QUOTED"),
    # Lead buyurtmasi topshirildi — event orqali (SYSTEM)
    _lead("WIN", "NEW", "WON", SYSTEM),
    _lead("WIN", "QUALIFIED", "WON", SYSTEM),
    _lead("WIN", "QUOTED", "WON", SYSTEM),
    _lead("LOSE", "NEW", "LOST", reason=True),
    _lead("LOSE", "QUALIFIED", "LOST", reason=True),
    _lead("LOSE", "QUOTED", "LOST", reason=True),
    _lead("REOPEN", "LOST", "QUALIFIED"),  # xaridor qaytdi
]

QUOTE_RULES = [
    _quote("SUBMIT", "DRAFT", "REVIEW", STAFF_OR_AI),
    _quote("AUTO_APPROVE", "DRAFT", "APPROVED", STAFF_OR_AI),  # RISKY_ONLY: PASS va chegirmasiz (DEC-102)
    _quote("APPROVE", "REVIEW", "APPROVED"),
    _quote("RETURN", "REVIEW", "DRAFT", reason=True),  # menejer qaytardi — yangi revision
    _quote("SEND", "APPROVED", "SENT"),
    _quote("ACCEPT", "SENT", "ACCEPTED", CUSTOMER_OR_STAFF),  # havola orqali yoki xodim qo'lda belgilaydi
    _quote("REJECT", "SENT", "REJECTED", CUSTOMER_OR_STAFF),
    _quote("EXPIRE", "SENT", "EXPIRED", SYSTEM),
    _quote("REVISE", "SENT", "DRAFT"),  # narx/moslik o'zgardi — yangi versiya, eski havola bekor
    _quote("REVISE", "REJECTED", "DRAFT"),
    _quote("REVISE", "EXPIRED", "DRAFT"),
    _quote("CANCEL", "DRAFT", "CANCELLED", STAFF_OR_SYSTEM),
    _quote("CANCEL", "REVIEW", "CANCELLED", STAFF_OR_SYSTEM),
    _quote("CANCEL", "APPROVED", "CANCELLED", STAFF_OR_SYSTEM),
    # Lead yo'qotildi (QA 6a F12) — ochiq takliflari bekor, havola o'chadi; yuborilgani ham
    _quote("LEAD_LOST", "DRAFT", "CANCELLED", STAFF_OR_SYSTEM),
    _quote("LEAD_LOST", "REVIEW", "CANCELLED", STAFF_OR_SYSTEM),
    _quote("LEAD_LOST", "APPROVED", "CANCELLED", STAFF_OR_SYSTEM),
    _quote("LEAD_LOST", "SENT", "CANCELLED", STAFF_OR_SYSTEM),
]
