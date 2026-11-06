"""Leadlar (FSM-05, db/commerce_quotes.md §1, DEC-142 Q1–Q2).

Kim ko'radi: ega va menejer — hammasini; operator — o'ziga biriktirilgan va biriktirilmaganlarini.
Kontakt (telefon) faqat rozilik bilan va shifrlangan (BL-042); javobda — niqoblangan; event/audit'da yo'q.
QUOTED va WON — avtomatik (taklif yuborilganda / buyurtma topshirilganda), LOST — faqat xodim, sabab bilan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import (
    cursor_time,
    cursor_uuid,
    field,
    make_cursor,
    member_names,
    read_cursor,
)
from app.domains.commerce.orders.models.orm import Order
from app.domains.commerce.orders.services.views import mask_phone
from app.domains.commerce.permissions import LEAD_ASSIGN, LEAD_MANAGE, QUOTE_EDIT
from app.domains.commerce.quotes.common import next_number
from app.domains.commerce.quotes.models.orm import OPEN_LEAD_STATUSES, Lead, Quote, QuoteRevision
from app.domains.commerce.quotes.schemas import (
    History,
    LeadAction,
    LeadCounts,
    LeadCreate,
    LeadList,
    LeadListItem,
    LeadOrderSummary,
    LeadOut,
    LeadUpdate,
    QuoteSummary,
    QuoteTransitionOut,
    Requirements,
)
from app.domains.commerce.quotes.state_machine import LEAD
from app.domains.commerce.schemas import member_ref
from app.platform.audit.services.audit_service import AuditService
from app.platform.staff.models.orm import Membership, Principal
from app.platform.use.models.orm import TransitionLog
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.contracts.messaging import ConversationLookupPort
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import ForbiddenError, InvalidTransitionError, NotFoundError, ValidationError
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.pagination import DEFAULT_LIMIT
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

_SUPERVISOR = ("OWNER", "MANAGER")
_LEAD_OWNER_ROLES = ("OWNER", "MANAGER", "SALES")


def is_supervisor(actor: ActorContext) -> bool:
    return any(role in actor.roles for role in _SUPERVISOR)


def lead_visible(actor: ActorContext, lead: Lead) -> bool:
    # AI sotuvchi (6b) faqat o'z suhbatining leadiga SalesDraftsPort orqali tegadi
    if actor.actor_type == "AI_AGENT":
        return True
    return is_supervisor(actor) or lead.assigned_membership_id in (None, actor.membership_id)


def ensure_lead_visible(actor: ActorContext, lead: Lead) -> None:
    if not lead_visible(actor, lead):
        raise ForbiddenError("Lead is assigned to another operator", reason="other_operator")


def requirements_dict(req: Requirements | None) -> dict[str, Any]:
    return req.model_dump(mode="json", exclude_none=True) if req is not None else {}


async def history(db: AsyncSession, shop_id: UUID, entity_type: str, entity_id: UUID) -> History:
    """Kim va qachon — `transition_log` dan, eskisi birinchi. Erkin matn sabab xodimga ko'rinadi."""
    rows = list(
        (
            await db.execute(
                select(TransitionLog)
                .where(
                    TransitionLog.shop_id == shop_id,
                    TransitionLog.entity_type == entity_type,
                    TransitionLog.entity_id == entity_id,
                )
                .order_by(TransitionLog.occurred_at, TransitionLog.id)
            )
        ).scalars()
    )
    ids = {r.actor_id for r in rows if r.actor_id is not None}
    names: dict[UUID, str] = {}
    if ids:
        found = await db.execute(select(Principal.id, Principal.full_name).where(Principal.id.in_(ids)))
        names = {pid: name for pid, name in found}
    return History(
        items=[
            QuoteTransitionOut(
                at=r.occurred_at,
                command=r.command,
                from_status=r.from_status,
                to_status=r.to_status,
                actor_type=r.actor_type,
                actor_name=names.get(r.actor_id) if r.actor_id else None,
                reason=r.reason,
            )
            for r in rows
        ]
    )


