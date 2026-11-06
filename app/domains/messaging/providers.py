"""messaging servislari: bir marta yaratiladi (main.py — composition root) va app.state'dan olinadi.

Buyurtma qoralamasi va bog'lash — `ConversationOrdersPort` orqali (commerce kodi import qilinmaydi, ADR-032);
sayt holati — `SitePort`. Tashqi kanal klientlari `adapters` da — testlar soxtasini qo'yadi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.domains.messaging.common import ChannelAdapters, MessagingConfig
from app.domains.messaging.services.ai_replies import AiReplyService
from app.domains.messaging.services.channels import ChannelService
from app.domains.messaging.services.core import ConversationCore
from app.domains.messaging.services.ig_classify import IgClassifyService
from app.domains.messaging.services.ig_ingest import IgIngestService
from app.domains.messaging.services.ig_media import IgMediaService
from app.domains.messaging.services.ig_panel import IgPanelService
from app.domains.messaging.services.ig_reply import IgReplyService
from app.domains.messaging.services.inbound import InboundService
from app.domains.messaging.services.inbox import InboxService
from app.domains.messaging.services.notify import CustomerNotifier
from app.domains.messaging.services.outbound import MessageWriter
from app.domains.messaging.services.sending import SendingService
from app.domains.messaging.services.webchat import WebchatService
from app.platform.audit.services.audit_service import AuditService
from app.platform.llm.router import LlmRouter
from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.platform.storage.services.file_service import FileService
from app.platform.use.services.use_service import UseService
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import ConversationOrdersPort, StockQueryPort
from app.shared.contracts.sales_ai import AiBudgetPort, AiGatePort
from app.shared.contracts.storefront import SitePort


@dataclass(frozen=True)
class InstagramServices:
    """Instagram izohlari (DEC-148): webhook → qoida; javob; kayfiyat; post media; panel."""

    ingest: IgIngestService
    reply: IgReplyService
    classify: IgClassifyService
    media: IgMediaService
    panel: IgPanelService


@dataclass(frozen=True)
class MessagingServices:
    config: MessagingConfig
    adapters: ChannelAdapters
    channels: ChannelService
    core: ConversationCore
    writer: MessageWriter
    inbound: InboundService
    inbox: InboxService
    sending: SendingService
    webchat: WebchatService
    notifier: CustomerNotifier
    ai: AiReplyService
    site: SitePort
    ig: InstagramServices


def build_messaging_services(
    use: UseService,
    audit: AuditService,
    files: FileService,
    templates: CustomerTemplateService,
    orders: ConversationOrdersPort,
    site: SitePort,
    config: MessagingConfig,
    adapters: ChannelAdapters | None = None,
    ai_gate: AiGatePort | None = None,
    catalog: CatalogQueryPort | None = None,
    stock: StockQueryPort | None = None,
    llm: LlmRouter | None = None,
    ai_budget: AiBudgetPort | None = None,
) -> MessagingServices:
    adapters = adapters or ChannelAdapters()
    writer = MessageWriter(files)
    core = ConversationCore(use, writer, templates, ai_gate=ai_gate)
    inbound = InboundService(core)
    channels = ChannelService(use, audit, adapters, config)
    return MessagingServices(
        config=config,
        adapters=adapters,
        channels=channels,
        core=core,
        writer=writer,
        inbound=inbound,
        inbox=InboxService(core, writer, files, orders),
        sending=SendingService(adapters, files, use),
        webchat=WebchatService(inbound),
        notifier=CustomerNotifier(writer, templates),
        ai=AiReplyService(core, writer),
        site=site,
        ig=InstagramServices(
            ingest=IgIngestService(),
            reply=IgReplyService(adapters, config, templates, catalog, stock),
            classify=IgClassifyService(config, llm, ai_budget),
            media=IgMediaService(adapters),
            panel=IgPanelService(config, channels, audit, templates, catalog),
        ),
    )


def messaging_services(request: Request) -> MessagingServices:
    return request.app.state.messaging  # type: ignore[no-any-return]


def from_state(state: Any) -> MessagingServices:
    """Fon ishlari va tinglovchilar uchun (app.state yoki worker holati)."""
    return state.messaging  # type: ignore[no-any-return]
