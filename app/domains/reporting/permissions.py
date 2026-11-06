"""reporting ruxsatlari (10 §6.3, 19 §6, DEC-146).

Hisobotlar — ega va menejer: `reporting.view`. Tannarx, foyda va AI xarajati (pul) — faqat ega:
`reporting.margin.read` (DEC-146: tannarxni faqat ega ko'radi). Menejerga tannarxsiz maydonlar ochiq.
Ikkinchi qatlam: filial doirasi (`actor.branch_ids`) — faqat shu filiallar raqamlari.
"""

from __future__ import annotations

from collections.abc import Mapping

REPORTING_VIEW = "reporting.view"

REPORTING_MARGIN_READ = "reporting.margin.read"

REPORTING_PERMISSIONS = [REPORTING_VIEW, REPORTING_MARGIN_READ]

REPORTING_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": frozenset({REPORTING_VIEW, REPORTING_MARGIN_READ}),
    "MANAGER": frozenset({REPORTING_VIEW}),
}
