"""Sayt holati (storefront.md §0): Qoralama → Ochiq ⇄ To'xtatilgan. Faqat ega (ruxsat qatlamida)."""

from __future__ import annotations

from app.shared.types.state import StateMachineRule

SITE = "storefront.site"


def _site(command: str, src: str, dst: str) -> StateMachineRule:
    return StateMachineRule(
        entity_type=SITE,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset({"STAFF"}),
        business_ref="storefront.md §0",
    )


SITE_RULES = [
    _site("PUBLISH", "DRAFT", "LIVE"),  # telefon majburiy; shop faol bo'lmasa xaridor hali ko'rmaydi
    _site("PAUSE", "LIVE", "PAUSED"),  # "vaqtincha ishlamayapti", buyurtma qabul qilinmaydi
    _site("RESUME", "PAUSED", "LIVE"),
]
