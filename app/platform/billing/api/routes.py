"""M26 tariflar: shop (`/shop/billing`) va platforma (`/platform/billing/*`) endpoint'lari."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.platform.billing.services.billing_service import (
    BillingOut,
    BillingService,
    InvoiceList,
    InvoiceOut,
    MarkPaidIn,
    PlanChangeIn,
    PlanIn,
    PlanOut,
    SubscriptionSetIn,
)
from app.platform.staff.infrastructure.guard import (
    RequestContext,
    require_permission,
    require_platform_permission,
)

shop_router = APIRouter(prefix="/billing", tags=["billing"])
platform_router = APIRouter(prefix="/billing", tags=["billing-platform"])


def billing_service(request: Request) -> BillingService:
    return request.app.state.billing  # type: ignore[no-any-return]


Billing = Annotated[BillingService, Depends(billing_service)]
CanView = Annotated[RequestContext, Depends(require_permission("billing.view"))]
CanManage = Annotated[RequestContext, Depends(require_permission("billing.manage"))]
CanAdmin = Annotated[RequestContext, Depends(require_platform_permission("platform.billing.manage"))]


@shop_router.get("", response_model=BillingOut)
async def get_billing(ctx: CanView, svc: Billing) -> BillingOut:
    """Tarif, holat, davr, limitlar va hozirgi foydalanish, oxirgi 12 hisob."""
    assert ctx.actor.shop_id is not None
    return await svc.overview(ctx.db, ctx.actor.shop_id)


@shop_router.post("/plan", response_model=BillingOut)
async def request_plan(body: PlanChangeIn, ctx: CanManage, svc: Billing) -> BillingOut:
    """Tarif keyingi davrdan kuchga kiradi; hisob davr tugashidan 5 kun oldin chiqadi (BL-083)."""
    return await svc.request_plan(ctx.db, ctx.actor, body)


@platform_router.get("/plans", response_model=list[PlanOut])
async def list_plans(ctx: CanAdmin, svc: Billing) -> list[PlanOut]:
    return await svc.plans(ctx.db)


@platform_router.put("/plans/{code}", response_model=PlanOut)
async def update_plan(code: str, body: PlanIn, ctx: CanAdmin, svc: Billing) -> PlanOut:
    return await svc.update_plan(ctx.db, ctx.actor, code, body)


@platform_router.get("/invoices", response_model=InvoiceList)
async def list_invoices(
    ctx: CanAdmin, svc: Billing, status: Annotated[str | None, Query(pattern="^(ISSUED|PAID|VOID)$")] = None
) -> InvoiceList:
    return await svc.invoices(ctx.db, status)


@platform_router.post("/invoices/{invoice_id}/paid", response_model=InvoiceOut)
async def mark_invoice_paid(invoice_id: UUID, body: MarkPaidIn, ctx: CanAdmin, svc: Billing) -> InvoiceOut:
    """To'lov tizimdan tashqarida keldi (DEC-100) — admin belgilaydi, izoh majburiy."""
    return await svc.mark_paid(ctx.db, ctx.actor, invoice_id, body)


@platform_router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
async def void_invoice(invoice_id: UUID, body: MarkPaidIn, ctx: CanAdmin, svc: Billing) -> InvoiceOut:
    return await svc.void(ctx.db, ctx.actor, invoice_id, body)


@platform_router.get("/shops/{shop_id}", response_model=BillingOut)
async def shop_billing(shop_id: UUID, ctx: CanAdmin, svc: Billing) -> BillingOut:
    return await svc.overview(ctx.db, shop_id)


@platform_router.put("/shops/{shop_id}", response_model=BillingOut)
async def set_shop_subscription(
    shop_id: UUID, body: SubscriptionSetIn, ctx: CanAdmin, svc: Billing
) -> BillingOut:
    """Tarifni darhol almashtirish yoki sinov/davrni uzaytirish (kelishuv bo'yicha)."""
    return await svc.set_subscription(ctx.db, ctx.actor, shop_id, body)
