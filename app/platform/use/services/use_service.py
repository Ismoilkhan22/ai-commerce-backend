"""Slim USE — faqat 3 ish: validate, log, force (ADR-034, 04 §2).

Ruxsat tekshirish (router), event (domen outbox'i), notification — bu yerda EMAS.
Tartib: idempotency → lock/o'qish → validate → o'zgartirish → log → audit → outbox → COMMIT.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.use.infrastructure.rules_loader import RulesRegistry
from app.platform.use.models.orm import TransitionLog
from app.shared.errors.base import ForbiddenError, InvalidTransitionError, ValidationError
from app.shared.tracing.context import get_trace_id
from app.shared.types.actor import ActorContext
from app.shared.types.state import StateMachineRule

logger = structlog.get_logger(__name__)

FORCE_REASON_MIN_LENGTH = 20


class UseService:
    def __init__(self, registry: RulesRegistry, audit: AuditService) -> None:
        self.registry = registry
        self.audit = audit

    def validate_transition(
        self, entity_type: str, from_status: str, to_status: str, command: str, actor: ActorContext
    ) -> StateMachineRule:
        rule = self.registry.find(entity_type, from_status, command)
        if rule is None or rule.to_status != to_status or actor.actor_type not in rule.actors:
            logger.info(
                "use.transition_rejected",
                entity_type=entity_type,
                command=command,
                from_status=from_status,
                to_status=to_status,
                actor_type=actor.actor_type,
            )
            raise InvalidTransitionError(
                "Transition not allowed", entity=entity_type, **{"from": from_status}, command=command
            )
        return rule

    async def log_transition(
        self,
        db: AsyncSession,
        *,
        entity_id: UUID,
        rule: StateMachineRule,
        actor: ActorContext,
        reason: str | None = None,
    ) -> None:
        if rule.requires_reason and not (reason and reason.strip()):
            raise ValidationError(
                "Reason required", fields=[{"field": "reason", "code": "required", "params": {}}]
            )
        await self._insert(
            db, rule.entity_type, entity_id, rule.command, rule.from_status, rule.to_status, actor, reason
        )
        logger.info(
            "use.transition",
            entity_type=rule.entity_type,
            command=rule.command,
            from_status=rule.from_status,
            to_status=rule.to_status,
        )

    async def force_transition(
        self,
        db: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        from_status: str,
        to_status: str,
        actor: ActorContext,
        reason: str,
    ) -> None:
        """Faqat platforma admini, runbook holatlari uchun (04 §7). Holatni chaqiruvchi o'zgartiradi.

        Qoldiq va pulga bog'liq holatlarga KIRISH ham, ulardan CHIQISH ham majburlab bo'lmaydi
        (founder, 2026-10-23): masalan CONFIRMED → CANCELLED majburlansa, rezerv bo'shatilmay qolardi.
        Har majburlash shu yerning o'zida jurnal va auditga yoziladi — chaqiruvchi unutib qo'yolmaydi.
        """
        if actor.actor_type != "PLATFORM" or "platform.state.force" not in actor.permissions:
            raise ForbiddenError("Force transition requires platform.state.force")
        if len(reason.strip()) < FORCE_REASON_MIN_LENGTH:
            raise ValidationError(
                "Reason too short",
                fields=[
                    {"field": "reason", "code": "min_length", "params": {"min": FORCE_REASON_MIN_LENGTH}}
                ],
            )
        protected = self.registry.non_forceable.get(entity_type, frozenset())
        if from_status in protected or to_status in protected:
            raise InvalidTransitionError(
                "State cannot be forced", entity=entity_type, **{"from": from_status}, command="FORCE"
            )
        await self._insert(
            db, entity_type, entity_id, "FORCE", from_status, to_status, actor, reason, forced=True
        )
        await self.audit.record(
            db,
            action="platform.state.forced",
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            reason=reason,
            diff={"status": {"old": from_status, "new": to_status}},
        )
        logger.warning(
            "use.transition_forced", entity_type=entity_type, from_status=from_status, to_status=to_status
        )

    async def _insert(
        self,
        db: AsyncSession,
        entity_type: str,
        entity_id: UUID,
        command: str,
        from_status: str,
        to_status: str,
        actor: ActorContext,
        reason: str | None,
        *,
        forced: bool = False,
    ) -> None:
        db.add(
            TransitionLog(
                shop_id=actor.shop_id,
                entity_type=entity_type,
                entity_id=entity_id,
                command=command,
                from_status=from_status,
                to_status=to_status,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                reason=reason,
                forced=forced,
                trace_id=get_trace_id(),
            )
        )
        await db.flush()
