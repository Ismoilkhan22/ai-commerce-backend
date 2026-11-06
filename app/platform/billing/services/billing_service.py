"""M26: tariflar, obuna davri va hisob-fakturalar (Stage 2) — DEC-100, DEC-119, BL-083.

```
Yangi shop ──▶ TRIAL (PILOT tarifi, 30 kun) — obuna birinchi o'qishda o'zi ochiladi
Davr tugashiga 5 kun qolganda ──▶ keyingi davr hisobi (ISSUED, muddati — davr oxiri), egaga xabar
Davr tugadi:  hisob to'langan ──▶ yangi davr ACTIVE (kutilayotgan tarif shu yerda kuchga kiradi)
              to'lanmagan, muddatidan 7 kun o'tdi ──▶ PAST_DUE, egaga va platformaga xabar
```

Avtomatik yechib olish yo'q (BL-083). PAST_DUE shopni to'xtatmaydi — to'xtatish platforma qarori (FSM-01).
Tarif o'zgarishi faqat keyingi davrdan; narxi belgilanmagan tarifga hisob chiqmaydi.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.billing.models.orm import Invoice, Plan, Subscription
from app.platform.llm.models.orm import AiUsage
from app.platform.shops.models.orm import Branch, Shop
from app.platform.staff.models.orm import Membership
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.db.session import set_shop_context
from app.shared.errors.base import InvalidTransitionError, NotFoundError, ValidationError
from app.shared.types.actor import ActorContext

PERIOD = timedelta(days=30)
TRIAL = timedelta(days=30)  # DEC-119: 30 kun bepul
INVOICE_AHEAD = timedelta(days=5)
GRACE = timedelta(days=7)
DEFAULT_PLAN = "PILOT"
INVOICE = "platform.invoice"
SUBSCRIPTION = "platform.subscription"

# Founder narxni kiritguncha `None` — hisob chiqmaydi (business/14 §2.1 gipoteza)
SEED_PLANS: tuple[dict[str, Any], ...] = (
    {
        "code": "PILOT",
        "name": "Pilot",
        "price": 0,
        "position": 0,
        "limits": {"branches": 2, "staff": 5, "skus": 5000, "ai_replies": 5000},
    },
    {
        "code": "START",
        "name": "Start",
        "price": None,
        "position": 1,
        "limits": {"branches": 1, "staff": 3, "skus": 1000, "ai_replies": 2500},
    },
    {
        "code": "PC_PRO",
        "name": "PC Pro",
        "price": None,
        "position": 2,
        "limits": {"branches": 2, "staff": 10, "skus": 5000, "ai_replies": 10000},
    },
    {
        "code": "BUSINESS",
        "name": "Business",
        "price": None,
        "position": 3,
        "limits": {"branches": 10, "staff": 40, "skus": 20000, "ai_replies": 30000},
    },
)


class PlanOut(BaseModel):
    code: str
    name: str
    monthly_price_uzs_minor: int | None
    limits: dict[str, int]
    is_active: bool


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    monthly_price_uzs_minor: int | None = Field(default=None, ge=0, le=10**13)
    limits: dict[Literal["branches", "staff", "skus", "ai_replies"], int]
    is_active: bool = True


class InvoiceOut(BaseModel):
    id: UUID
    shop_id: UUID
    number: str
    plan_code: str
    period_start: datetime
    period_end: datetime
    amount_uzs_minor: int
    status: str
    due_at: datetime
    paid_at: datetime | None


class Usage(BaseModel):
    branches: int
    staff: int
    skus: int
    ai_replies: int  # AI sotuvchi javoblari (navbatlar) — joriy davrda


class BillingOut(BaseModel):
    plan: PlanOut
    status: str
    period_start: datetime
    period_end: datetime
    pending_plan_code: str | None
    usage: Usage
    over_limit: list[str]
    invoices: list[InvoiceOut]
    plans: list[PlanOut]
    version: int


class PlanChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(max_length=40)


class InvoiceList(BaseModel):
    items: list[InvoiceOut]


class MarkPaidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=3, max_length=300, description="To'lov qanday keldi (bank, sana)")


class SubscriptionSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str | None = Field(default=None, max_length=40)
    extend_days: int | None = Field(default=None, ge=1, le=365)  # sinov yoki davrni uzaytirish


def _plan_out(plan: Plan) -> PlanOut:
    return PlanOut(
        code=plan.code,
        name=plan.name,
        monthly_price_uzs_minor=plan.monthly_price_uzs_minor,
        limits={k: int(v) for k, v in (plan.limits or {}).items()},
        is_active=plan.is_active,
    )


def _invoice_out(row: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=row.id,
        shop_id=row.shop_id,
        number=row.number,
        plan_code=row.plan_code,
        period_start=row.period_start,
        period_end=row.period_end,
        amount_uzs_minor=row.amount_uzs_minor,
        status=row.status,
        due_at=row.due_at,
        paid_at=row.paid_at,
    )


class BillingService:
    def __init__(self, audit: AuditService, catalog: CatalogQueryPort) -> None:
        self.audit = audit
        self.catalog = catalog

    # ------------------------------------------------------------------ tariflar
    async def ensure_plans(self, db: AsyncSession) -> None:
        existing = set((await db.execute(select(Plan.code))).scalars())
        for seed in SEED_PLANS:
            if seed["code"] not in existing:
                db.add(
                    Plan(
                        code=seed["code"],
                        name=seed["name"],
                        monthly_price_uzs_minor=seed["price"],
                        limits=seed["limits"],
                        position=seed["position"],
                    )
                )
        await db.flush()

    async def plans(self, db: AsyncSession, *, active_only: bool = False) -> list[PlanOut]:
        await self.ensure_plans(db)
        query = select(Plan).order_by(Plan.position, Plan.code)
        if active_only:
            query = query.where(Plan.is_active.is_(True))
        return [_plan_out(p) for p in (await db.execute(query)).scalars()]

    async def update_plan(self, db: AsyncSession, actor: ActorContext, code: str, data: PlanIn) -> PlanOut:
        await self.ensure_plans(db)
        plan = await db.get(Plan, code, with_for_update=True)
        if plan is None:
            raise NotFoundError("Plan not found")
        plan.name, plan.monthly_price_uzs_minor = data.name.strip(), data.monthly_price_uzs_minor
        plan.limits, plan.is_active = {str(k): v for k, v in data.limits.items()}, data.is_active
        await db.flush()
        await self.audit.record(
            db,
            action="billing.plan.updated",
            entity_type="platform.plan",
            entity_id=None,
            actor=actor,
            diff={"code": code, "price": data.monthly_price_uzs_minor},
        )
        return _plan_out(plan)

    # ------------------------------------------------------------------ obuna
    async def subscription(self, db: AsyncSession, shop_id: UUID, *, lock: bool = False) -> Subscription:
        sub = await db.get(Subscription, shop_id, with_for_update=lock)
        if sub is not None:
            return sub
        await self.ensure_plans(db)
        shop = await db.get(Shop, shop_id)
        if shop is None:
            raise NotFoundError("Shop not found")
        start = utcnow()  # sinov obuna ochilgan paytdan (eski shoplar ham to'liq 30 kun oladi — QA #8)
        sub = Subscription(
            shop_id=shop_id,
            plan_code=DEFAULT_PLAN,
            status="TRIAL",
            period_start=start,
            period_end=start + TRIAL,
            version=1,
        )
        db.add(sub)
        await db.flush()
        return sub

    async def usage(self, db: AsyncSession, shop_id: UUID, since: datetime) -> Usage:
        branches = await db.scalar(
            select(func.count()).where(Branch.shop_id == shop_id, Branch.status == "ACTIVE")
        )
        staff = await db.scalar(
            select(func.count()).where(
                Membership.shop_id == shop_id, Membership.status.in_(("ACTIVE", "INVITED"))
            )
        )
        replies = await db.scalar(
            select(func.count(func.distinct(AiUsage.ref_id))).where(
                AiUsage.shop_id == shop_id, AiUsage.purpose == "SALES_TURN", AiUsage.occurred_at >= since
            )
        )
        skus = await self.catalog.count_active_skus(db, shop_id)
        return Usage(
            branches=int(branches or 0), staff=int(staff or 0), skus=skus, ai_replies=int(replies or 0)
        )

    async def overview(self, db: AsyncSession, shop_id: UUID) -> BillingOut:
        await set_shop_context(
            db, shop_id
        )  # platforma panelidan ham foydalanish to'g'ri sanalsin (RLS, QA #5)
        sub = await self.subscription(db, shop_id)
        plan = await db.get(Plan, sub.plan_code)
        assert plan is not None
        usage = await self.usage(db, shop_id, sub.period_start)
        over = [k for k, limit in (plan.limits or {}).items() if getattr(usage, k, 0) > int(limit)]
        invoices = await db.execute(
            select(Invoice).where(Invoice.shop_id == shop_id).order_by(Invoice.period_start.desc()).limit(12)
        )
        return BillingOut(
            plan=_plan_out(plan),
            status=sub.status,
            period_start=sub.period_start,
            period_end=sub.period_end,
            pending_plan_code=sub.pending_plan_code,
            usage=usage,
            over_limit=over,
            invoices=[_invoice_out(i) for i in invoices.scalars()],
            plans=await self.plans(db, active_only=True),
            version=sub.version,
        )

    async def request_plan(self, db: AsyncSession, actor: ActorContext, data: PlanChangeIn) -> BillingOut:
        """Ega tarifni tanlaydi — keyingi davrdan kuchga kiradi (BL-083: sana va summa oldindan aniq)."""
        assert actor.shop_id is not None
        plan = await db.get(Plan, data.plan_code)
        if plan is None or not plan.is_active or plan.code == DEFAULT_PLAN:
            raise ValidationError(
                "Plan not available", fields=[{"field": "plan_code", "code": "invalid", "params": {}}]
            )
        sub = await self.subscription(db, actor.shop_id, lock=True)
        sub.pending_plan_code = None if plan.code == sub.plan_code else plan.code
        issued = (
            await db.execute(
                select(Invoice).where(
                    Invoice.shop_id == actor.shop_id,
                    Invoice.period_start == sub.period_end,
                    Invoice.status == "ISSUED",
                )
            )
        ).scalar_one_or_none()
        target = sub.pending_plan_code or sub.plan_code
        if issued is not None and issued.plan_code != target:
            # Keyingi davr hisobi eski tarifga chiqqan — bekor, yangi tarifga qayta chiqadi (QA #6)
            issued.status, issued.payment_note = "VOID", "Tarif o'zgardi — yangi hisob chiqadi"
        await db.flush()
        await self.audit.record(
            db,
            action="billing.plan.requested",
            entity_type=SUBSCRIPTION,
            entity_id=actor.shop_id,
            actor=actor,
            diff={"plan_code": plan.code},
        )
        return await self.overview(db, actor.shop_id)

    # ------------------------------------------------------------------ platforma
    async def set_subscription(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, data: SubscriptionSetIn
    ) -> BillingOut:
        sub = await self.subscription(db, shop_id, lock=True)
        if data.plan_code is not None:
            plan = await db.get(Plan, data.plan_code)
            if plan is None:
                raise ValidationError(
                    "Plan not found", fields=[{"field": "plan_code", "code": "invalid", "params": {}}]
                )
            sub.plan_code, sub.pending_plan_code = plan.code, None
        if data.extend_days:
            sub.period_end = sub.period_end + timedelta(days=data.extend_days)
            if sub.status == "PAST_DUE":
                sub.status = "ACTIVE" if sub.plan_code != DEFAULT_PLAN else "TRIAL"
        await db.flush()
        await self.audit.record(
            db,
            action="billing.subscription.set",
            entity_type=SUBSCRIPTION,
            entity_id=shop_id,
            actor=_on(actor, shop_id),
            diff={"plan_code": data.plan_code, "extend_days": data.extend_days},
        )
        return await self.overview(db, shop_id)

    async def invoices(self, db: AsyncSession, status: str | None) -> InvoiceList:
        query = select(Invoice).order_by(Invoice.due_at.desc()).limit(200)
        if status:
            query = query.where(Invoice.status == status)
        return InvoiceList(items=[_invoice_out(i) for i in (await db.execute(query)).scalars()])

    async def mark_paid(
        self, db: AsyncSession, actor: ActorContext, invoice_id: UUID, data: MarkPaidIn
    ) -> InvoiceOut:
        invoice = await db.get(Invoice, invoice_id, with_for_update=True)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        if invoice.status != "ISSUED":
            raise InvalidTransitionError(
                "Invoice is closed", entity=INVOICE, **{"from": invoice.status}, command="PAY"
            )
        invoice.status, invoice.paid_at = "PAID", utcnow()
        invoice.payment_note, invoice.recorded_by = data.note.strip(), actor.actor_id
        sub = await self.subscription(db, invoice.shop_id, lock=True)
        if sub.status == "PAST_DUE" and invoice.period_start == sub.period_end:
            await self._roll(sub, invoice)  # kechikkan to'lov — o'sha (allaqachon boshlangan) davr ochiladi
        await db.flush()
        await self.audit.record(
            db,
            action="billing.invoice.paid",
            entity_type=INVOICE,
            entity_id=invoice.id,
            actor=_on(actor, invoice.shop_id),
            reason=invoice.payment_note,
        )
        return _invoice_out(invoice)

    async def void(
        self, db: AsyncSession, actor: ActorContext, invoice_id: UUID, data: MarkPaidIn
    ) -> InvoiceOut:
        invoice = await db.get(Invoice, invoice_id, with_for_update=True)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        if invoice.status != "ISSUED":
            raise InvalidTransitionError(
                "Invoice is closed", entity=INVOICE, **{"from": invoice.status}, command="VOID"
            )
        invoice.status, invoice.payment_note, invoice.recorded_by = "VOID", data.note.strip(), actor.actor_id
        await db.flush()
        await self.audit.record(
            db,
            action="billing.invoice.voided",
            entity_type=INVOICE,
            entity_id=invoice.id,
            actor=_on(actor, invoice.shop_id),
            reason=invoice.payment_note,
        )
        return _invoice_out(invoice)

    # ------------------------------------------------------------------ rejali ish
    async def cycle(self, db: AsyncSession, shop_id: UUID, now: datetime | None = None) -> str | None:
        """Bitta shop uchun: hisob chiqarish, davrni almashtirish yoki PAST_DUE. Natija — nima bo'lgani."""
        now = now or utcnow()
        shop = await db.get(Shop, shop_id)
        if shop is None or shop.status == "CLOSED":
            return None
        sub = await self.subscription(db, shop_id, lock=True)
        if sub.status == "CANCELLED":
            return None
        next_plan = await db.get(Plan, sub.pending_plan_code or sub.plan_code)
        next_invoice = (
            await db.execute(
                select(Invoice).where(
                    Invoice.shop_id == shop_id,
                    Invoice.period_start == sub.period_end,
                    Invoice.status != "VOID",  # bekor qilingan hisob o'rniga yangisi chiqadi (QA #4)
                )
            )
        ).scalar_one_or_none()
        priced = next_plan is not None and next_plan.monthly_price_uzs_minor not in (None, 0)
        if next_invoice is None and priced and now >= sub.period_end - INVOICE_AHEAD:
            assert next_plan is not None and next_plan.monthly_price_uzs_minor is not None
            seq = await db.scalar(text("SELECT nextval('platform.invoice_number_seq')"))
            db.add(
                Invoice(
                    shop_id=shop_id,
                    number=f"INV-{now:%Y}-{int(seq or 0):06d}",
                    plan_code=next_plan.code,
                    period_start=sub.period_end,
                    period_end=sub.period_end + PERIOD,
                    amount_uzs_minor=next_plan.monthly_price_uzs_minor,
                    due_at=sub.period_end,
                )
            )
            await db.flush()
            return "INVOICED"
        if now < sub.period_end:
            return None
        if next_invoice is not None and next_invoice.status == "PAID":
            await self._roll(sub, next_invoice)
            await db.flush()
            return "ROLLED"
        if not priced:  # narxsiz tarif (pilot yoki narx kiritilmagan) — davr o'zi uzayadi, to'lov so'ralmaydi
            sub.period_start, sub.period_end = sub.period_end, sub.period_end + PERIOD
            if sub.pending_plan_code:
                sub.plan_code, sub.pending_plan_code = sub.pending_plan_code, None
            if sub.plan_code == DEFAULT_PLAN and sub.status == "TRIAL":
                sub.status = "PAST_DUE"  # sinov tugadi, tarif tanlanmagan — xabar, savdo to'xtamaydi
                await db.flush()
                return "TRIAL_ENDED"
            await db.flush()
            return "EXTENDED"
        if sub.status != "PAST_DUE" and now >= sub.period_end + GRACE:
            sub.status = "PAST_DUE"
            await db.flush()
            return "PAST_DUE"
        return None

    @staticmethod
    async def _roll(sub: Subscription, invoice: Invoice) -> None:
        sub.period_start, sub.period_end = invoice.period_start, invoice.period_end
        sub.plan_code, sub.pending_plan_code, sub.status = invoice.plan_code, None, "ACTIVE"


def _on(actor: ActorContext, shop_id: UUID) -> ActorContext:
    return ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        shop_id=shop_id,
        surface=actor.surface,
        roles=actor.roles,
        membership_id=actor.membership_id,
    )
