"""support ruxsatlari va rollar (10 §6.3, business/04, DEC-130, DEC-131, DEC-145).

Rol ruxsati — faqat birinchi qatlam. Ikkinchi qatlam service'da (10 §6.8):
- **br** (filial doirasi): `actor.branch_ids` bo'lsa — faqat shu filiallar murojaatlari.

Kim nima qiladi:
- ochish: ega, menejer, operator (SALES). Omborchi ko'radi (business/04);
- izoh, rasm, "mahsulot qabul qilindi", diagnostika, yopish: ega, menejer, operator va omborchi
  (`support.case.service`; omborchi — qabul va diagnostika, support.md §1);
- xizmatni boshlash va hal qilish (ombor yozuvi bor): ega, menejer, omborchi (`support.case.fulfil`);
- qabul / rad / qaror turini o'zgartirish / kafolat muddati tugagan sotuvga ruxsat: faqat ega va menejer
  (`support.case.decide`, DEC-130).
"""

from __future__ import annotations

from collections.abc import Mapping

CASE_VIEW = "support.case.view"
CASE_OPEN = "support.case.open"
CASE_SERVICE = "support.case.service"
CASE_FULFIL = "support.case.fulfil"
CASE_DECIDE = "support.case.decide"

_MANAGER = frozenset({CASE_VIEW, CASE_OPEN, CASE_SERVICE, CASE_FULFIL, CASE_DECIDE})
_SALES = frozenset({CASE_VIEW, CASE_OPEN, CASE_SERVICE})
_WAREHOUSE = frozenset({CASE_VIEW, CASE_SERVICE, CASE_FULFIL})

SUPPORT_PERMISSIONS = sorted(_MANAGER | _SALES | _WAREHOUSE)

SUPPORT_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": _MANAGER,
    "MANAGER": _MANAGER,
    "SALES": _SALES,
    "WAREHOUSE": _WAREHOUSE,
}
