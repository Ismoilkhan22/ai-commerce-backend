"""PC takliflari (FSM-06, db/commerce_quotes.md §2–§5, DEC-142 Q3–Q8).

- Narx katalogdan nusxa (BL-041); tekshiruvga yuborishda joriy narxga yangilanib muzlaydi (BL-043, trigger).
- Moslik: qoralamada — jonli; yuborish (SUBMIT), tasdiq (APPROVAL) va qabul (ACCEPT) bosqichlarida muzlatiladi
  (BL-030). BLOCK bo'lsa tekshiruvga ham, tasdiqqa ham o'tmaydi; REVIEW_REQUIRED — tasdiqlovchi dalil yozadi.
- Tasdiq: `ALL` — har taklif qo'lda; `RISKY_ONLY` — moslik PASS va chegirmasiz bo'lsa avtomatik (DEC-102).
  Chegirmali taklif doim qo'lda, tasdiqlovchining limiti ichida (DEC-110, Q8). O'zi tuzganini tasdiqlamaydi.
- Yuborish — faqat xodim (AI emas, Q4): havola `/q/{token}`, bazada faqat xeshi.
- Qabulda narx va moslik qayta tekshiriladi (Q6): o'zgargan bo'lsa QUOTE_CHANGED — yangi versiya yuboriladi.
  O'zgarmagan bo'lsa — DRAFT buyurtma (source QUOTE), qatorlar taklifdan (tasdiqlangan chegirma bilan).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import (
    STALE_RATE_HOURS,
    cursor_time,
    cursor_uuid,
    discount_limit,
    field,
    load_policy,
    make_cursor,
    member_names,
    read_cursor,
)
from app.domains.commerce.events import order_event
from app.domains.commerce.orders.models.orm import Order, OrderLine
from app.domains.commerce.orders.services.order_service import OrderService, next_order_number
from app.domains.commerce.orders.services.pricing import recompute, usable
from app.domains.commerce.orders.services.storefront_service import tracking_hash
from app.domains.commerce.permissions import QUOTE_APPROVE, QUOTE_EDIT, QUOTE_SEND
from app.domains.commerce.quotes.common import (
    apply_line_snapshot,
    compat_out,
    line_role,
    new_token,
    next_number,
    snapshot_findings,
    snapshot_out,
    spec_versions,
    token_hash,
    totals,
)
from app.domains.commerce.quotes.models.orm import (
    OPEN_LEAD_STATUSES,
    Lead,
    Quote,
    QuoteCompatibilitySnapshot,
    QuoteLine,
    QuoteRevision,
)
from app.domains.commerce.quotes.schemas import (
    History,
    LeadCreate,
    LeadOut,
    LineAvailability,
    QuoteAction,
    QuoteCreate,
    QuoteLineIn,
    QuoteLineOut,
    QuoteList,
    QuoteListItem,
    QuoteOut,
    Requirements,
    RevisionOut,
    RevisionSummary,
)
from app.domains.commerce.quotes.services.lead_service import (
    LeadService,
    ensure_lead_visible,
    history,
    is_supervisor,
    requirements_dict,
)
from app.domains.commerce.quotes.state_machine import QUOTE
from app.domains.commerce.schemas import member_ref
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.tasks import QUOTE_APPROVAL, REQUESTER_PARAM, TaskService
from app.platform.shops.models.orm import Shop, ShopPolicy
from app.platform.shops.services.sales_gate import ensure_shop_can_sell
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort, SkuSnapshot
from app.shared.contracts.commerce import StockQueryPort
from app.shared.contracts.compatibility import BuildLine, CompatibilityResult
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import (
    BusinessRuleError,
    DiscountLimitExceededError,
    ExchangeRateStaleError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    ProductNotAvailableError,
    QuoteChangedError,
    QuoteExpiredError,
    SelfApprovalError,
    ValidationError,
)
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.i18n.locale import get_display_locale
from app.shared.money import MAX_SAFE_MINOR
from app.shared.pagination import DEFAULT_LIMIT
from app.shared.types.actor import ActorContext

_tasks = TaskService()
DECISION_RANK = {"PASS": 0, "REVIEW_REQUIRED": 1, "BLOCK": 2}


class QuoteService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        catalog: CatalogQueryPort,
        leads: LeadService,
        orders: OrderService,
        public_url_template: str | None = None,
        stock: StockQueryPort | None = None,
    ) -> None:
        self.use = use
        self.audit = audit
        self.catalog = catalog
        self.leads = leads
        self.orders = orders
        self.public_url_template = public_url_template
        self.stock = stock

    # ================================================================== o'qish
    async def load(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, *, for_update: bool = False
    ) -> Quote:
        query = select(Quote).where(Quote.shop_id == actor.shop_id, Quote.id == quote_id)
        if for_update:
            query = query.with_for_update()
        quote = (await db.execute(query)).scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found")
        return quote

    async def lead_of(self, db: AsyncSession, quote: Quote) -> Lead:
        lead = (
            await db.execute(select(Lead).where(Lead.shop_id == quote.shop_id, Lead.id == quote.lead_id))
        ).scalar_one()
        return lead

    async def revision(self, db: AsyncSession, quote: Quote) -> QuoteRevision:
        assert quote.current_revision_id is not None
        return (
            await db.execute(
                select(QuoteRevision).where(
                    QuoteRevision.shop_id == quote.shop_id, QuoteRevision.id == quote.current_revision_id
                )
            )
        ).scalar_one()

    @staticmethod
    async def lines(db: AsyncSession, revision: QuoteRevision) -> list[QuoteLine]:
        return list(
            (
                await db.execute(
                    select(QuoteLine)
                    .where(QuoteLine.shop_id == revision.shop_id, QuoteLine.quote_revision_id == revision.id)
                    .order_by(QuoteLine.position)
                )
            ).scalars()
        )

    async def get(self, db: AsyncSession, actor: ActorContext, quote_id: UUID) -> QuoteOut:
        quote = await self.load(db, actor, quote_id)
        lead = await self.lead_of(db, quote)
        ensure_lead_visible(actor, lead)
        return await self.detail(db, actor, quote, lead)

    async def detail(
        self, db: AsyncSession, actor: ActorContext, quote: Quote, lead: Lead | None = None
    ) -> QuoteOut:
        await db.flush()
        await db.refresh(quote)  # server tomonidagi `updated_at` / `version` — yangilangan qiymat
        lead = lead or await self.lead_of(db, quote)
        revision = await self.revision(db, quote)
        await db.refresh(revision)
        lines = await self.lines(db, revision)
        compatibility = None
        if quote.status == "DRAFT":
            if lines:
                result = await self.check(db, quote.shop_id, lines)
                compatibility = compat_out(result, "LIVE", utcnow())
        else:
            snapshot = (
                (
                    await db.execute(
                        select(QuoteCompatibilitySnapshot)
                        .where(
                            QuoteCompatibilitySnapshot.shop_id == quote.shop_id,
                            QuoteCompatibilitySnapshot.quote_revision_id == revision.id,
                        )
                        .order_by(QuoteCompatibilitySnapshot.checked_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            compatibility = snapshot_out(snapshot) if snapshot else None
        revisions = (
            (
                await db.execute(
                    select(QuoteRevision)
                    .where(QuoteRevision.shop_id == quote.shop_id, QuoteRevision.quote_id == quote.id)
                    .order_by(QuoteRevision.revision)
                )
            )
            .scalars()
            .all()
        )
        names = await member_names(db, quote.shop_id, [quote.created_by, revision.approved_by])
        return QuoteOut(
            id=quote.id,
            number=quote.number,
            lead_id=lead.id,
            lead_number=lead.number,
            conversation_id=quote.conversation_id,
            status=quote.status,
            created_by_kind=quote.created_by_kind,
            created_by=member_ref(quote.created_by, names),
            revision=revision.revision,
            revision_id=revision.id,
            requirements=revision.requirements or {},
            lines=[_line_out(line) for line in lines],
            subtotal_uzs_minor=revision.subtotal_uzs_minor,
            discount_uzs_minor=revision.discount_uzs_minor,
            total_uzs_minor=revision.total_uzs_minor,
            compatibility=compatibility,
            approval_mode=revision.approval_mode,
            approved_by=member_ref(revision.approved_by, names),
            approved_at=revision.approved_at,
            approval_note=revision.approval_note,
            returned_note=revision.returned_note,
            sent_at=quote.sent_at,
            expires_at=quote.expires_at,
            accepted_at=quote.accepted_at,
            accepted_order_id=quote.accepted_order_id,
            rejected_at=quote.rejected_at,
            reject_reason=quote.reject_reason,
            price_changed=await self._price_changed(db, quote, lines),
            approver_discount_limit_pct=discount_limit(actor, await load_policy(db, quote.shop_id)),
            revisions=[
                RevisionSummary(
                    id=r.id,
                    revision=r.revision,
                    total_uzs_minor=r.total_uzs_minor,
                    compatibility_decision=r.compatibility_decision,
                    submitted_at=r.submitted_at,
                    approved_at=r.approved_at,
                    returned_note=r.returned_note,
                    created_at=r.created_at,
                )
                for r in revisions
            ],
            availability=await self._availability(db, quote.shop_id, lines),
            allowed_actions=self.allowed_actions(actor, quote, lead, revision),
            created_at=quote.created_at,
            updated_at=quote.updated_at,
            version=quote.version,
        )

    async def _availability(
        self, db: AsyncSession, shop_id: UUID, lines: Sequence[QuoteLine]
    ) -> list[LineAvailability]:
        """Faqat ma'lumot (QA 6a F14): taklif band qilmaydi va qoldiq yetmasa ham bloklanmaydi (DEC-100b) —
        xodim tasdiqlashdan oldin ko'radi, operator buyurtmani tasdiqlaganda qoldiq tekshiriladi."""
        if self.stock is None or not lines:
            return []
        found = await self.stock.availability(db, shop_id, [line.sku_id for line in lines])
        out: list[LineAvailability] = []
        for line in lines:
            item = found.get(line.sku_id)
            available = item.available if item is not None else 0
            out.append(
                LineAvailability(
                    sku_id=line.sku_id, qty=line.qty, available=available, enough=available >= line.qty
                )
            )
        return out

    async def _price_changed(self, db: AsyncSession, quote: Quote, lines: Sequence[QuoteLine]) -> bool:
        """Muzlagan (tasdiqlangan/yuborilgan) narx katalogdan farq qiladimi — qabulda QUOTE_CHANGED."""
        if quote.status not in ("APPROVED", "SENT") or not lines:
            return False
        snapshots = await self.catalog.get_skus(db, quote.shop_id, [line.sku_id for line in lines])
        for line in lines:
            snap = snapshots.get(line.sku_id)
            if not usable(snap) or (snap is not None and snap.uzs_amount_minor != line.unit_price_uzs_minor):
                return True
        return False

    async def revision_detail(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, number: int
    ) -> RevisionOut:
        quote = await self.load(db, actor, quote_id)
        ensure_lead_visible(actor, await self.lead_of(db, quote))
        revision = (
            await db.execute(
                select(QuoteRevision).where(
                    QuoteRevision.shop_id == quote.shop_id,
                    QuoteRevision.quote_id == quote.id,
                    QuoteRevision.revision == number,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise NotFoundError("Revision not found")
        snapshots = (
            (
                await db.execute(
                    select(QuoteCompatibilitySnapshot)
                    .where(
                        QuoteCompatibilitySnapshot.shop_id == quote.shop_id,
                        QuoteCompatibilitySnapshot.quote_revision_id == revision.id,
                    )
                    .order_by(QuoteCompatibilitySnapshot.checked_at)
                )
            )
            .scalars()
            .all()
        )
        names = await member_names(db, quote.shop_id, [revision.approved_by])
        return RevisionOut(
            id=revision.id,
            revision=revision.revision,
            requirements=revision.requirements or {},
            lines=[_line_out(line) for line in await self.lines(db, revision)],
            subtotal_uzs_minor=revision.subtotal_uzs_minor,
            discount_uzs_minor=revision.discount_uzs_minor,
            total_uzs_minor=revision.total_uzs_minor,
            compatibility=[snapshot_out(s) for s in snapshots],
            submitted_at=revision.submitted_at,
            approved_by=member_ref(revision.approved_by, names),
            approved_at=revision.approved_at,
            approval_mode=revision.approval_mode,
            approval_note=revision.approval_note,
            returned_note=revision.returned_note,
            created_at=revision.created_at,
        )

    def can_edit(self, actor: ActorContext, quote: Quote, lead: Lead) -> bool:
        if QUOTE_EDIT not in actor.permissions:
            return False
        if is_supervisor(actor):
            return True
        return quote.created_by == actor.membership_id or lead.assigned_membership_id in (
            None,
            actor.membership_id,
        )

    @staticmethod
    def _authors(quote: Quote, revision: QuoteRevision) -> set[UUID]:
        """Tasdiqlay olmaydiganlar (DEC-109, QA 6a F1): taklifni tuzgan, joriy versiya qatorlarini oxirgi
        tahrirlagan va tekshiruvga yuborgan xodimlar. Versiyani qaytargan menejer (yangi versiya muallifi)
        bu ro'yxatda yo'q — u qatorlarga tegmagan bo'lsa, qayta yuborilganini tasdiqlay oladi."""
        ids = (quote.created_by, revision.edited_by, revision.submitted_by)
        return {i for i in ids if i is not None}

    def allowed_actions(
        self, actor: ActorContext, quote: Quote, lead: Lead, revision: QuoteRevision
    ) -> list[QuoteAction]:
        editor = self.can_edit(actor, quote, lead)
        approver = QUOTE_APPROVE in actor.permissions
        sender = QUOTE_SEND in actor.permissions and (editor or is_supervisor(actor))
        actions: list[QuoteAction] = []
        status = quote.status
        if status == "DRAFT" and editor:
            actions += ["EDIT", "SUBMIT", "CANCEL"]
        elif status == "REVIEW":
            if approver and actor.membership_id not in self._authors(quote, revision):
                actions.append("APPROVE")
            if approver:
                actions.append("RETURN")
            if approver or editor:
                actions.append("CANCEL")
        elif status == "APPROVED":
            if sender:
                actions.append("SEND")
            if approver or editor:
                actions.append("CANCEL")
        elif status == "SENT":
            if sender:
                actions += ["ACCEPT", "REJECT"]
            if editor:
                actions.append("REVISE")
        elif status in ("REJECTED", "EXPIRED") and editor:
            actions.append("REVISE")
        return actions

    async def list_quotes(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        statuses: list[str] | None,
        lead_id: UUID | None,
        mine: bool,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> QuoteList:
        conditions: list[ColumnElement[bool]] = [Quote.shop_id == actor.shop_id]
        query = (
            select(
                Quote,
                Lead.number,
                QuoteRevision.total_uzs_minor,
                QuoteRevision.compatibility_decision,
                Lead.customer_name,
            )
            .join(Lead, (Lead.shop_id == Quote.shop_id) & (Lead.id == Quote.lead_id))
            .outerjoin(
                QuoteRevision,
                (QuoteRevision.shop_id == Quote.shop_id) & (QuoteRevision.id == Quote.current_revision_id),
            )
        )
        if not is_supervisor(actor):
            conditions.append(
                or_(
                    Quote.created_by == actor.membership_id,
                    Lead.assigned_membership_id.is_(None),
                    Lead.assigned_membership_id == actor.membership_id,
                )
            )
        if statuses:
            conditions.append(Quote.status.in_(statuses))
        if lead_id:
            conditions.append(Quote.lead_id == lead_id)
        if mine:
            conditions.append(
                or_(
                    Quote.created_by == actor.membership_id,
                    Lead.assigned_membership_id == actor.membership_id,
                )
            )
        if cursor:
            values = read_cursor(cursor, "quote", ("t", "id"))
            at, after = cursor_time(values["t"]), cursor_uuid(values["id"])
            conditions.append(or_(Quote.updated_at < at, (Quote.updated_at == at) & (Quote.id < after)))
        rows = (
            await db.execute(
                query.where(*conditions).order_by(Quote.updated_at.desc(), Quote.id.desc()).limit(limit + 1)
            )
        ).all()
        page = rows[:limit]
        names = await member_names(db, actor.shop_id, [q.created_by for q, *_ in page])
        items = [
            QuoteListItem(
                id=q.id,
                number=q.number,
                lead_id=q.lead_id,
                lead_number=lead_number,
                customer_name=customer_name,
                status=q.status,
                total_uzs_minor=int(total or 0),
                compatibility_decision=decision,
                created_by=member_ref(q.created_by, names),
                expires_at=q.expires_at,
                updated_at=q.updated_at,
            )
            for q, lead_number, total, decision, customer_name in page
        ]
        last = page[-1][0] if page else None
        return QuoteList(
            items=items,
            next_cursor=make_cursor("quote", t=last.updated_at, id=last.id)
            if last and len(rows) > limit
            else None,
            has_more=len(rows) > limit,
        )

    async def history(self, db: AsyncSession, actor: ActorContext, quote_id: UUID) -> History:
        quote = await self.load(db, actor, quote_id)
        ensure_lead_visible(actor, await self.lead_of(db, quote))
        return await history(db, quote.shop_id, QUOTE, quote.id)

    # ================================================================== qoralama
    async def create(self, db: AsyncSession, actor: ActorContext, data: QuoteCreate) -> QuoteOut:
        assert actor.shop_id is not None
        if data.conversation_id is not None:
            await self.leads.ensure_conversation(db, actor.shop_id, data.conversation_id)
        if data.lead_id is not None:
            lead = await self.leads.load(db, actor, data.lead_id, for_update=True)
            ensure_lead_visible(actor, lead)
            if lead.status not in OPEN_LEAD_STATUSES:
                raise InvalidTransitionError(
                    "Lead is closed", entity="commerce.lead", **{"from": lead.status}, command="CREATE_QUOTE"
                )
        else:  # lead bo'lmasa — avtomatik (suhbatdan bo'lsa — o'sha suhbatning ochiq leadi)
            lead = await self.leads.create(
                db,
                actor,
                LeadCreate(
                    conversation_id=data.conversation_id, requirements=data.requirements or Requirements()
                ),
            )
        requirements = (
            requirements_dict(data.requirements) if data.requirements else (lead.requirements or {})
        )
        quote = Quote(
            shop_id=actor.shop_id,
            number=await next_number(db, "quote_counters", actor.shop_id),
            lead_id=lead.id,
            conversation_id=data.conversation_id or lead.conversation_id,
            status="DRAFT",
            current_revision_no=1,
            created_by_kind="AI" if actor.actor_type == "AI_AGENT" else "STAFF",
            created_by=actor.membership_id,
        )
        db.add(quote)
        await db.flush()
        revision = QuoteRevision(
            shop_id=actor.shop_id,
            quote_id=quote.id,
            revision=1,
            requirements=requirements,
            created_by_kind=quote.created_by_kind,
            created_by=actor.membership_id,
            edited_by=actor.membership_id,
        )
        db.add(revision)
        await db.flush()
        quote.current_revision_id = revision.id
        await db.flush()
        if data.lines:
            await self._set_lines(db, actor, revision, data.lines)
        await self.leads.touch(db, lead)
        await self.audit.record(
            db,
            action="commerce.quote.created",
            entity_type=QUOTE,
            entity_id=quote.id,
            actor=actor,
            entity_version=quote.version,
            diff={"lines": len(data.lines), "lead_id": str(lead.id)},
        )
        await self.event(db, actor, quote, revision, "commerce.quote.created")
        return await self.detail(db, actor, quote, lead)

    async def set_lines(
        self,
        db: AsyncSession,
        actor: ActorContext,
        quote_id: UUID,
        expected_version: int,
        items: Sequence[QuoteLineIn],
    ) -> QuoteOut:
        quote, lead = await self._editable(db, actor, quote_id, expected_version, "EDIT")
        revision = await self.revision(db, quote)
        await self._set_lines(db, actor, revision, items)
        revision.edited_by = actor.membership_id
        quote.updated_at = utcnow()  # agregat o'zgardi — versiya oshadi (If-Match)
        await db.flush()
        await self.audit.record(
            db,
            action="commerce.quote.lines_set",
            entity_type=QUOTE,
            entity_id=quote.id,
            actor=actor,
            entity_version=quote.version,
            diff={"lines": len(items)},
        )
        await self.event(db, actor, quote, revision, "commerce.quote.updated")
        return await self.detail(db, actor, quote, lead)

    async def _set_lines(
        self, db: AsyncSession, actor: ActorContext, revision: QuoteRevision, items: Sequence[QuoteLineIn]
    ) -> None:
        assert actor.shop_id is not None
        seen: set[UUID] = set()
        for index, item in enumerate(items):
            if item.sku_id in seen:  # bir versiyada bir SKU — bitta qator (qty bilan)
                raise ValidationError("Duplicate SKU", fields=[field(f"lines[{index}].sku_id", "not_unique")])
            seen.add(item.sku_id)
            if item.discount_pct > 0 and actor.actor_type != "STAFF":  # AI chegirma qo'ya olmaydi (DEC-110)
                raise ForbiddenError("Only staff can set a discount", reason="discount_staff_only")
        ids = [i.sku_id for i in items]
        snapshots = await self.catalog.get_skus(db, actor.shop_id, ids)
        categories = await self.catalog.sku_spec_categories(db, actor.shop_id, ids)
        _ensure_usable(items, snapshots)
        await db.execute(
            delete(QuoteLine).where(
                QuoteLine.shop_id == revision.shop_id, QuoteLine.quote_revision_id == revision.id
            )
        )
        new_lines: list[QuoteLine] = []
        for position, item in enumerate(items):
            line = QuoteLine(
                shop_id=revision.shop_id,
                quote_revision_id=revision.id,
                position=position,
                role=line_role(categories.get(item.sku_id)),
                sku_id=item.sku_id,
                qty=item.qty,
            )
            apply_line_snapshot(line, snapshots[item.sku_id], item.discount_pct)
            db.add(line)
            new_lines.append(line)
        await db.flush()
        self._apply_totals(revision, new_lines, snapshots)
        await db.flush()

    @staticmethod
    def _apply_totals(
        revision: QuoteRevision, lines: Sequence[QuoteLine], snapshots: dict[UUID, SkuSnapshot]
    ) -> None:
        subtotal, discount, total = totals(lines)
        if total > MAX_SAFE_MINOR:
            raise ValidationError("Quote total too large", fields=[field("lines", "max_value")])
        revision.subtotal_uzs_minor, revision.discount_uzs_minor, revision.total_uzs_minor = (
            subtotal,
            discount,
            total,
        )
        usd = next((snapshots[line.sku_id] for line in lines if line.currency == "USD"), None)
        revision.exchange_rate_id = usd.exchange_rate_id if usd else None
        revision.exchange_rate_snapshot = usd.exchange_rate if usd else None

    # ================================================================== tekshiruv va tasdiq
    async def submit(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int
    ) -> QuoteOut:
        quote, lead = await self._editable(db, actor, quote_id, expected_version, "SUBMIT")
        assert actor.shop_id is not None
        revision = await self.revision(db, quote)
        lines = await self.lines(db, revision)
        if not lines:
            raise ValidationError("Quote has no lines", fields=[field("lines", "required")])
        # Joriy narxga yangilanadi va muzlaydi (BL-043): tekshiruvchi xaridor ko'radigan narxni ko'radi
        snapshots = await self.catalog.get_skus(db, actor.shop_id, [line.sku_id for line in lines])
        _ensure_rate_fresh(snapshots)
        _ensure_usable(lines, snapshots)
        result = await self.check(db, quote.shop_id, lines)
        if result.decision == "BLOCK":
            raise _rule_block(result)
        for line in lines:
            apply_line_snapshot(line, snapshots[line.sku_id], line.discount_pct)
            evidence = result.spec_versions.get(line.sku_id)
            line.spec_id, line.spec_version = (
                (evidence.spec_id, evidence.version) if evidence else (None, None)
            )
        await db.flush()
        self._apply_totals(revision, lines, snapshots)
        now = utcnow()
        revision.submitted_at = now
        revision.submitted_by = actor.membership_id
        revision.compatibility_decision = result.decision
        revision.ruleset_version = result.rule_set_version
        await db.flush()
        await self._snapshot(db, revision, "SUBMIT", result)
        policy = await db.get(ShopPolicy, quote.shop_id)
        has_discount = any(line.discount_pct > 0 for line in lines)
        auto = (
            policy is not None
            and policy.quote_approval_mode == "RISKY_ONLY"
            and result.decision == "PASS"
            and result.can_publish_quote
            and not has_discount
        )
        if auto:
            revision.approval_mode, revision.approved_at = "AUTO_RISKY_ONLY", now
            await db.flush()
            await self._transition(db, actor, quote, revision, "AUTO_APPROVE", "APPROVED")
        else:
            await self._transition(db, actor, quote, revision, "SUBMIT", "REVIEW")
            await _tasks.open(
                db,
                shop_id=quote.shop_id,
                actor=actor,
                type=QUOTE_APPROVAL,
                subject_type=QUOTE,
                subject_id=quote.id,
                dedup_key=f"quote_approval:{revision.id}",
                assignee_role="MANAGER",
                params={
                    "quote_number": quote.number,
                    "revision": revision.revision,
                    "decision": result.decision,
                    REQUESTER_PARAM: str(actor.membership_id) if actor.membership_id else None,
                },
            )
        await self.leads.touch(db, lead)
        return await self.detail(db, actor, quote, lead)

    async def approve(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int, note: str | None
    ) -> QuoteOut:
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if QUOTE_APPROVE not in actor.permissions:
            raise ForbiddenError("Approval permission required", permission=QUOTE_APPROVE)
        revision = await self.revision(db, quote)
        self.use.validate_transition(QUOTE, quote.status, "APPROVED", "APPROVE", actor)
        if actor.membership_id in self._authors(quote, revision):
            raise SelfApprovalError("You cannot approve your own quote")  # DEC-109, QA 6a F1
        lines = await self.lines(db, revision)
        policy = await load_policy(db, quote.shop_id)
        limit = discount_limit(actor, policy)
        biggest = max((line.discount_pct for line in lines), default=Decimal(0))
        if biggest > limit:
            raise DiscountLimitExceededError(
                "Discount exceeds your limit",
                limit_pct=str(limit),
                requested_pct=str(biggest),
                approver_role="OWNER",
            )
        await self._ensure_rate_fresh(db, quote.shop_id, lines)
        result = await self.check(db, quote.shop_id, lines)
        # 17 §2: REVIEW_REQUIRED — `can_publish_quote` false, lekin menejer/ega dalil bilan tasdiqlaydi
        if result.decision == "BLOCK":
            raise _rule_block(result)
        if result.decision == "REVIEW_REQUIRED" and not (note and note.strip()):
            raise ValidationError("Evidence note required", fields=[field("note", "required")])
        await self._snapshot(db, revision, "APPROVAL", result)
        revision.approved_by, revision.approved_at = actor.membership_id, utcnow()
        revision.approval_mode, revision.approval_note = "MANUAL", note
        await db.flush()
        await self._transition(db, actor, quote, revision, "APPROVE", "APPROVED")
        await _tasks.resolve(db, shop_id=quote.shop_id, actor=actor, subject_type=QUOTE, subject_id=quote.id)
        return await self.detail(db, actor, quote, lead)

    async def return_(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int, reason: str
    ) -> QuoteOut:
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if QUOTE_APPROVE not in actor.permissions:
            raise ForbiddenError("Approval permission required", permission=QUOTE_APPROVE)
        self.use.validate_transition(QUOTE, quote.status, "DRAFT", "RETURN", actor)
        revision = await self.revision(db, quote)
        revision.returned_note = reason
        await db.flush()
        await self._new_revision(db, actor, quote, revision)
        await self._transition(db, actor, quote, revision, "RETURN", "DRAFT", reason=reason)
        await _tasks.resolve(db, shop_id=quote.shop_id, actor=actor, subject_type=QUOTE, subject_id=quote.id)
        return await self.detail(db, actor, quote, lead)

    async def cancel(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int, reason: str | None
    ) -> QuoteOut:
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if not (self.can_edit(actor, quote, lead) or QUOTE_APPROVE in actor.permissions):
            raise ForbiddenError("Quote is not yours", reason="other_operator")
        revision = await self.revision(db, quote)
        quote.cancelled_at = utcnow()
        await self._transition(db, actor, quote, revision, "CANCEL", "CANCELLED", reason=reason)
        await _tasks.resolve(db, shop_id=quote.shop_id, actor=actor, subject_type=QUOTE, subject_id=quote.id)
        return await self.detail(db, actor, quote, lead)

    async def lose_lead(
        self,
        db: AsyncSession,
        actor: ActorContext,
        lead_id: UUID,
        expected_version: int,
        reason: str,
        note: str | None,
    ) -> LeadOut:
        """Lead yo'qotildi → ochiq takliflari bekor, xaridor havolasi o'chadi, tasdiq vazifalari yopiladi
        (QA 6a F12): yo'qotilgan lead'ning yuborilgan taklifi qabul qilinib buyurtmaga aylanmaydi."""
        await self.leads.lose(db, actor, lead_id, expected_version, reason, note)
        quotes = (
            (
                await db.execute(
                    select(Quote)
                    .where(
                        Quote.shop_id == actor.shop_id,
                        Quote.lead_id == lead_id,
                        Quote.status.in_(("DRAFT", "REVIEW", "APPROVED", "SENT")),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        now = utcnow()
        for quote in quotes:
            revision = await self.revision(db, quote)
            quote.cancelled_at = now
            quote.public_token_hash = None
            await self._transition(db, actor, quote, revision, "LEAD_LOST", "CANCELLED", reason="lead_lost")
            await _tasks.resolve(
                db, shop_id=quote.shop_id, actor=actor, subject_type=QUOTE, subject_id=quote.id
            )
        lead = await self.leads.load(db, actor, lead_id)
        return await self.leads.detail(db, actor, lead)

    # ================================================================== yuborish va xaridor javobi
    async def send(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int
    ) -> tuple[QuoteOut, str]:
        """Tasdiqlangan taklif → xaridorga havola. Token faqat javobda (bazada xeshi)."""
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if QUOTE_SEND not in actor.permissions or not (
            self.can_edit(actor, quote, lead) or is_supervisor(actor)
        ):
            raise ForbiddenError("Quote is not yours", reason="other_operator")
        await ensure_shop_can_sell(db, quote.shop_id)  # to'xtatilgan shop yangi taklif yubormaydi (TC-023)
        revision = await self.revision(db, quote)
        self.use.validate_transition(QUOTE, quote.status, "SENT", "SEND", actor)
        await self._ensure_rate_fresh(db, quote.shop_id, await self.lines(db, revision))
        policy = await db.get(ShopPolicy, quote.shop_id)
        ttl = policy.quote_ttl_hours if policy else 24
        token = new_token()
        now = utcnow()
        quote.public_token_hash = token_hash(token)
        quote.sent_at, quote.sent_by, quote.expires_at = now, actor.membership_id, now + timedelta(hours=ttl)
        await self._transition(db, actor, quote, revision, "SEND", "SENT")
        await self.leads.mark_quoted(db, actor, lead)
        return await self.detail(db, actor, quote, lead), token

    async def reissue_link(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID
    ) -> tuple[QuoteOut, str]:
        """Takroriy "yuborish" (Idempotency-Key) — yangi havola, eskisi bekor (token saqlanmaydi)."""
        quote = await self.load(db, actor, quote_id, for_update=True)
        lead = await self.lead_of(db, quote)
        # Takror ham huquq tekshiruvidan o'tadi (QA 6a F7): boshqa xodimning kaliti bilan havola chiqmaydi
        ensure_lead_visible(actor, lead)
        if QUOTE_SEND not in actor.permissions or not (
            self.can_edit(actor, quote, lead) or is_supervisor(actor)
        ):
            raise ForbiddenError("Quote is not yours", reason="other_operator")
        if quote.status != "SENT":
            raise InvalidTransitionError(
                "Quote is not sent", entity=QUOTE, **{"from": quote.status}, command="SEND"
            )
        token = new_token()
        quote.public_token_hash = token_hash(token)
        quote.updated_at = utcnow()
        await db.flush()
        return await self.detail(db, actor, quote, lead), token

    async def public_url(self, db: AsyncSession, shop_id: UUID, token: str) -> str | None:
        if not self.public_url_template:
            return None
        slug = (await db.execute(select(Shop.slug).where(Shop.id == shop_id))).scalar_one_or_none()
        if slug is None:
            return None
        return self.public_url_template.replace("{slug}", slug).rstrip("/") + f"/q/{token}"

    async def reject(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int, reason: str
    ) -> QuoteOut:
        """Xodim xaridorning rad javobini belgilaydi (masalan telefonda aytdi)."""
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if QUOTE_SEND not in actor.permissions:
            raise ForbiddenError("Permission required", permission=QUOTE_SEND)
        await self.reject_core(db, actor, quote, reason, by="STAFF")
        return await self.detail(db, actor, quote, lead)

    async def reject_core(
        self, db: AsyncSession, actor: ActorContext, quote: Quote, reason: str | None, *, by: str
    ) -> None:
        if quote.status == "SENT" and quote.expires_at is not None and quote.expires_at <= utcnow():
            # QA 6a F15: muddati o'tgan (rejali ish hali ulgurmagan) taklif rad ham, qabul ham qilinmaydi
            raise QuoteExpiredError("Quote has expired", expires_at=quote.expires_at.isoformat())
        revision = await self.revision(db, quote)
        quote.rejected_at, quote.rejected_by_kind, quote.reject_reason = utcnow(), by, reason
        await self._transition(db, actor, quote, revision, "REJECT", "REJECTED", reason=reason)

    async def revise(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int
    ) -> QuoteOut:
        """Yuborilgan/rad etilgan/muddati o'tgan → yangi versiya (qoralama). Eski havola bekor (BL-043)."""
        quote, lead = await self._editable(db, actor, quote_id, expected_version, "REVISE")
        revision = await self.revision(db, quote)
        self.use.validate_transition(QUOTE, quote.status, "DRAFT", "REVISE", actor)
        await self._new_revision(db, actor, quote, revision)
        quote.public_token_hash, quote.expires_at = None, None
        quote.sent_at = quote.sent_by = None
        quote.rejected_at = quote.rejected_by_kind = quote.reject_reason = None
        await self._transition(db, actor, quote, revision, "REVISE", "DRAFT")
        return await self.detail(db, actor, quote, lead)

    async def accept_by_staff(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int
    ) -> tuple[QuoteOut, Order]:
        """Xaridor chatda/telefonda "olaman" dedi — xodim qabulni qo'lda belgilaydi (Q5)."""
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if QUOTE_SEND not in actor.permissions:
            raise ForbiddenError("Permission required", permission=QUOTE_SEND)
        order = await self.accept_core(db, actor, quote, lead)
        return await self.detail(db, actor, quote, lead), order

    async def accept_core(self, db: AsyncSession, actor: ActorContext, quote: Quote, lead: Lead) -> Order:
        """Narx va moslik qayta tekshiriladi (Q6, BL-030). O'zgarmagan bo'lsa — DRAFT buyurtma (QUOTE)."""
        self.use.validate_transition(QUOTE, quote.status, "ACCEPTED", "ACCEPT", actor)
        now = utcnow()
        if quote.expires_at is not None and quote.expires_at <= now:
            raise QuoteExpiredError("Quote has expired", expires_at=quote.expires_at.isoformat())
        await ensure_shop_can_sell(db, quote.shop_id)
        revision = await self.revision(db, quote)
        lines = await self.lines(db, revision)
        snapshots = await self.catalog.get_skus(db, quote.shop_id, [line.sku_id for line in lines])
        _ensure_rate_fresh(snapshots)
        changed: list[dict[str, Any]] = []
        for line in lines:
            snap = snapshots.get(line.sku_id)
            if not usable(snap):
                changed.append(
                    {"sku_id": line.sku_id, "title": line.title_snapshot, "reason": "not_available"}
                )
            elif snap is not None and snap.uzs_amount_minor != line.unit_price_uzs_minor:
                changed.append(
                    {
                        "sku_id": line.sku_id,
                        "title": line.title_snapshot,
                        "reason": "price",
                        "old_uzs_minor": line.unit_price_uzs_minor,
                        "new_uzs_minor": snap.uzs_amount_minor,
                    }
                )
        result = await self.check(db, quote.shop_id, lines)
        old = revision.compatibility_decision or "PASS"
        # QA 6a F13: tasdiqlovchi ko'rmagan yangi BLOCK/REVIEW qoidasi ham — o'zgarish
        approved_rules = await self._approved_rule_ids(db, revision)
        new_rules = sorted(set(_rule_ids(result)) - approved_rules)
        compat_changed = (
            result.decision == "BLOCK"
            or DECISION_RANK[result.decision] > DECISION_RANK[old]
            or bool(new_rules)
        )
        if changed or compat_changed:
            raise QuoteChangedError(
                "Quote changed since it was sent",
                lines=changed,
                compatibility={"old": old, "new": result.decision, "new_rule_ids": new_rules}
                if compat_changed
                else None,
            )
        await self._snapshot(db, revision, "ACCEPT", result)
        order = await self._order_from_quote(db, actor, quote, revision, lead, lines)
        quote.accepted_at, quote.accepted_order_id = now, order.id
        await self._transition(db, actor, quote, revision, "ACCEPT", "ACCEPTED", order_id=order.id)
        await self.leads.touch(db, lead)
        return order

    async def _ensure_rate_fresh(self, db: AsyncSession, shop_id: UUID, lines: Sequence[QuoteLine]) -> None:
        _ensure_rate_fresh(await self.catalog.get_skus(db, shop_id, [line.sku_id for line in lines]))

    async def _approved_rule_ids(self, db: AsyncSession, revision: QuoteRevision) -> set[str]:
        """Tasdiqlangan holatdagi BLOCK/REVIEW qoidalari: APPROVAL snapshot'i (avto-tasdiqda — SUBMIT)."""
        rows = (
            (
                await db.execute(
                    select(QuoteCompatibilitySnapshot).where(
                        QuoteCompatibilitySnapshot.shop_id == revision.shop_id,
                        QuoteCompatibilitySnapshot.quote_revision_id == revision.id,
                        QuoteCompatibilitySnapshot.stage.in_(("APPROVAL", "SUBMIT")),
                    )
                )
            )
            .scalars()
            .all()
        )
        chosen = next((r for r in rows if r.stage == "APPROVAL"), None) or next(iter(rows), None)
        if chosen is None:
            return set()
        return {
            str(f.get("rule_id"))
            for f in chosen.findings
            if f.get("severity") in ("BLOCK", "REVIEW_REQUIRED")
        }

    async def _order_from_quote(
        self,
        db: AsyncSession,
        actor: ActorContext,
        quote: Quote,
        revision: QuoteRevision,
        lead: Lead,
        lines: Sequence[QuoteLine],
    ) -> Order:
        phone = lead.contact_phone_enc if lead.consent_contact_at else None
        order = Order(
            shop_id=quote.shop_id,
            number=await next_order_number(db, quote.shop_id),
            status="DRAFT",
            source="QUOTE",
            conversation_id=quote.conversation_id,
            customer_ref=lead.customer_identity_id,
            quote_id=quote.id,
            quote_revision_id=revision.id,
            lead_id=lead.id,
            assigned_membership_id=lead.assigned_membership_id or quote.sent_by or quote.created_by,
            fulfillment_method="PICKUP",
            customer_name=lead.customer_name,
            customer_phone_enc=phone,
            customer_phone_hmac=search_hmac(phone) if phone else None,
            total_minor=0,
            created_by=actor.membership_id,
        )
        db.add(order)
        await db.flush()
        for line in lines:
            discounted = line.discount_pct > 0
            order_line = OrderLine(
                shop_id=quote.shop_id,
                order_id=order.id,
                position=line.position,
                sku_id=line.sku_id,
                product_id=line.product_id,
                title_snapshot=line.title_snapshot,
                sku_code_snapshot=line.sku_code_snapshot,
                qty=line.qty,
                price_version_id=line.price_version_id,
                unit_price_minor=line.unit_price_minor,
                currency=line.currency,
                exchange_rate_id=line.exchange_rate_id,
                exchange_rate_snapshot=line.exchange_rate_snapshot,
                unit_price_uzs_minor=line.unit_price_uzs_minor,
                discount_pct=line.discount_pct,
                # Chegirma taklif tasdig'ida tekshirilgan (DEC-110, Q8) — buyurtmada qayta so'ralmaydi
                discount_approved_by=revision.approved_by if discounted else None,
                discount_approved_at=revision.approved_at if discounted else None,
                warranty_months=line.warranty_months,
                line_total_minor=0,
            )
            recompute(order_line)
            db.add(order_line)
        await db.flush()
        await self.orders.touch_total(db, order)
        await self.audit.record(
            db,
            action="commerce.order.created",
            entity_type="commerce.order",
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"lines": len(lines), "source": "QUOTE", "quote_id": str(quote.id)},
        )
        await order_event(db, actor, order, "commerce.order.drafted", quote_id=quote.id, lead_id=lead.id)
        return order

    async def tracking_token(self, db: AsyncSession, order: Order) -> str:
        """Qabuldan keyin xaridor buyurtma holatini kuzatadi (4-modul sahifasi) — token faqat javobda."""
        token = new_token()
        order.tracking_token_hash = tracking_hash(token)
        await db.flush()
        return token

    # ================================================================== rejali
    async def expire_due(self, db: AsyncSession, shop_id: UUID) -> int:
        now = utcnow()
        quotes = (
            (
                await db.execute(
                    select(Quote)
                    .where(Quote.shop_id == shop_id, Quote.status == "SENT", Quote.expires_at <= now)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        actor = ActorContext.system(shop_id)
        for quote in quotes:
            revision = await self.revision(db, quote)
            await self._transition(db, actor, quote, revision, "EXPIRE", "EXPIRED")
        return len(quotes)

    async def remind_due(
        self, db: AsyncSession, shop_id: UUID, after: timedelta = timedelta(hours=12)
    ) -> int:
        """DEC-149: yuborilganiga 12 soat bo'lgan, hali amal qiladigan, suhbatga bog'langan taklif — bitta
        eslatma (`commerce.quote.reminder_due`; messaging yuboradi, xaridor voz kechgan bo'lsa — yo'q)."""
        now = utcnow()
        quotes = (
            (
                await db.execute(
                    select(Quote)
                    .where(
                        Quote.shop_id == shop_id,
                        Quote.status == "SENT",
                        Quote.conversation_id.is_not(None),
                        Quote.reminder_sent_at.is_(None),
                        Quote.sent_at <= now - after,
                        Quote.expires_at > now + timedelta(hours=1),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        actor = ActorContext.system(shop_id)
        for quote in quotes:
            quote.reminder_sent_at = now
            await db.flush()
            await write_outbox(
                db,
                schema="commerce",
                event_type="commerce.quote.reminder_due",
                actor=actor,
                shop_id=shop_id,
                aggregate_type="commerce.quote",
                aggregate_id=quote.id,
                aggregate_version=quote.version,
                payload={
                    "quote_id": quote.id,
                    "number": quote.number,
                    "conversation_id": quote.conversation_id,
                    "expires_at": quote.expires_at,
                },
            )
        return len(quotes)

    # ================================================================== ichki
    async def check(self, db: AsyncSession, shop_id: UUID, lines: Sequence[QuoteLine]) -> CompatibilityResult:
        # PC yig'ma (protsessor yoki ona plata bor) — to'liqlik qoidalari bilan; faqat qismlar yoki noutbuk —
        # to'liqlik qoidalarisiz (17 §6.1)
        full_build = any(line.role in ("CPU", "MOTHERBOARD") for line in lines)
        return await self.catalog.check_compatibility(
            db,
            shop_id,
            [BuildLine(sku_id=line.sku_id, quantity=line.qty) for line in lines],
            get_display_locale(),
            full_build=full_build,
        )

    @staticmethod
    async def _snapshot(
        db: AsyncSession, revision: QuoteRevision, stage: str, result: CompatibilityResult
    ) -> None:
        exists = (
            await db.execute(
                select(QuoteCompatibilitySnapshot.id).where(
                    QuoteCompatibilitySnapshot.shop_id == revision.shop_id,
                    QuoteCompatibilitySnapshot.quote_revision_id == revision.id,
                    QuoteCompatibilitySnapshot.stage == stage,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:  # har bosqichda bitta muzlagan natija
            return
        db.add(
            QuoteCompatibilitySnapshot(
                shop_id=revision.shop_id,
                quote_revision_id=revision.id,
                stage=stage,
                ruleset_version=result.rule_set_version,
                decision=result.decision,
                can_publish=result.can_publish_quote,
                findings=snapshot_findings(result),
                spec_versions=spec_versions(result),
                estimated_power_w=result.estimated_power_w,
            )
        )
        await db.flush()

    async def _new_revision(
        self, db: AsyncSession, actor: ActorContext, quote: Quote, old: QuoteRevision
    ) -> QuoteRevision:
        """Yangi versiya — eskisining qatorlari nusxasi (qoralama). Eski versiya tarixda."""
        new = QuoteRevision(
            shop_id=quote.shop_id,
            quote_id=quote.id,
            revision=old.revision + 1,
            requirements=old.requirements,
            exchange_rate_id=old.exchange_rate_id,
            exchange_rate_snapshot=old.exchange_rate_snapshot,
            subtotal_uzs_minor=old.subtotal_uzs_minor,
            discount_uzs_minor=old.discount_uzs_minor,
            total_uzs_minor=old.total_uzs_minor,
            created_by_kind="AI" if actor.actor_type == "AI_AGENT" else "STAFF",
            created_by=actor.membership_id,
            edited_by=old.edited_by,  # qatorlar nusxa — muallif o'sha; keyingi tahrir yangilaydi
        )
        db.add(new)
        await db.flush()
        for line in await self.lines(db, old):
            db.add(
                QuoteLine(
                    shop_id=quote.shop_id,
                    quote_revision_id=new.id,
                    position=line.position,
                    role=line.role,
                    sku_id=line.sku_id,
                    product_id=line.product_id,
                    title_snapshot=line.title_snapshot,
                    sku_code_snapshot=line.sku_code_snapshot,
                    qty=line.qty,
                    price_version_id=line.price_version_id,
                    unit_price_minor=line.unit_price_minor,
                    currency=line.currency,
                    exchange_rate_id=line.exchange_rate_id,
                    exchange_rate_snapshot=line.exchange_rate_snapshot,
                    unit_price_uzs_minor=line.unit_price_uzs_minor,
                    discount_pct=line.discount_pct,
                    line_total_uzs_minor=line.line_total_uzs_minor,
                    warranty_months=line.warranty_months,
                )
            )
        await db.flush()
        quote.current_revision_id, quote.current_revision_no = new.id, new.revision
        await db.flush()
        return new

    async def _transition(
        self,
        db: AsyncSession,
        actor: ActorContext,
        quote: Quote,
        revision: QuoteRevision,
        command: str,
        target: str,
        *,
        reason: str | None = None,
        **extra: Any,
    ) -> None:
        rule = self.use.validate_transition(QUOTE, quote.status, target, command, actor)
        from_status = quote.status
        quote.status = rule.to_status
        quote.updated_at = utcnow()
        await db.flush()
        await self.use.log_transition(db, entity_id=quote.id, rule=rule, actor=actor, reason=reason)
        await self.audit.record(
            db,
            action=f"commerce.quote.{command.lower()}",
            entity_type=QUOTE,
            entity_id=quote.id,
            actor=actor,
            entity_version=quote.version,
            reason=reason,
            diff={"status": {"old": from_status, "new": quote.status}, "revision": quote.current_revision_no},
        )
        event = {
            "SUBMIT": "commerce.quote.submitted",
            "AUTO_APPROVE": "commerce.quote.approved",
            "APPROVE": "commerce.quote.approved",
            "RETURN": "commerce.quote.returned",
            "SEND": "commerce.quote.sent",
            "ACCEPT": "commerce.quote.accepted",
            "REJECT": "commerce.quote.rejected",
            "EXPIRE": "commerce.quote.expired",
            "REVISE": "commerce.quote.revised",
            "CANCEL": "commerce.quote.cancelled",
            "LEAD_LOST": "commerce.quote.cancelled",
        }[command]
        await self.event(db, actor, quote, revision, event, from_status=from_status, **extra)

    async def event(
        self,
        db: AsyncSession,
        actor: ActorContext,
        quote: Quote,
        revision: QuoteRevision,
        event_type: str,
        **extra: Any,
    ) -> None:
        await db.flush()
        await write_outbox(
            db,
            schema="commerce",
            event_type=event_type,
            actor=actor,
            shop_id=quote.shop_id,
            aggregate_type=QUOTE,
            aggregate_id=quote.id,
            aggregate_version=quote.version,
            payload={  # ID, holat va summa — PII, havola tokeni va erkin matn yo'q (05 §3.1)
                "quote_id": quote.id,
                "number": quote.number,
                "lead_id": quote.lead_id,
                "status": quote.status,
                "revision": quote.current_revision_no,
                "total_uzs_minor": revision.total_uzs_minor,
                "compatibility_decision": revision.compatibility_decision,
                "conversation_id": quote.conversation_id,
                "created_by": quote.created_by,
                "expires_at": quote.expires_at,
                **extra,
            },
        )

    async def _locked(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int
    ) -> tuple[Quote, Lead]:
        quote = await self.load(db, actor, quote_id, for_update=True)
        lead = await self.lead_of(db, quote)
        ensure_lead_visible(actor, lead)
        check_version(quote.version, expected_version)
        return quote, lead

    async def _editable(
        self, db: AsyncSession, actor: ActorContext, quote_id: UUID, expected_version: int, command: str
    ) -> tuple[Quote, Lead]:
        quote, lead = await self._locked(db, actor, quote_id, expected_version)
        if not self.can_edit(actor, quote, lead):
            raise ForbiddenError("Quote is not yours", reason="other_operator")
        if command in ("EDIT", "SUBMIT") and quote.status != "DRAFT":
            raise InvalidTransitionError(
                "Quote is not a draft", entity=QUOTE, **{"from": quote.status}, command=command
            )
        return quote, lead


def _line_out(line: QuoteLine) -> QuoteLineOut:
    return QuoteLineOut(
        id=line.id,
        position=line.position,
        role=line.role,
        sku_id=line.sku_id,
        product_id=line.product_id,
        title=line.title_snapshot,
        sku_code=line.sku_code_snapshot,
        qty=line.qty,
        unit_price_minor=line.unit_price_minor,
        currency=line.currency,
        exchange_rate=line.exchange_rate_snapshot,
        unit_price_uzs_minor=line.unit_price_uzs_minor,
        discount_pct=line.discount_pct,
        line_total_uzs_minor=line.line_total_uzs_minor,
        warranty_months=line.warranty_months,
        spec_id=line.spec_id,
        spec_version=line.spec_version,
    )


def _ensure_rate_fresh(snapshots: dict[UUID, SkuSnapshot]) -> None:
    """Dollar narxli qator va kurs eskirgan (3 kundan eski) yoki yo'q — yangi taklif berilmaydi (BL-018).
    Buyurtma tasdig'i bilan bir xil xato: `EXCHANGE_RATE_STALE` (UAT-M05)."""
    bad = [
        s
        for s in snapshots.values()
        if s.currency == "USD" and (s.exchange_rate_stale or s.exchange_rate is None)
    ]
    if bad:
        raise ExchangeRateStaleError(
            "Exchange rate is stale",
            rate_effective_at=bad[0].exchange_rate_effective_at,
            max_age_hours=STALE_RATE_HOURS,
        )


def _ensure_usable(items: Sequence[Any], snapshots: dict[UUID, SkuSnapshot]) -> None:
    problems = []
    for index, item in enumerate(items):
        snap = snapshots.get(item.sku_id)
        if snap is None:  # boshqa shop SKU'si — xuddi yo'qdek
            raise ValidationError("Unknown SKU", fields=[field(f"lines[{index}].sku_id", "invalid")])
        if not usable(snap):
            problems.append(
                {"sku_id": item.sku_id, "product_status": snap.product_status, "sku_status": snap.sku_status}
            )
    if problems:
        raise ProductNotAvailableError("Product is not available", lines=problems)


def _rule_ids(result: CompatibilityResult) -> list[str]:
    return [f.rule_id for f in result.findings if f.severity in ("BLOCK", "REVIEW_REQUIRED")]


def _rule_block(result: CompatibilityResult) -> BusinessRuleError:
    """RULE_BLOCK tafsiloti — 11 §6 shakli (QA 6a F8): qoidalar to'plami versiyasi va topilmalar."""
    return BusinessRuleError(
        "Build is not compatible",
        ruleset_version=result.rule_set_version,
        decision=result.decision,
        findings=[
            {"rule_id": f.rule_id, "severity": f.severity}
            for f in result.findings
            if f.severity in ("BLOCK", "REVIEW_REQUIRED")
        ],
    )
