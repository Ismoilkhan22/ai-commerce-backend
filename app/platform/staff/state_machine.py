"""Xodim a'zoligi (business/05 "Xodim"). DISABLED → ACTIVE yo'q (ochiq savol, 04 §11)."""

from __future__ import annotations

from app.shared.types.state import StateMachineRule

ENTITY = "platform.membership"


def _rule(command: str, src: str, dst: str, *actors: str) -> StateMachineRule:
    return StateMachineRule(
        entity_type=ENTITY,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset(actors),
        business_ref="business/05 Xodim",
    )


MEMBERSHIP_RULES = [
    _rule("ACCEPT_INVITE", "INVITED", "ACTIVE", "STAFF"),
    _rule("DISABLE", "ACTIVE", "DISABLED", "STAFF", "PLATFORM"),
    _rule("REVOKE_INVITE", "INVITED", "DISABLED", "STAFF", "PLATFORM"),
]
