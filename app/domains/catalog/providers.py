"""catalog servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.catalog.pc_specs.services.link_service import LinkService
from app.domains.catalog.pc_specs.services.spec_service import SpecLibraryService
from app.domains.catalog.pricing.services.pricing_service import PricingService
from app.domains.catalog.products.services.category_service import CategoryService
from app.domains.catalog.products.services.product_service import ProductService
from app.platform.audit.services.audit_service import AuditService
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService


@dataclass(frozen=True)
class CatalogServices:
    categories: CategoryService
    pricing: PricingService
    links: LinkService
    products: ProductService
    specs: SpecLibraryService


def build_catalog_services(use: UseService, audit: AuditService, files: FileService) -> CatalogServices:
    categories = CategoryService(audit)
    pricing = PricingService(audit)
    links = LinkService(audit)
    return CatalogServices(
        categories=categories,
        pricing=pricing,
        links=links,
        products=ProductService(use, audit, categories, pricing, links, files),
        specs=SpecLibraryService(audit),
    )


def catalog_services(request: Request) -> CatalogServices:
    return request.app.state.catalog  # type: ignore[no-any-return]
