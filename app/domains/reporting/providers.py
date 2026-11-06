"""reporting servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Katalog o'lchami `CatalogQueryPort`, qayta qurish manbasi va tannarx `ReportingSourcePort` orqali — boshqa
domen kodi import qilinmaydi (ADR-032).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.reporting.services.reports import ReportService
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.reporting import ReportingSourcePort


@dataclass(frozen=True)
class ReportingServices:
    reports: ReportService
    catalog: CatalogQueryPort
    sources: ReportingSourcePort


def build_reporting_services(catalog: CatalogQueryPort, sources: ReportingSourcePort) -> ReportingServices:
    return ReportingServices(reports=ReportService(), catalog=catalog, sources=sources)


def reporting_services(request: Request) -> ReportingServices:
    return request.app.state.reporting  # type: ignore[no-any-return]
