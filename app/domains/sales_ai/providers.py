"""sales_ai servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Boshqa domenlar bilan faqat port'lar orqali: suhbat — `AiConversationPort` (messaging), qoralamalar —
`SalesDraftsPort` (commerce), katalog va qoldiq — Query Port'lar. LLM — `platform/llm` routeri.
`Database` lifespan'da ochiladi — shuning uchun broker va navbat ijrochisi chaqiruv paytida yig'iladi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.domains.sales_ai.agent import TurnRunner
from app.domains.sales_ai.eval.runner import EvalEngine, RouterFactory
from app.domains.sales_ai.eval.service import EvalService
from app.domains.sales_ai.services.gate import AiGateService
from app.domains.sales_ai.services.panel import AiPanelService
from app.domains.sales_ai.services.quality import AiQualityService
from app.domains.sales_ai.services.review import AiReviewService
from app.domains.sales_ai.services.sandbox import SandboxService
from app.domains.sales_ai.tools import ToolBroker
from app.platform.audit.services.audit_service import AuditService
from app.platform.llm.router import LlmRouter
from app.platform.notifications.services.notifications import NotificationService
from app.shared.cache import Cache
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import SalesDraftsPort, StockQueryPort
from app.shared.contracts.messaging import AiConversationPort
from app.shared.db.session import Database


@dataclass
class SalesAiServices:
    router: LlmRouter
    gate: AiGateService
    panel: AiPanelService
    sandbox: SandboxService
    catalog: CatalogQueryPort
    stock: StockQueryPort
    debounce_s: float
    drafts: SalesDraftsPort | None = None
    conversations: AiConversationPort | None = None  # messaging yig'ilgandan keyin ulanadi (main.py)
    review: AiReviewService | None = None
    eval: EvalService = None  # type: ignore[assignment]  # 6c: baholash (platforma admini)
    quality: AiQualityService = None  # type: ignore[assignment]  # 6c: "AI sifati"

    def broker(self, database: Database) -> ToolBroker:
        return ToolBroker(database, self.catalog, self.stock, self.drafts)

    def runner(self, database: Database) -> TurnRunner:
        assert self.conversations is not None
        return TurnRunner(
            database,
            self.router,
            self.broker(database),
            self.conversations,
            self.gate,
            debounce_s=self.debounce_s,
        )

    def connect(self, conversations: AiConversationPort, drafts: SalesDraftsPort) -> None:
        self.conversations = conversations
        self.drafts = drafts
        self.review = AiReviewService(conversations)


def build_sales_ai_services(
    router: LlmRouter,
    audit: AuditService,
    cache: Cache,
    catalog: CatalogQueryPort,
    stock: StockQueryPort,
    *,
    allow_fake: bool,
    debounce_s: float,
    eval_routers: RouterFactory | None = None,
    git_sha: str = "dev",
    gemini_free: bool = True,
) -> SalesAiServices:
    gate = AiGateService(router.status, allow_fake=allow_fake, notifications=NotificationService())
    services = SalesAiServices(
        router=router,
        gate=gate,
        panel=AiPanelService(
            gate, audit, {alias: models[0] for alias, models in router.config.models.items() if models}
        ),
        sandbox=None,  # type: ignore[arg-type]
        catalog=catalog,
        stock=stock,
        debounce_s=debounce_s,
    )
    services.sandbox = SandboxService(router, services.broker, gate, cache)
    services.quality = AiQualityService(services.panel)
    services.eval = EvalService(
        EvalEngine(
            routers=eval_routers or (lambda provider, overrides: router),
            brokers=services.broker,
            git_sha=git_sha,
            gemini_free=gemini_free,
        ),
        audit,
    )
    return services


def sales_ai_services(request: Request) -> SalesAiServices:
    return from_state(request.app.state)


def from_state(state: Any) -> SalesAiServices:
    services: SalesAiServices = state.sales_ai
    return services