class LeadService:
    def __init__(
        self, use: UseService, audit: AuditService, conversations: ConversationLookupPort | None = None
    ) -> None:
        self.use = use
        self.audit = audit
        self.conversations = conversations

    async def ensure_conversation(self, db: AsyncSession, shop_id: UUID, conversation_id: UUID) -> None:
        """Suhbat shu shopnikimi (QA 6a F11) — boshqa shop suhbatiga lead/taklif bog'lanmaydi."""
        if self.conversations is None:
            return
        if not await self.conversations.conversation_exists(db, shop_id, conversation_id):
            raise ValidationError("Unknown conversation", fields=[field("conversation_id", "invalid")])

    # ================================================================== o'qish
    async def load(
        self, db: AsyncSession, actor: ActorContext, lead_id: UUID, *, for_update: bool = False
    ) -> Lead:
        query = select(Lead).where(Lead.shop_id == actor.shop_id, Lead.id == lead_id)
        if for_update:
            query = query.with_for_update()
        lead = (await db.execute(query)).scalar_one_or_none()
        if lead is None:
            raise NotFoundError("Lead not found")
        return lead

    async def get(self, db: AsyncSession, actor: ActorContext, lead_id: UUID) -> LeadOut:
        lead = await self.load(db, actor, lead_id)
        ensure_lead_visible(actor, lead)
        return await self.detail(db, actor, lead)

    async def detail(self, db: AsyncSession, actor: ActorContext, lead: Lead) -> LeadOut:
        await db.flush()
        await db.refresh(lead)
        quotes = (
            await db.execute(
                select(Quote, QuoteRevision.total_uzs_minor)
                .outerjoin(
                    QuoteRevision,
                    (QuoteRevision.shop_id == Quote.shop_id)
                    & (QuoteRevision.id == Quote.current_revision_id),
                )
                .where(Quote.shop_id == lead.shop_id, Quote.lead_id == lead.id)
                .order_by(Quote.number)
            )
        ).all()
        names = await member_names(db, lead.shop_id, [lead.assigned_membership_id])
        phone = lead.contact_phone_enc if lead.consent_contact_at else None
        orders = (
            (
                await db.execute(
                    select(Order)
                    .where(Order.shop_id == lead.shop_id, Order.lead_id == lead.id)
                    .order_by(Order.number)
                )
            )
            .scalars()
            .all()
        )
        return LeadOut(
            id=lead.id,
            number=lead.number,
            status=lead.status,
            source=lead.source,
            conversation_id=lead.conversation_id,
            customer_name=lead.customer_name,
            contact_phone=mask_phone(phone),
            has_contact_consent=lead.consent_contact_at is not None,
            requirements=lead.requirements or {},
            budget_minor=lead.budget_minor,
            assigned=member_ref(lead.assigned_membership_id, names),
            lost_reason=lead.lost_reason,
            lost_reason_inferred=lead.lost_reason_inferred,
            lost_note=lead.lost_note,
            won_order_id=lead.won_order_id,
            quotes=[
                QuoteSummary(
                    id=q.id,
                    number=q.number,
                    status=q.status,
                    total_uzs_minor=int(total or 0),
                    current_revision_no=q.current_revision_no,
                    updated_at=q.updated_at,
                )
                for q, total in quotes
            ],
            orders=[
                LeadOrderSummary(
                    id=o.id,
                    number=o.number,
                    status=o.status,
                    source=o.source,
                    total_minor=o.total_minor,
                    created_at=o.created_at,
                )
                for o in orders
            ],
            allowed_actions=self.allowed_actions(actor, lead),
            last_activity_at=lead.last_activity_at,
            created_at=lead.created_at,
            updated_at=lead.updated_at,
            version=lead.version,
        )

    def allowed_actions(self, actor: ActorContext, lead: Lead) -> list[LeadAction]:
        if LEAD_MANAGE not in actor.permissions or not lead_visible(actor, lead):
            return []
        actions: list[LeadAction] = []
        if lead.status in OPEN_LEAD_STATUSES:
            actions += ["EDIT", "LOSE"]
            if lead.status == "NEW":
                actions.append("QUALIFY")
            if QUOTE_EDIT in actor.permissions:
                actions.append("CREATE_QUOTE")
        if lead.status == "LOST":
            actions.append("REOPEN")
        if LEAD_ASSIGN in actor.permissions and lead.status in OPEN_LEAD_STATUSES:
            actions.append("ASSIGN")
        if lead.status in OPEN_LEAD_STATUSES and lead.assigned_membership_id is None:
            actions.append("TAKE")
        return actions

    async def counts(self, db: AsyncSession, actor: ActorContext) -> LeadCounts:
        visible: list[ColumnElement[bool]] = [
            Lead.shop_id == actor.shop_id,
            Lead.merged_into_lead_id.is_(None),
        ]
        if not is_supervisor(actor):
            visible.append(
                or_(Lead.assigned_membership_id.is_(None), Lead.assigned_membership_id == actor.membership_id)
            )
        rows = await db.execute(select(Lead.status, func.count()).where(*visible).group_by(Lead.status))
        by_status = {status: int(n) for status, n in rows}
        open_ = [*visible, Lead.status.in_(OPEN_LEAD_STATUSES)]
        mine = await db.scalar(
            select(func.count()).where(*open_, Lead.assigned_membership_id == actor.membership_id)
        )
        unassigned = await db.scalar(
            select(func.count()).where(*open_, Lead.assigned_membership_id.is_(None))
        )
        return LeadCounts(by_status=by_status, mine=int(mine or 0), unassigned=int(unassigned or 0))

    async def take(
        self, db: AsyncSession, actor: ActorContext, lead_id: UUID, expected_version: int
    ) -> LeadOut:
        """Biriktirilmagan leadni operator o'ziga oladi (navbat)."""
        lead = await self._editable(db, actor, lead_id, expected_version)
        if lead.status not in OPEN_LEAD_STATUSES or lead.assigned_membership_id is not None:
            raise InvalidTransitionError(
                "Lead is not in the queue", entity=LEAD, **{"from": lead.status}, command="TAKE"
            )
        lead.assigned_membership_id = actor.membership_id
        lead.last_activity_at = utcnow()
        await db.flush()
        await self.audit.record(
            db,
            action="commerce.lead.taken",
            entity_type=LEAD,
            entity_id=lead.id,
            actor=actor,
            entity_version=lead.version,
        )
        await self.event(db, actor, lead, "commerce.lead.assigned")
        return await self.detail(db, actor, lead)

    async def list_leads(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        statuses: list[str] | None,
        assigned: str | None,
        q: str | None,
        source: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> LeadList:
        conditions: list[ColumnElement[bool]] = [
            Lead.shop_id == actor.shop_id,
            Lead.merged_into_lead_id.is_(None),
        ]
        if not is_supervisor(actor):
            conditions.append(
                or_(Lead.assigned_membership_id.is_(None), Lead.assigned_membership_id == actor.membership_id)
            )
        if statuses:
            conditions.append(Lead.status.in_(statuses))
        if source:
            conditions.append(Lead.source == source)
        if assigned == "me":
            conditions.append(Lead.assigned_membership_id == actor.membership_id)
        elif assigned == "unassigned":
            conditions.append(Lead.assigned_membership_id.is_(None))
        elif assigned:
            try:
                conditions.append(Lead.assigned_membership_id == UUID(assigned))
            except ValueError as exc:
                raise ValidationError("Invalid filter", fields=[field("assigned", "invalid_format")]) from exc
        if q:
            text = q.strip().lstrip("Ll-#")
            if text.isdigit() and len(text) <= 9:
                conditions.append(Lead.number == int(text))
            else:
                pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                conditions.append(Lead.customer_name.ilike(pattern, escape="\\"))
        if cursor:
            values = read_cursor(cursor, "lead", ("t", "id"))
            at, after = cursor_time(values["t"]), cursor_uuid(values["id"])
            conditions.append(
                or_(Lead.last_activity_at < at, (Lead.last_activity_at == at) & (Lead.id < after))
            )
        quote_count = (
            select(func.count(Quote.id))
            .where(Quote.shop_id == Lead.shop_id, Quote.lead_id == Lead.id)
            .correlate(Lead)
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(Lead, quote_count)
                .where(*conditions)
                .order_by(Lead.last_activity_at.desc(), Lead.id.desc())
                .limit(limit + 1)
            )
        ).all()
        page = rows[:limit]
        names = await member_names(db, actor.shop_id, [lead.assigned_membership_id for lead, _ in page])
        items = [
            LeadListItem(
                id=lead.id,
                number=lead.number,
                status=lead.status,
                source=lead.source,
                customer_name=lead.customer_name,
                budget_minor=lead.budget_minor,
                assigned=member_ref(lead.assigned_membership_id, names),
                quote_count=int(count),
                last_activity_at=lead.last_activity_at,
                updated_at=lead.updated_at,
            )
            for lead, count in page
        ]
        last = page[-1][0] if page else None
        return LeadList(
            items=items,
            next_cursor=make_cursor("lead", t=last.last_activity_at, id=last.id)
            if last and len(rows) > limit
            else None,
            has_more=len(rows) > limit,
        )

    async def history(self, db: AsyncSession, actor: ActorContext, lead_id: UUID) -> History:
        lead = await self.load(db, actor, lead_id)
        ensure_lead_visible(actor, lead)
        return await history(db, lead.shop_id, LEAD, lead.id)

    # ================================================================== yozish
    async def create(
        self,
        db: AsyncSession,
        actor: ActorContext,
        data: LeadCreate,
        *,
        source: str = "STAFF",
        ai_request_id: str | None = None,
    ) -> Lead:
        """Bitta suhbatda bitta ochiq lead (unikal indeks): bor bo'lsa — o'sha qaytadi (Q1)."""
        assert actor.shop_id is not None
        if data.conversation_id is not None:
            await self.ensure_conversation(db, actor.shop_id, data.conversation_id)
            existing = await self.open_for_conversation(db, actor.shop_id, data.conversation_id)
            if existing is not None:
                ensure_lead_visible(actor, existing)  # QA 6a F4: boshqa operatorning leadi ochilmaydi
                return existing
        phone = None
        if data.contact_phone:
            if not data.consent_contact:  # rozilik yo'q — telefon saqlanmaydi (BL-042)
                raise ValidationError("Consent required", fields=[field("consent_contact", "required")])
            phone = normalize_phone(data.contact_phone, "contact_phone")
        assignee = data.assigned_membership_id
        if assignee is not None and assignee != actor.membership_id:
            if LEAD_ASSIGN not in actor.permissions:
                raise ForbiddenError("Only a manager assigns leads", permission=LEAD_ASSIGN)
            await self._ensure_assignee(db, actor.shop_id, assignee)
        if assignee is None and actor.actor_type == "STAFF" and not is_supervisor(actor):
            assignee = actor.membership_id  # operator yaratsa — o'ziga
        req = requirements_dict(data.requirements)
        lead = Lead(
            shop_id=actor.shop_id,
            number=await next_number(db, "lead_counters", actor.shop_id),
            status="NEW",
            source=source,
            conversation_id=data.conversation_id,
            customer_name=data.customer_name,
            contact_phone_enc=phone,
            contact_phone_hmac=search_hmac(phone) if phone else None,
            consent_contact_at=utcnow() if phone else None,
            requirements=req,
            budget_minor=req.get("budget_minor"),
            assigned_membership_id=assignee,
            ai_request_id=ai_request_id,
            created_by=actor.membership_id,
            last_activity_at=utcnow(),
        )
        try:
            # QA 6a F5: qo'shish ham savepoint ichida — unikal indeks to'qnashuvi faqat savepoint'ni bekor
            # qiladi, tashqi tranzaksiya sog' qoladi va mavjud lead qaytadi (500 emas)
            async with db.begin_nested():
                db.add(lead)
                await db.flush()
        except IntegrityError:  # parallel ikkinchi so'rov shu suhbatga lead ochib ulgurdi
            if data.conversation_id is None:
                raise
            existing = await self.open_for_conversation(db, actor.shop_id, data.conversation_id)
            if existing is None:
                raise
            ensure_lead_visible(actor, existing)
            return existing
        await self.audit.record(
            db,
            action="commerce.lead.created",
            entity_type=LEAD,
            entity_id=lead.id,
            actor=actor,
            entity_version=lead.version,
            diff={"source": source, "has_contact": phone is not None},
        )
        await self.event(db, actor, lead, "commerce.lead.created")
        return lead

    async def open_for_conversation(
        self, db: AsyncSession, shop_id: UUID, conversation_id: UUID
    ) -> Lead | None:
        return (
            await db.execute(
                select(Lead).where(
                    Lead.shop_id == shop_id,
                    Lead.conversation_id == conversation_id,
                    Lead.status.in_(OPEN_LEAD_STATUSES),
                    Lead.merged_into_lead_id.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def update(
        self, db: AsyncSession, actor: ActorContext, lead_id: UUID, expected_version: int, data: LeadUpdate
    ) -> LeadOut:
        lead = await self._editable(db, actor, lead_id, expected_version)
        _ensure_open(lead, "EDIT")
        wanted = data.model_dump(exclude_unset=True)
        changed: list[str] = []
        if "customer_name" in wanted:
            lead.customer_name = data.customer_name
            changed.append("customer_name")
        if "requirements" in wanted:
            req = requirements_dict(data.requirements)
            lead.requirements = req
            lead.budget_minor = req.get("budget_minor")
            changed.append("requirements")
        if changed:
            lead.last_activity_at = utcnow()
            await db.flush()
            await self.audit.record(
                db,
                action="commerce.lead.updated",
                entity_type=LEAD,
                entity_id=lead.id,
                actor=actor,
                entity_version=lead.version,
                diff={"changed_fields": changed},
            )
            await self.event(db, actor, lead, "commerce.lead.updated")
        return await self.detail(db, actor, lead)

    async def qualify(
        self, db: AsyncSession, actor: ActorContext, lead_id: UUID, expected_version: int
    ) -> LeadOut:
        lead = await self._editable(db, actor, lead_id, expected_version)
        await self.transition(db, actor, lead, "QUALIFY", "QUALIFIED")
        return await self.detail(db, actor, lead)

    async def lose(
        self,
        db: AsyncSession,
        actor: ActorContext,
        lead_id: UUID,
        expected_version: int,
        reason: str,
        note: str | None,
    ) -> LeadOut:
        lead = await self._editable(db, actor, lead_id, expected_version)
        lead.lost_reason, lead.lost_note, lead.lost_reason_inferred = reason, note, False
        await self.transition(db, actor, lead, "LOSE", "LOST", reason=reason)
        return await self.detail(db, actor, lead)

    async def reopen(
        self, db: AsyncSession, actor: ActorContext, lead_id: UUID, expected_version: int
    ) -> LeadOut:
        lead = await self.load(db, actor, lead_id, for_update=True)
        ensure_lead_visible(actor, lead)
        check_version(lead.version, expected_version)
        if lead.conversation_id is not None:  # suhbatda boshqa ochiq lead bo'lsa — qaytarib bo'lmaydi
            other = await self.open_for_conversation(db, lead.shop_id, lead.conversation_id)
            if other is not None and other.id != lead.id:
                raise InvalidTransitionError(
                    "Conversation already has an open lead", entity=LEAD, command="REOPEN", lead_id=other.id
                )
        lead.lost_reason = lead.lost_note = None
        await self.transition(db, actor, lead, "REOPEN", "QUALIFIED")
        return await self.detail(db, actor, lead)

    async def assign(
        self,
        db: AsyncSession,
        actor: ActorContext,
        lead_id: UUID,
        expected_version: int,
        membership_id: UUID | None,
    ) -> LeadOut:
        lead = await self._editable(db, actor, lead_id, expected_version)
        _ensure_open(lead, "ASSIGN")
        if membership_id is not None:
            assert actor.shop_id is not None
            await self._ensure_assignee(db, actor.shop_id, membership_id)
        lead.assigned_membership_id = membership_id
        lead.last_activity_at = utcnow()
        await db.flush()
        await self.audit.record(
            db,
            action="commerce.lead.assigned",
            entity_type=LEAD,
            entity_id=lead.id,
            actor=actor,
            entity_version=lead.version,
            diff={"assigned_membership_id": str(membership_id) if membership_id else None},
        )
        await self.event(db, actor, lead, "commerce.lead.assigned")
        return await self.detail(db, actor, lead)

    # ================================================================== avtomatik o'tishlar
    async def mark_quoted(self, db: AsyncSession, actor: ActorContext, lead: Lead) -> None:
        """Birinchi taklif yuborilganda (FSM-05): NEW/QUALIFIED → QUOTED; boshqa holatda faqat faollik."""
        lead.last_activity_at = utcnow()
        if lead.status in ("NEW", "QUALIFIED"):
            await self.transition(db, actor, lead, "MARK_QUOTED", "QUOTED")
        else:
            await db.flush()

    async def mark_won(self, db: AsyncSession, shop_id: UUID, lead_id: UUID, order_id: UUID) -> bool:
        lead = (
            await db.execute(
                select(Lead).where(Lead.shop_id == shop_id, Lead.id == lead_id).with_for_update()
            )
        ).scalar_one_or_none()
        if lead is None or lead.status not in OPEN_LEAD_STATUSES:
            return False
        lead.won_order_id = order_id
        await self.transition(db, ActorContext.system(shop_id), lead, "WIN", "WON")
        return True

    async def touch(self, db: AsyncSession, lead: Lead) -> None:
        lead.last_activity_at = utcnow()
        await db.flush()

    # ================================================================== ichki
    async def transition(
        self,
        db: AsyncSession,
        actor: ActorContext,
        lead: Lead,
        command: str,
        target: str,
        *,
        reason: str | None = None,
    ) -> None:
        rule = self.use.validate_transition(LEAD, lead.status, target, command, actor)
        from_status = lead.status
        lead.status = rule.to_status
        lead.last_activity_at = utcnow()
        await db.flush()
        await self.use.log_transition(db, entity_id=lead.id, rule=rule, actor=actor, reason=reason)
        await self.audit.record(
            db,
            action=f"commerce.lead.{command.lower()}",
            entity_type=LEAD,
            entity_id=lead.id,
            actor=actor,
            entity_version=lead.version,
            diff={"status": {"old": from_status, "new": lead.status}},
        )
        await self.event(db, actor, lead, "commerce.lead.status_changed", from_status=from_status)

    async def event(
        self, db: AsyncSession, actor: ActorContext, lead: Lead, event_type: str, **extra: Any
    ) -> None:
        await db.flush()
        await write_outbox(
            db,
            schema="commerce",
            event_type=event_type,
            actor=actor,
            shop_id=lead.shop_id,
            aggregate_type=LEAD,
            aggregate_id=lead.id,
            aggregate_version=lead.version,
            payload={  # PII yo'q: ism, telefon, talablar matni event'ga tushmaydi (05 §3.1)
                "lead_id": lead.id,
                "number": lead.number,
                "status": lead.status,
                "source": lead.source,
                "conversation_id": lead.conversation_id,
                "assigned_staff_id": lead.assigned_membership_id,
                "budget_minor": lead.budget_minor,
                "lost_reason": lead.lost_reason,
                "won_order_id": lead.won_order_id,
                **extra,
            },
        )

    async def _editable(
        self, db: AsyncSession, actor: ActorContext, lead_id: UUID, expected_version: int
    ) -> Lead:
        lead = await self.load(db, actor, lead_id, for_update=True)
        ensure_lead_visible(actor, lead)
        check_version(lead.version, expected_version)
        return lead

    async def _ensure_assignee(self, db: AsyncSession, shop_id: UUID, membership_id: UUID) -> None:
        member = (
            await db.execute(
                select(Membership).where(
                    Membership.shop_id == shop_id,
                    Membership.id == membership_id,
                    Membership.status == "ACTIVE",
                    Membership.role.in_(_LEAD_OWNER_ROLES),
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise ValidationError(
                "Member cannot own leads", fields=[field("membership_id", "invalid_choice")]
            )


def _ensure_open(lead: Lead, command: str) -> None:
    """Yopilgan (WON/LOST) leadni tahrirlab va biriktirib bo'lmaydi (QA 6a F10)."""
    if lead.status not in OPEN_LEAD_STATUSES:
        raise InvalidTransitionError("Lead is closed", entity=LEAD, **{"from": lead.status}, command=command)


def lead_due(last_activity_at: datetime, now: datetime, days: int) -> bool:
    return (now - last_activity_at).days >= days
