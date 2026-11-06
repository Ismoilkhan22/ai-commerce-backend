"""storefront servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Katalog va mavjudlik — `CatalogQueryPort` / `StockQueryPort` orqali (catalog va commerce kodi import
qilinmaydi).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.storefront.common import PreviewSigner
from app.domains.storefront.services.public_service import PublicService
from app.domains.storefront.services.site_service import SiteService
from app.domains.storefront.site_gate import SiteGate
from app.platform.audit.services.audit_service import AuditService
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.cache import Cache
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import StockQueryPort


@dataclass(frozen=True)
class StorefrontServices:
    gate: SiteGate
    sites: SiteService
    public: PublicService


def build_storefront_services(
    use: UseService,
    audit: AuditService,
    files: FileService,
    cache: Cache,
    catalog: CatalogQueryPort,
    stock: StockQueryPort,
    *,
    secret: str,
    site_url_template: str,
) -> StorefrontServices:
    preview = PreviewSigner(secret)
    gate = SiteGate(cache, preview)
    return StorefrontServices(
        gate=gate,
        sites=SiteService(use, audit, files, cache, preview, site_url_template),
        public=PublicService(catalog, stock, files, cache, gate, site_url_template),
    )


def storefront_services(request: Request) -> StorefrontServices:
    return request.app.state.storefront  # type: ignore[no-any-return]
