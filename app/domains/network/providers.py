"""network servislari: composition root (main.py) — app.state.network."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.network.services.api_keys import ApiKeyService
from app.domains.network.services.offers import OfferService
from app.domains.network.services.review import ReviewService
from app.domains.network.services.trust import TrustService
from app.platform.audit.services.audit_service import AuditService
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import StockQueryPort


@dataclass(frozen=True)
class NetworkServices:
    offers: OfferService
    review: ReviewService
    trust: TrustService
    api_keys: ApiKeyService


def build_network_services(
    audit: AuditService, catalog: CatalogQueryPort, stock: StockQueryPort, secret: str
) -> NetworkServices:
    offers = OfferService(audit, catalog, stock)
    return NetworkServices(
        offers=offers,
        review=ReviewService(audit, offers),
        trust=TrustService(audit, offers),
        api_keys=ApiKeyService(audit, secret),  # M30: kalit xeshi shu sir bilan (HMAC)
    )


def network_services(request: Request) -> NetworkServices:
    return request.app.state.network  # type: ignore[no-any-return]
