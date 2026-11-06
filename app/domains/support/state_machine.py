"""Kafolat murojaati (FSM-11, business/05) — db/support.md §1, DEC-145.

FSM-11 o'zgarmaydi: diagnostika `IN_REVIEW` ichida (`item_received_at`, `DIAGNOSIS` izohi), qaror turi —
`resolution` maydoni. Qabul/rad (`APPROVE`, `REJECT`) — faqat menejer/ega: bu ruxsat qatlamida
(`support.case.decide`), holat jadvalida emas. `CLOSE` — xaridor tasdiqlaganda xodim, 7 kundan keyin tizim.
"""

from __future__ import annotations

from app.shared.types.actor import ActorType
from app.shared.types.state import StateMachineRule

CASE = "support.case"

STAFF: frozenset[ActorType] = frozenset({"STAFF"})
STAFF_OR_SYSTEM: frozenset[ActorType] = frozenset({"STAFF", "SYSTEM"})


def _rule(
    command: str, src: str, dst: str, actors: frozenset[ActorType] = STAFF, *, reason: bool = False
) -> StateMachineRule:
    return StateMachineRule(
        entity_type=CASE,
        command=command,
        from_status=src,
        to_status=dst,
        actors=actors,
        requires_reason=reason,
        business_ref="FSM-11",
    )


CASE_RULES = [
    _rule("START_REVIEW", "NEW", "IN_REVIEW"),
    _rule("APPROVE", "IN_REVIEW", "APPROVED"),
    _rule("REJECT", "IN_REVIEW", "REJECTED", reason=True),  # sabab majburiy (kod yoki izoh)
    _rule("START_SERVICE", "APPROVED", "IN_SERVICE"),
    _rule("RESOLVE", "IN_SERVICE", "RESOLVED"),
    _rule("CLOSE", "RESOLVED", "CLOSED", STAFF_OR_SYSTEM),
]

# Ombor yozuvi bor holatlar: majburlab kirib ham, chiqib ham bo'lmaydi — karantin/almashtirish yozuvi
# tushib qolardi (04 §7)
NON_FORCEABLE = {CASE: frozenset({"IN_SERVICE", "RESOLVED"})}
