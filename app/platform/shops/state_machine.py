"""Shop akkaunti — FSM-01 (business/05 "Shop akkaunti"). Faollashtirishni platforma qiladi (DEC-122)."""

from __future__ import annotations

from app.shared.types.state import StateMachineRule

ENTITY = "platform.shop"


def _rule(command: str, src: str, dst: str, *actors: str, reason: bool = False) -> StateMachineRule:
    return StateMachineRule(
        entity_type=ENTITY,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset(actors),
        requires_reason=reason,
        business_ref="FSM-01",
    )


SHOP_RULES = [
    _rule("SUBMIT_FOR_VERIFICATION", "DRAFT", "PENDING_VERIFICATION", "STAFF", "PLATFORM"),
    _rule("ACTIVATE", "PENDING_VERIFICATION", "ACTIVE", "PLATFORM"),
    _rule("SUSPEND", "ACTIVE", "SUSPENDED", "PLATFORM", reason=True),
    _rule("REACTIVATE", "SUSPENDED", "ACTIVE", "PLATFORM", reason=True),
    _rule("CLOSE", "ACTIVE", "CLOSED", "PLATFORM", reason=True),
]
