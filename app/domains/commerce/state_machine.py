"""Buyurtma (FSM-08) va band qilish (FSM-07) — business/05 dagi strelkalar, DEC-134 bilan.

Aniq rol (operator / menejer / omborchi) — ruxsat qatlamida (permissions.py) va service'dagi "own" /
filial tekshiruvida. Qoldiq va pulga bog'liq holatlarni majburlab (force) o'zgartirib bo'lmaydi (04 §7).
"""

from __future__ import annotations

from app.shared.types.actor import ActorType
from app.shared.types.state import StateMachineRule

ORDER = "commerce.order"
RESERVATION = "commerce.reservation"

STAFF: frozenset[ActorType] = frozenset({"STAFF"})
STAFF_OR_CUSTOMER: frozenset[ActorType] = frozenset({"STAFF", "CUSTOMER"})


def _order(
    command: str, src: str, dst: str, actors: frozenset[ActorType] = STAFF, *, reason: bool = False
) -> StateMachineRule:
    return StateMachineRule(
        entity_type=ORDER,
        command=command,
        from_status=src,
        to_status=dst,
        actors=actors,
        requires_reason=reason,
        business_ref="FSM-08",
    )


def _reservation(command: str, src: str, dst: str) -> StateMachineRule:
    return StateMachineRule(
        entity_type=RESERVATION,
        command=command,
        from_status=src,
        to_status=dst,
        actors=STAFF,
        business_ref="FSM-07",
    )


ORDER_RULES = [
    _order("SUBMIT", "DRAFT", "PENDING_CONFIRMATION", STAFF_OR_CUSTOMER),  # xaridor saytda yuboradi (4-modul)
    _order("CONFIRM", "PENDING_CONFIRMATION", "CONFIRMED"),
    _order("START_PROCESSING", "CONFIRMED", "PROCESSING"),
    # "Olib ketishga tayyor": holat o'zgarmaydi, lekin kim va qachon — tarixda (FSM-08)
    _order("MARK_READY", "PROCESSING", "PROCESSING"),
    _order("COMPLETE", "PROCESSING", "COMPLETED"),
    _order("CANCEL", "DRAFT", "CANCELLED", STAFF_OR_CUSTOMER),
    _order("CANCEL", "PENDING_CONFIRMATION", "CANCELLED", reason=True),  # BL-049
    _order("CANCEL", "CONFIRMED", "CANCELLED", reason=True),
    _order("CANCEL", "EXCEPTION", "CANCELLED", reason=True),
    _order("RAISE_EXCEPTION", "PROCESSING", "EXCEPTION", reason=True),
    _order("RESOLVE_EXCEPTION", "EXCEPTION", "PROCESSING"),
    # 72 soatlik "bekor qilinsinmi?" vazifasidan menejer qarori (DEC-104, DEC-134)
    _order("EXPIRE", "CONFIRMED", "CANCELLED", reason=True),
    _order("EXPIRE", "PROCESSING", "CANCELLED", reason=True),
    _order("EXPIRE", "EXCEPTION", "CANCELLED", reason=True),  # muammoli buyurtma ham mahsulotni ushlab turadi
]

RESERVATION_RULES = [
    _reservation("ALLOCATE", "ACTIVE", "ALLOCATED"),
    _reservation("CONSUME", "ALLOCATED", "CONSUMED"),
    _reservation("RELEASE", "ACTIVE", "RELEASED"),
    _reservation("RELEASE", "ALLOCATED", "RELEASED"),
    _reservation("EXPIRE", "ACTIVE", "EXPIRED"),
    _reservation("EXPIRE", "ALLOCATED", "EXPIRED"),
]

# Band bor holatlar: majburlab kirib ham, chiqib ham bo'lmaydi — band bo'shatilmay qolardi (04 §7)
NON_FORCEABLE = {
    ORDER: frozenset({"CONFIRMED", "PROCESSING", "EXCEPTION", "COMPLETED"}),
    RESERVATION: frozenset({"ACTIVE", "ALLOCATED", "CONSUMED", "RELEASED", "EXPIRED"}),
}
