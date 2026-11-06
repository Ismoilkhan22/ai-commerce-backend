"""sales_ai ruxsatlari (10 §6, business/04 "AI sotuvchi").

- sozlamalarni ko'rish (holat, xarajat, bilim bazasi) — ega va menejer;
- o'zgartirish (rejim, ish vaqti, limitlar, bilim bazasi) — faqat ega (business/13 6.4: AUTO — ega qarori);
- sinov oynasi — ega va menejer;
- AI takliflarini ko'rib yuborish / rad etish — inbox'ga kiradiganlar (operator — o'z suhbatlarida).
"""

from __future__ import annotations

from collections.abc import Mapping

SETTINGS_VIEW = "sales_ai.settings.view"
SETTINGS_EDIT = "sales_ai.settings.edit"
KNOWLEDGE_TEST = "sales_ai.knowledge.test"  # sinov oynasi
SUGGESTION_REVIEW = "sales_ai.suggestion.review"

_OPERATOR = frozenset({SUGGESTION_REVIEW})
_MANAGER = _OPERATOR | {SETTINGS_VIEW, KNOWLEDGE_TEST}
_OWNER = _MANAGER | {SETTINGS_EDIT}

SALES_AI_PERMISSIONS = sorted(_OWNER)

SALES_AI_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": _OWNER,
    "MANAGER": _MANAGER,
    "SALES": _OPERATOR,
}
