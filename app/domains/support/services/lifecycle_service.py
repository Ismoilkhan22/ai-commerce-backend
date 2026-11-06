"""Kafolat murojaati holat o'tishlari (FSM-11) va ombor yozuvi (7b, DEC-145).

Tartib: qulf → If-Match → validate → o'zgartirish → ombor yozuvi (commerce port'i) → jurnal → audit → outbox.
Hammasi bitta tranzaksiyada: almashtirish uchun dona yetmasa (409 INSUFFICIENT_AVAILABLE_STOCK) holat ham
o'zgarmaydi. Ombor qoidalari:
- `START_SERVICE`: `REPLACE`/`REFUND` bo'lsa qaytgan dona karantinga (RETURN_QUARANTINE). `REPAIR` — xaridor
  mahsuloti, omborga kirmaydi;
- `RESOLVE` + `REPLACE`: yangi dona ombordan (WARRANTY_REPLACEMENT);
- karantindan chiqarish — oddiy RESTOCK / WRITE_OFF tuzatishi (`support_case_id` bilan).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.support import permissions as perm
from app.domains.support.common import AUTO_CLOSE_DAYS, field, in_branch_scope
from app.domains.support.events import READY_NOTICE, RESOLVED, STATUS_CHANGED, UPDATED, case_event
from app.domains.support.models.orm import SupportCase
from app.domains.support.schemas import (
    CaseApproveIn,
    CaseDetail,
    CaseRejectIn,
    CaseResolutionChangeIn,
    CaseResolveIn,
    CaseStartReviewIn,
)
from app.domains.support.services.views import CaseViews
from app.domains.support.state_machine import CASE
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.tasks import SUPPORT_CASE_DECISION, TaskService
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.support import SupportCommercePort
from app.shared.errors.base import ForbiddenError, NotFoundError, ValidationError
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

OUTCOMES = {"REPAIR": "REPAIRED", "REPLACE": "REPLACED", "REFUND": "RETURNED"}
QUARANTINING = ("REPLACE", "REFUND")  # qaytgan dona shopga qaytadi


class CaseLifecycleService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        catalog: CatalogQueryPort,
        commerce: SupportCommercePort,
        views: CaseViews,
    ) -> None:
        self.use = use
        self.audit = audit
        self.catalog = catalog
        self.commerce = commerce
        self.views = views
        self.tasks = TaskService()

    # ================================================================== buyruqlar
    async def start_review(
        self,
        db: AsyncSession,
        actor: ActorContext,
        case_id: UUID,
        expected_version: int,
        data: CaseStartReviewIn,
    ) -> CaseDetail:
        case = await self._locked(db, actor, case_id, expected_version)
        rule = self.use.validate_transition(CASE, case.status, "IN_REVIEW", "START_REVIEW", actor)
        case.status = rule.to_status
        if data.item_received and case.item_received_at is None:
            case.item_received_at, case.item_received_by = utcnow(), actor.membership_id
        return await self._finish(db, actor, case, rule.command, rule.from_status, None)

    async def approve(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int, data: CaseApproveIn
    ) -> CaseDetail:
        case = await self._locked(db, actor, case_id, expected_version)
        rule = self.use.validate_transition(CASE, case.status, "APPROVED", "APPROVE", actor)
        # Kafolatdan tashqari yoki tashqi sotuv: izoh majburiy ("mijoz doimiy, istisno")
        if (not case.within_warranty or case.source == "EXTERNAL") and not data.decision_note:
            raise ValidationError("Decision note is required", fields=[field("decision_note", "required")])
        await self._set_resolution(db, actor, case, data.resolution, data.replacement_sku_id)
        case.status = rule.to_status
        case.decided_by, case.decided_at, case.decision_note = (
            actor.membership_id,
            utcnow(),
            data.decision_note,
        )
        await self._close_decision_task(db, actor, case)
        return await self._finish(db, actor, case, rule.command, rule.from_status, data.decision_note)

    async def reject(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int, data: CaseRejectIn
    ) -> CaseDetail:
        case = await self._locked(db, actor, case_id, expected_version)
        rule = self.use.validate_transition(CASE, case.status, "REJECTED", "REJECT", actor)
        case.status = rule.to_status
        case.reject_reason = data.reject_reason
        case.decided_by, case.decided_at, case.decision_note = actor.membership_id, utcnow(), data.note
        await self._close_decision_task(db, actor, case)
        return await self._finish(
            db, actor, case, rule.command, rule.from_status, data.note or data.reject_reason
        )

    async def start_service(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int
    ) -> CaseDetail:
        case = await self._locked(db, actor, case_id, expected_version)
        rule = self.use.validate_transition(CASE, case.status, "IN_SERVICE", "START_SERVICE", actor)
        if case.item_received_at is None:  # mahsulotsiz xizmat yo'q (CHECK ham himoya qiladi)
            raise ValidationError("Item is not received yet", fields=[field("item_received_at", "required")])
        case.status = rule.to_status
        case.service_started_at = utcnow()
        await db.flush()
        await self._quarantine(db, actor, case)
        return await self._finish(db, actor, case, rule.command, rule.from_status, None)

    async def resolve(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int, data: CaseResolveIn
    ) -> CaseDetail:
        case = await self._locked(db, actor, case_id, expected_version)
        rule = self.use.validate_transition(CASE, case.status, "RESOLVED", "RESOLVE", actor)
        assert case.resolution is not None
        if data.refund_amount_minor is not None and case.resolution != "REFUND":
            raise ValidationError(
                "Refund amount applies to refunds only", fields=[field("refund_amount_minor", "invalid")]
            )
        if data.refund_amount_minor is not None:
            await self._check_refund_cap(db, actor, case, data.refund_amount_minor)
        if case.resolution == "REPLACE":
            target = case.replacement_sku_id or case.sku_id
            if target is None:  # tasdiqlashda tekshirilgan; o'zgargan bo'lsa ham bu yerda ushlanadi
                raise ValidationError(
                    "Replacement SKU is required", fields=[field("replacement_sku_id", "required")]
                )
            # Dona yetmasa InsufficientStockError → butun tranzaksiya qaytadi (BL-019)
            await self.commerce.issue_replacement(
                db, actor, case_id=case.id, branch_id=case.branch_id, sku_id=target, qty=case.qty
            )
        case.status = rule.to_status
        case.outcome = OUTCOMES[case.resolution]
        case.refund_amount_minor = data.refund_amount_minor
        case.resolved_at, case.resolved_by = utcnow(), actor.membership_id
        return await self._finish(
            db,
            actor,
            case,
            rule.command,
            rule.from_status,
            data.note,
            also=(RESOLVED, {"outcome": case.outcome}),
        )

    async def _check_refund_cap(
        self, db: AsyncSession, actor: ActorContext, case: SupportCase, amount: int
    ) -> None:
        """Qaytarilgan summa sotilgan qator summasidan (son × dona narxi) oshmaydi. Qator noma'lum
        (tizimdan oldingi sotuv) bo'lsa — faqat menejer/ega summa kirita oladi (sanity chegara schema'da)."""
        assert actor.shop_id is not None
        line = None
        if case.source == "ORDER_LINE" and case.order_id and case.order_line_id:
            line = await self.commerce.order_line(db, actor.shop_id, case.order_id, case.order_line_id)
        elif case.source == "QUICK_SALE_LINE" and case.quick_sale_id and case.quick_sale_line_id:
            line = await self.commerce.quick_sale_line(
                db, actor.shop_id, case.quick_sale_id, case.quick_sale_line_id
            )
        if line is None or line.unit_price_uzs_minor is None:
            if perm.CASE_DECIDE not in actor.permissions:
                raise ForbiddenError(
                    "Only a manager or owner may set the refund for an unknown sale",
                    permission=perm.CASE_DECIDE,
                )
            return
        cap = case.qty * line.unit_price_uzs_minor
        if amount > cap:
            raise ValidationError(
                "Refund exceeds the sold line total",
                fields=[field("refund_amount_minor", "max_value", max=cap)],
            )

    async def close(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int
    ) -> CaseDetail:
        case = await self._locked(db, actor, case_id, expected_version)
        return await self._close(db, actor, case, None)

    async def change_resolution(
        self,
        db: AsyncSession,
        actor: ActorContext,
        case_id: UUID,
        expected_version: int,
        data: CaseResolutionChangeIn,
    ) -> CaseDetail:
        """Qaror turini o'zgartirish ("ta'mirlab bo'lmadi, almashtiramiz"): `APPROVED` va `IN_SERVICE` da,
        faqat menejer/ega, sabab bilan. Karantinga tushgan donani ta'mirga qaytarib bo'lmaydi."""
        case = await self._locked(db, actor, case_id, expected_version)
        if case.status not in ("APPROVED", "IN_SERVICE"):
            raise ValidationError(
                "Resolution cannot be changed now", fields=[field("status", "invalid_state")]
            )
        old = case.resolution
        if case.status == "IN_SERVICE" and old in QUARANTINING and data.resolution == "REPAIR":
            raise ValidationError(
                "The returned unit is already in quarantine", fields=[field("resolution", "invalid_change")]
            )
        await self._set_resolution(db, actor, case, data.resolution, data.replacement_sku_id)
        if case.status == "IN_SERVICE":
            await self._quarantine(db, actor, case)  # REPAIR → REPLACE/REFUND: dona endi shopga qaytadi
        await db.flush()
        await self.audit.record(
            db,
            action="support.case.resolution_changed",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
            reason=data.reason,
            diff={"resolution": {"old": old, "new": case.resolution}},
        )
        await case_event(db, actor, case, UPDATED, change="RESOLUTION", previous_resolution=old)
        return await self.views.detail(db, actor, case)

    async def notify_ready(self, db: AsyncSession, actor: ActorContext, case_id: UUID) -> CaseDetail:
        """Xodim "Xaridorga xabar berish" bosdi: mahsulot tayyor (ta'mir/almashtirish tugadi). Xabarni
        messaging yuboradi (`customer.support_case_ready`), suhbat bo'lsa; bir murojaatga bitta (BL-060)."""
        case = await self._load(db, actor, case_id)
        if case.status not in ("IN_SERVICE", "RESOLVED"):
            raise ValidationError("Item is not ready yet", fields=[field("status", "invalid_state")])
        if case.conversation_id is None:
            raise ValidationError(
                "Case has no conversation", fields=[field("conversation_id", "no_conversation")]
            )
        await self.audit.record(
            db,
            action="support.case.ready_notice",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
        )
        await case_event(db, actor, case, READY_NOTICE)
        return await self.views.detail(db, actor, case)

    async def auto_close_due(self, db: AsyncSession, shop_id: UUID, now: datetime) -> int:
        """`RESOLVED` dan 7 kun o'tdi → `CLOSED` (FSM-11 "muddat o'tdi"). Bekor qilish emas, shuning uchun
        "hech narsa avtomatik bekor qilinmaydi" qoidasiga zid emas."""
        cutoff = now - timedelta(days=AUTO_CLOSE_DAYS)
        cases = list(
            (
                await db.execute(
                    select(SupportCase)
                    .where(
                        SupportCase.shop_id == shop_id,
                        SupportCase.status == "RESOLVED",
                        SupportCase.resolved_at <= cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        actor = ActorContext.system(shop_id)
        for case in cases:
            await self._close(db, actor, case, "AUTO_CLOSE_7_DAYS")
        return len(cases)

    # ================================================================== ichki
    async def _close(
        self, db: AsyncSession, actor: ActorContext, case: SupportCase, reason: str | None
    ) -> CaseDetail:
        rule = self.use.validate_transition(CASE, case.status, "CLOSED", "CLOSE", actor)
        case.status = rule.to_status
        case.closed_at, case.closed_by = utcnow(), actor.membership_id  # SYSTEM: closed_by NULL
        return await self._finish(db, actor, case, rule.command, rule.from_status, reason)

    async def _set_resolution(
        self,
        db: AsyncSession,
        actor: ActorContext,
        case: SupportCase,
        resolution: str,
        replacement: UUID | None,
    ) -> None:
        """Qaror turi va (REPLACE da) beriladigan SKU. Boshqa model tanlansa — faol SKU bo'lishi shart."""
        assert actor.shop_id is not None
        if resolution == "REPLACE":
            target = replacement or case.sku_id
            if target is None:
                raise ValidationError(
                    "Replacement SKU is required", fields=[field("replacement_sku_id", "required")]
                )
            snapshot = (await self.catalog.get_skus(db, actor.shop_id, [target])).get(target)
            if snapshot is None or snapshot.sku_status != "ACTIVE":
                raise ValidationError(
                    "Replacement SKU is not available", fields=[field("replacement_sku_id", "invalid")]
                )
            case.replacement_sku_id = target
        else:
            if replacement is not None:
                raise ValidationError(
                    "Replacement SKU applies to REPLACE only", fields=[field("replacement_sku_id", "invalid")]
                )
            case.replacement_sku_id = None
        case.resolution = resolution

    async def _quarantine(self, db: AsyncSession, actor: ActorContext, case: SupportCase) -> None:
        """REPLACE/REFUND: qaytgan dona tekshiruvga. SKU katalogda topilmagan tashqi sotuvda yozuv yo'q."""
        if case.resolution in QUARANTINING and case.sku_id is not None:
            await self.commerce.quarantine_returned(
                db, actor, case_id=case.id, branch_id=case.branch_id, sku_id=case.sku_id, qty=case.qty
            )

    async def _close_decision_task(self, db: AsyncSession, actor: ActorContext, case: SupportCase) -> None:
        await self.tasks.resolve(
            db,
            shop_id=case.shop_id,
            actor=actor,
            subject_type=CASE,
            subject_id=case.id,
            types=[SUPPORT_CASE_DECISION],
        )

    async def _load(self, db: AsyncSession, actor: ActorContext, case_id: UUID) -> SupportCase:
        case = (
            await db.execute(
                select(SupportCase)
                .where(SupportCase.id == case_id, SupportCase.shop_id == actor.shop_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if case is None or not in_branch_scope(actor, case.branch_id):
            raise NotFoundError("Case not found")
        return case

    async def _locked(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int
    ) -> SupportCase:
        case = await self._load(db, actor, case_id)
        check_version(case.version, expected_version)
        return case

    async def _finish(
        self,
        db: AsyncSession,
        actor: ActorContext,
        case: SupportCase,
        command: str,
        from_status: str,
        reason: str | None,
        *,
        also: tuple[str, dict[str, object]] | None = None,
    ) -> CaseDetail:
        await db.flush()
        rule = self.use.registry.find(CASE, from_status, command)
        assert rule is not None
        await self.use.log_transition(db, entity_id=case.id, rule=rule, actor=actor, reason=reason)
        await self.audit.record(
            db,
            action=f"support.case.{command.lower()}",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
            reason=reason,
            diff={"status": {"old": from_status, "new": case.status}},
        )
        await case_event(db, actor, case, STATUS_CHANGED, from_status=from_status, command=command)
        if also is not None:  # RESOLVED — hisobot va xaridor xabari uchun alohida event (05 §8.5)
            await case_event(db, actor, case, also[0], from_status=from_status, **also[1])
        return await self.views.detail(db, actor, case)
