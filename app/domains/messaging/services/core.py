"""Suhbat yadrosi: FSM-04 o'tishlari, fencing raqami va operatorga uzatish (handoff).

Holat va speaker bitta UPDATE'da o'zgaradi (12 §8): `TAKE_OVER` / `RETURN_TO_AI` / pauza — `speaker_version`
+1, shuning uchun AI tayyorlab turgan javob (eski versiya bilan) navbatga tushmaydi (TC-009).
Har o'tish `platform.transition_log` ga yoziladi (USE).

Operatorga uzatilganda: `handoffs` qatori (suhbatda bitta ochiq), `HANDOFF` vazifasi, xodimlarga xabar
(`staff.handoff`) va — ish vaqtidan tashqari bo'lsa — xaridorga bir marta `customer.handoff_after_hours`.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.common import (
    CONVERSATION,
    channel_label,
    hours_label,
    within_inbox_hours,
)
from app.domains.messaging.models.orm import Conversation, Handoff
from app.domains.messaging.services.outbound import MessageWriter
from app.domains.messaging.state_machine import CONVERSATION as CONVERSATION_ENTITY
from app.platform.notifications.customer_templates import safe_render
from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import HANDOFF, TaskService
from app.platform.shops.models.orm import Shop, ShopPolicy
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)

OPERATOR_ROLES = ("OWNER", "MANAGER", "SALES")
SPEAKER_BUMPING = frozenset({"TAKE_OVER", "RETURN_TO_AI"})


class ConversationCore:
    def __init__(
        self,
        use: UseService,
        writer: MessageWriter,
        templates: CustomerTemplateService,
        *,
        ai_enabled: bool = False,
    ) -> None:
        self.use = use
        self.writer = writer
        self.templates = templates
        self.ai_enabled = ai_enabled  # 6-modulgacha False: birinchi xabar darhol operatorga
        self.tasks = TaskService()
        self.notifications = NotificationService()

    async def lock(self, db: AsyncSession, shop_id: UUID, conversation_id: UUID) -> Conversation | None:
        return (
            await db.execute(
                select(Conversation)
                .where(Conversation.shop_id == shop_id, Conversation.id == conversation_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def transition(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation: Conversation,
        command: str,
        to_status: str,
        *,
        reason: str | None = None,
    ) -> None:
        rule = self.use.validate_transition(
            CONVERSATION_ENTITY, conversation.status, to_status, command, actor
        )
        conversation.status = rule.to_status
        if command in SPEAKER_BUMPING:
            conversation.speaker_version += 1
            conversation.speaker_mode = "HUMAN" if command == "TAKE_OVER" else "AI"
        await self.use.log_transition(db, entity_id=conversation.id, rule=rule, actor=actor, reason=reason)

    async def pause_speaker(self, conversation: Conversation) -> None:
        """AI javob bermaydi (o'chiq / limit / shop to'xtatilgan): PAUSED, versiya +1 (12 §8)."""
        if conversation.speaker_mode != "PAUSED":
            conversation.speaker_mode = "PAUSED"
            conversation.speaker_version += 1

    async def route_new_customer_message(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation, *, operator_requested: bool
    ) -> None:
        """Xaridor yozdi — holat FSM-04 bo'yicha. AI o'chiq (6-modulgacha): AI navbatiga tushgan suhbat darhol
        operatorga (`REQUEST_HUMAN`, sabab AI_UNAVAILABLE yoki xaridor so'radi)."""
        status = conversation.status
        if status == "NEW":
            await self.transition(db, actor, conversation, "FIRST_MESSAGE", "AI_ACTIVE")
        elif status == "RESOLVED":
            await self.transition(db, actor, conversation, "CUSTOMER_REPLIED", "REOPENED")
        elif status == "WAITING_CUSTOMER":
            if conversation.speaker_mode == "HUMAN":
                await self.transition(db, actor, conversation, "CUSTOMER_REPLIED", "HUMAN_ACTIVE")
                return
            await self.transition(db, actor, conversation, "CUSTOMER_REPLIED_TO_AI", "AI_ACTIVE")
        if conversation.status in ("AI_ACTIVE", "REOPENED") and (operator_requested or not self.ai_enabled):
            reason = "CUSTOMER_REQUEST" if operator_requested else "AI_UNAVAILABLE"
            await self.request_human(db, actor, conversation, reason=reason, requested_by_type="CUSTOMER")

    async def request_human(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation: Conversation,
        *,
        reason: str,
        requested_by_type: str,
        requested_by_membership_id: UUID | None = None,
    ) -> Handoff | None:
        await self.transition(db, actor, conversation, "REQUEST_HUMAN", "HUMAN_NEEDED")
        if not self.ai_enabled:
            await self.pause_speaker(conversation)
        conversation.waiting_since = utcnow()
        return await self.open_handoff(
            db,
            actor,
            conversation,
            reason=reason,
            requested_by_type=requested_by_type,
            requested_by_membership_id=requested_by_membership_id,
        )

    async def open_handoff(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation: Conversation,
        *,
        reason: str,
        requested_by_type: str,
        requested_by_membership_id: UUID | None = None,
    ) -> Handoff | None:
        """Suhbatda bitta ochiq uzatish (07): ochig'i bor bo'lsa — yangisi ochilmaydi."""
        existing = await self.open_handoff_of(db, conversation)
        if existing is not None:
            return None
        handoff = Handoff(
            shop_id=conversation.shop_id,
            conversation_id=conversation.id,
            reason=reason,
            requested_by_type=requested_by_type,
            requested_by_membership_id=requested_by_membership_id,
            status="OPEN",
            speaker_version_at_request=conversation.speaker_version,
        )
        db.add(handoff)
        await db.flush()
        await self.tasks.open(
            db,
            shop_id=conversation.shop_id,
            actor=actor,
            type=HANDOFF,
            subject_type=CONVERSATION,
            subject_id=conversation.id,
            dedup_key=f"handoff:{handoff.id}",
            assignee_membership_id=conversation.assignee_membership_id,
            assignee_role="SALES",
            priority="HIGH",
            params={"channel": conversation.channel, "reason": reason},
        )
        await self.notifications.notify_staff(
            db,
            shop_id=conversation.shop_id,
            actor=actor,
            template_key="staff.handoff",
            aggregate_type=CONVERSATION,
            aggregate_id=conversation.id,
            aggregate_version=conversation.version,
            variables={"channel": channel_label(conversation.channel)},
            membership_ids=[conversation.assignee_membership_id],
            roles=OPERATOR_ROLES if conversation.assignee_membership_id is None else ("OWNER", "MANAGER"),
            dedup_scope=f"handoff:{handoff.id}",
        )
        await self.writer.conversation_changed(
            db, actor, conversation, "handed_off", handoff_id=handoff.id, reason_code=reason
        )
        # Xaridorga eslatma — "eng yaxshi urinish": xato bo'lsa ham kiruvchi xabar saqlanadi
        # (QA 5b H1, BL-032)
        try:
            async with db.begin_nested():
                await self._after_hours_notice(db, actor, conversation, handoff)
        except Exception:  # eslatma xatosi suhbatni buzmasligi kerak
            logger.warning("messaging.after_hours_notice_failed", conversation_id=str(conversation.id))
        return handoff

    async def _after_hours_notice(
        self, db: AsyncSession, actor: ActorContext, conversation: Conversation, handoff: Handoff
    ) -> None:
        policy = await db.get(ShopPolicy, conversation.shop_id)
        shop = await db.get(Shop, conversation.shop_id)
        hours = policy.inbox_hours if policy is not None else None
        if not hours or shop is None or within_inbox_hours(hours, shop.timezone, utcnow()):
            return
        locale = conversation.locale or "uz"
        key = "customer.handoff_after_hours"
        body, _ = await self.templates.resolve(db, conversation.shop_id, key, locale)
        text = safe_render(key, body, {"hours": hours_label(hours), "shop_name": shop.name}, locale)
        await self.writer.append_outbound(
            db,
            actor,
            conversation,
            origin="NOTIFICATION",
            author_type="SYSTEM",
            body=text,
            intent_key=f"after_hours:{handoff.id}",
            require_reachable=False,
        )

    async def open_handoff_of(self, db: AsyncSession, conversation: Conversation) -> Handoff | None:
        return (
            await db.execute(
                select(Handoff)
                .where(
                    Handoff.shop_id == conversation.shop_id,
                    Handoff.conversation_id == conversation.id,
                    Handoff.status == "OPEN",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def close_handoff(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation: Conversation,
        *,
        status: str,
        taken_by: UUID | None = None,
    ) -> None:
        handoff = await self.open_handoff_of(db, conversation)
        now = utcnow()
        if handoff is not None:
            handoff.status = status
            handoff.closed_at = now
            if status == "TAKEN":
                handoff.taken_by, handoff.taken_at = taken_by, now
            await db.flush()
        conversation.waiting_since = None
        await self.tasks.resolve(
            db,
            shop_id=conversation.shop_id,
            actor=actor,
            subject_type=CONVERSATION,
            subject_id=conversation.id,
            types=[HANDOFF],
        )
