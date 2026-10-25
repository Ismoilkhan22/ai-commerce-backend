"""Mahsulotni saytga chiqarish — FSM-02 (business/05, DEC-133).

Stage 1: ega yoki menejer qoralamani to'g'ridan chiqaradi; arxivlashni faqat ega qiladi (ruxsat qatlamida —
`catalog.product.archive`). "Tekshiruvda" (IN_REVIEW) strelkalari katalog xodimi roli bilan qo'shiladi.
"""

from __future__ import annotations

from app.shared.types.state import StateMachineRule

ENTITY = "catalog.product"


def _rule(command: str, src: str, dst: str) -> StateMachineRule:
    return StateMachineRule(
        entity_type=ENTITY,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset({"STAFF"}),
        business_ref="FSM-02",
    )


PRODUCT_RULES = [
    _rule("PUBLISH", "DRAFT", "PUBLISHED"),
    _rule("HIDE", "PUBLISHED", "HIDDEN"),
    _rule("REPUBLISH", "HIDDEN", "PUBLISHED"),
    _rule("ARCHIVE", "DRAFT", "ARCHIVED"),
    _rule("ARCHIVE", "PUBLISHED", "ARCHIVED"),
    _rule("ARCHIVE", "HIDDEN", "ARCHIVED"),
]
