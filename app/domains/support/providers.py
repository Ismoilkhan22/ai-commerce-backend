"""support servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Sotuv qatori nusxasi va ombor yozuvi `SupportCommercePort` orqali — `commerce` kodi import qilinmaydi
(ADR-032). Katalog — `CatalogQueryPort`, suhbat tekshiruvi — `ConversationLookupPort`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.support.services.case_service import CaseService
from app.domains.support.services.lifecycle_service import CaseLifecycleService
from app.domains.support.services.privacy import CasePrivacyService
from app.domains.support.services.views import CaseViews
from app.platform.audit.services.audit_service import AuditService
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.messaging import ConversationLookupPort
from app.shared.contracts.support import SupportCommercePort


@dataclass(frozen=True)
class SupportServices:
    cases: CaseService
    lifecycle: CaseLifecycleService
    privacy: CasePrivacyService


def build_support_services(
    use: UseService,
    audit: AuditService,
    files: FileService,
    catalog: CatalogQueryPort,
    conversations: ConversationLookupPort,
    commerce: SupportCommercePort,
) -> SupportServices:
    views = CaseViews(files, commerce)
    return SupportServices(
        cases=CaseService(audit, files, catalog, conversations, commerce, views),
        lifecycle=CaseLifecycleService(use, audit, catalog, commerce, views),
        privacy=CasePrivacyService(audit),
    )


def support_services(request: Request) -> SupportServices:
    return request.app.state.support  # type: ignore[no-any-return]
