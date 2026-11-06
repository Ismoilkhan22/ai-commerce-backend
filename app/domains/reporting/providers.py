"""reporting servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Katalog o'lchami `CatalogQueryPort`, qayta qurish manbasi va tannarx `ReportingSourcePort` orqali — boshqa
domen kodi import qilinmaydi (ADR-032).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.reporting.services.assistant import ReportAssistant
from app.domains.reporting.services.reports import ReportService
from app.platform.audit.services.audit_service import AuditService
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.reporting import ReportingSourcePort


@dataclass(frozen=True)
class ReportingServices:
    reports: ReportService
    catalog: CatalogQueryPort
    sources: ReportingSourcePort
    assistant: ReportAssistant


def build_reporting_services(catalog: CatalogQueryPort, sources: ReportingSourcePort) -> ReportingServices:
    reports = ReportService()
    return ReportingServices(
        reports=reports, catalog=catalog, sources=sources, assistant=ReportAssistant(reports, AuditService())
    )


def reporting_services(request: Request) -> ReportingServices:
    return request.app.state.reporting  # type: ignore[no-any-return]
