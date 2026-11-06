"""network servislari: composition root (main.py) — app.state.network."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domains.network.query_port import NetworkQueryPortImpl
from app.domains.network.services.ads import AdService
from app.domains.network.services.advisor import AdvisorService
from app.domains.network.services.api_keys import ApiKeyService
from app.domains.network.services.global_bot import GlobalBotService
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
    advisor: AdvisorService
    global_bot: GlobalBotService
    ads: AdService


def build_network_services(
    audit: AuditService,
    catalog: CatalogQueryPort,
    stock: StockQueryPort,
    secret: str,
    *,
    marketplace_url: str = "http://localhost:3003",
    bot_username: str | None = None,
) -> NetworkServices:
    offers = OfferService(audit, catalog, stock)
    return NetworkServices(
        offers=offers,
        review=ReviewService(audit, offers),
        trust=TrustService(audit, offers),
        api_keys=ApiKeyService(audit, secret),  # M30: kalit xeshi shu sir bilan (HMAC)
        advisor=AdvisorService(NetworkQueryPortImpl()),  # M34: LLM main.py da ulanadi
        global_bot=GlobalBotService(NetworkQueryPortImpl(), marketplace_url, bot_username),  # M39
        ads=AdService(audit),  # M37
    )


def network_services(request: Request) -> NetworkServices:
    return request.app.state.network  # type: ignore[no-any-return]
