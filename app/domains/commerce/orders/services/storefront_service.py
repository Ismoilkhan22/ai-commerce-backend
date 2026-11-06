"""Saytdan buyurtma so'rovi va holat sahifasi (DEC-115, M07, storefront.md §6).

Bitta tranzaksiyada: tekshiruvlar → qoralama (STOREFRONT, biriktirilmagan) → darhol "Tasdiq kutilmoqda".
Mahsulot band qilinmaydi (DEC-100b): bandni operator tasdiqlashda qiladi (narx va qoldiq yana tekshiriladi).

- Takror himoyasi: `Idempotency-Key` = `orders.source_request_id` (BL-046). Ikki marta bosish yoki uzilib
  qayta yuborish — bitta buyurtma; takroriy javobga yangi holat havolasi (eskisi bekor bo'ladi).
- Holat havolasi tokenining o'zi hech qayerda saqlanmaydi: bazada faqat SHA-256 xeshi.
- Tanlangan filialda yo'q mahsulot ham qabul qilinadi — javobda belgilanadi (DEC-135, M07).
- Xaridor telefoni va manzili shifrlangan; audit va logga tushmaydi (26 §4).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import field, load_branch
from app.domains.commerce.orders.models.orm import Order, OrderLine
from app.domains.commerce.orders.schemas import OrderLineIn
from app.domains.commerce.orders.services.order_service import OrderService, next_order_number
from app.domains.commerce.orders.services.pricing import usable
from app.domains.commerce.orders.storefront_schemas import (
    OrderRequestIn,
    OrderRequestLineOut,
    OrderRequestOut,
    PublicOrderStatus,
    TrackingBranch,
    TrackingLine,
    TrackingOut,
)
from app.domains.commerce.state_machine import ORDER
from app.platform.audit.services.audit_service import AuditService
from app.platform.shops.models.orm import Branch, ShopPolicy
from app.platform.shops.services.sales_gate import ensure_shop_can_sell
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.consent import STOREFRONT_CONSENT_VERSION
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import StockQueryPort
from app.shared.contracts.storefront import SiteAccess
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import DomainError, NotFoundError, ProductNotAvailableError, ValidationError
from app.shared.types.actor import ActorContext

TRACKING_TOKEN = re.compile(r"[A-Za-z0-9_-]{24,64}")  # fullmatch bilan


def tracking_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def customer_actor(shop_id: UUID) -> ActorContext:
    """Saytdagi xaridor — anonim (tizimga kirmaydi); jurnal va auditda `CUSTOMER`."""
    return ActorContext(actor_type="CUSTOMER", actor_id=None, shop_id=shop_id, surface="storefront")


def public_status(order: Order) -> PublicOrderStatus:
    """Xaridorga ko'rinadigan holat: ichki "muammoli" holat — "tayyorlanmoqda" (ichki ish)."""
    if order.status in ("DRAFT", "PENDING_CONFIRMATION"):
        return "RECEIVED"
    if order.status == "CONFIRMED":
        return "CONFIRMED"
    if order.status in ("PROCESSING", "EXCEPTION"):
        return "READY" if order.ready_at is not None and order.status == "PROCESSING" else "PREPARING"
    return "COMPLETED" if order.status == "COMPLETED" else "CANCELLED"


@contextmanager
def public_error_details() -> Iterator[None]:
    """Sayt xaridoriga xato tafsilotida ichki ID yo'q (11 §6.3, QA M04 F5): `branch_id` kabi kalitlar olib
    tashlanadi, qatorlarda faqat xaridor o'zi yuborgan `sku_id` qoladi. Maydon xatolari (yo'l + kod)
    o'zgarmaydi."""
    try:
        yield
    except DomainError as exc:
        details = {k: v for k, v in exc.details.items() if not (k.endswith("_id") or k.endswith("_ids"))}
        lines = details.get("lines")
        if isinstance(lines, list):
            details["lines"] = [
                {"sku_id": item["sku_id"]} for item in lines if isinstance(item, dict) and "sku_id" in item
            ]
        exc.details = details
        raise


@dataclass(frozen=True)
class CreatedRequest:
    """Yangi so'rov natijasi: javob va buyurtma ID'si (takror himoyasi jadvaliga faqat ID yoziladi)."""

    order_id: UUID
    out: OrderRequestOut


class StorefrontOrderService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        orders: OrderService,
        catalog: CatalogQueryPort,
        stock: StockQueryPort,
    ) -> None:
        self.use = use
        self.audit = audit
        self.orders = orders
        self.catalog = catalog
        self.stock = stock

    # ================================================================== buyurtma so'rovi
    async def request(
        self, db: AsyncSession, access: SiteAccess, data: OrderRequestIn, phone: str, key: str
    ) -> CreatedRequest:
        shop_id = access.shop_id
        existing = await self._by_request(db, shop_id, key)
        if existing is not None:  # idempotency yozuvi eskirgan, lekin buyurtma bor — yangisi yaratilmaydi
            return CreatedRequest(existing.id, await self.reissue(db, shop_id, existing.id))
        await ensure_shop_can_sell(db, shop_id)
        actor = customer_actor(shop_id)
        with public_error_details():
            await self._validate(db, actor, data)
        token = secrets.token_urlsafe(32)
        now = utcnow()
        order = Order(
            shop_id=shop_id,
            number=await next_order_number(db, shop_id),
            status="DRAFT",
            source="STOREFRONT",
            source_request_id=key,
            branch_id=data.branch_id,
            assigned_membership_id=None,  # navbatga tushadi: operator o'ziga oladi yoki menejer biriktiradi
            fulfillment_method=data.fulfillment_method,
            customer_name=data.customer_name,
            customer_phone_enc=phone,
            customer_phone_hmac=search_hmac(phone),
            delivery_address_enc=data.delivery_address if data.fulfillment_method == "DELIVERY" else None,
            customer_locale=data.customer_locale,
            customer_comment=data.customer_comment,
            consent_version=data.consent_version,
            tracking_token_hash=tracking_hash(token),
            total_minor=0,
        )
        db.add(order)
        await db.flush()
        with public_error_details():
            await self.orders.add_lines(
                db, actor, order, [OrderLineIn(sku_id=line.sku_id, qty=line.qty) for line in data.lines]
            )
        await self.audit.record(
            db,
            action="commerce.order.created",
            entity_type=ORDER,
            entity_id=order.id,
            actor=actor,
            entity_version=order.version,
            diff={"lines": len(data.lines), "source": "STOREFRONT"},
        )
        # Darhol "Tasdiq kutilmoqda" — operatorga navbat (FSM-08: xaridor saytda yubordi)
        rule = self.use.validate_transition(ORDER, "DRAFT", "PENDING_CONFIRMATION", "SUBMIT", actor)
        order.status = rule.to_status
        order.submitted_at = now  # 24 soatlik eslatma shundan (DEC-104)
        await db.flush()
        await self.use.log_transition(db, entity_id=order.id, rule=rule, actor=actor)
        return CreatedRequest(order.id, await self._out(db, order, token))

    async def reissue(self, db: AsyncSession, shop_id: UUID, order_id: UUID) -> OrderRequestOut:
        """Takroriy so'rov: o'sha buyurtma, yangi holat havolasi (token saqlanmaydi — qaytarib bo'lmaydi)."""
        order = (
            await db.execute(select(Order).where(Order.shop_id == shop_id, Order.id == order_id))
        ).scalar_one()
        token = secrets.token_urlsafe(32)
        order.tracking_token_hash = tracking_hash(token)
        await db.flush()
        return await self._out(db, order, token)

    # ================================================================== holat sahifasi
    async def track(self, db: AsyncSession, access: SiteAccess, token: str) -> TrackingOut:
        if not TRACKING_TOKEN.fullmatch(token):
            raise NotFoundError("Order not found")
        wanted = tracking_hash(token)
        order = (
            await db.execute(
                select(Order).where(Order.shop_id == access.shop_id, Order.tracking_token_hash == wanted)
            )
        ).scalar_one_or_none()
        if order is None or not hmac.compare_digest(order.tracking_token_hash or "", wanted):
            raise NotFoundError("Order not found")
        branch = None
        if order.branch_id is not None and order.fulfillment_method == "PICKUP":
            row = await db.get(Branch, order.branch_id)
            if row is not None:
                branch = TrackingBranch(name=row.name, address=row.address, phone=row.phone)
        lines = await self._lines(db, order)
        return TrackingOut(
            number=order.number,
            status=public_status(order),
            fulfillment_method=order.fulfillment_method,
            branch=branch,
            lines=[
                TrackingLine(
                    title=line.title_snapshot,
                    qty=line.qty,
                    unit_price_uzs_minor=line.unit_price_uzs_minor,
                    line_total_minor=line.line_total_minor,
                )
                for line in lines
            ],
            total_uzs_minor=order.total_minor,
            created_at=order.submitted_at or order.created_at,
            updated_at=order.updated_at,
        )

    # ================================================================== ichki
    async def _validate(self, db: AsyncSession, actor: ActorContext, data: OrderRequestIn) -> None:
        assert actor.shop_id is not None
        if data.consent_version != STOREFRONT_CONSENT_VERSION:
            # Xaridor boshqa (eski) matnga rozilik bergan — sahifa yangilanib qayta yuboriladi
            raise ValidationError(
                "Consent is outdated",
                fields=[field("consent_version", "invalid_choice", expected=STOREFRONT_CONSENT_VERSION)],
            )
        policy = await db.get(ShopPolicy, actor.shop_id)
        if data.fulfillment_method == "DELIVERY":
            if policy is not None and not policy.delivery_enabled:
                raise ValidationError(
                    "Delivery is disabled", fields=[field("fulfillment_method", "invalid_choice")]
                )
            if not data.delivery_address:
                raise ValidationError("Address required", fields=[field("delivery_address", "required")])
            if data.branch_id is not None:
                await load_branch(db, actor, data.branch_id, pickup=False)
        else:
            if data.branch_id is None:
                raise ValidationError("Branch required", fields=[field("branch_id", "required")])
            await load_branch(db, actor, data.branch_id, pickup=True)  # yopiq — BRANCH_CLOSED (BL-010)
        seen: set[UUID] = set()
        for index, item in enumerate(data.lines):
            if item.sku_id in seen:
                raise ValidationError("Duplicate SKU", fields=[field(f"lines[{index}].sku_id", "not_unique")])
            seen.add(item.sku_id)
        snapshots = await self.catalog.get_skus(db, actor.shop_id, [i.sku_id for i in data.lines])
        for index, item in enumerate(data.lines):
            if item.sku_id not in snapshots:  # boshqa shop SKU'si — xuddi yo'qdek
                raise ValidationError("Unknown SKU", fields=[field(f"lines[{index}].sku_id", "invalid")])
        missing = [{"sku_id": i.sku_id} for i in data.lines if not usable(snapshots.get(i.sku_id))]
        if missing:  # saytdan olingan yoki narxi yo'q — savatchadan olib tashlanadi
            raise ProductNotAvailableError("Product is not available", lines=missing)

    async def _out(self, db: AsyncSession, order: Order, token: str) -> OrderRequestOut:
        lines = await self._lines(db, order)
        stock = await self.stock.availability(db, order.shop_id, [line.sku_id for line in lines])

        def available(line: OrderLine) -> bool:
            info = stock.get(line.sku_id)
            if info is None:
                return False
            if order.branch_id is None or order.fulfillment_method == "DELIVERY":
                return info.available >= line.qty
            branch = next((b for b in info.pickup_branches if b.branch_id == order.branch_id), None)
            return branch is not None and branch.available >= line.qty

        return OrderRequestOut(
            number=order.number,
            status=public_status(order),
            tracking_token=token,
            tracking_path=f"/orders/{token}",
            fulfillment_method=order.fulfillment_method,
            total_uzs_minor=order.total_minor,
            lines=[
                OrderRequestLineOut(
                    sku_id=line.sku_id,
                    title=line.title_snapshot,
                    qty=line.qty,
                    unit_price_uzs_minor=line.unit_price_uzs_minor,
                    line_total_minor=line.line_total_minor,
                    available_in_branch=available(line),
                )
                for line in lines
            ],
            created_at=order.submitted_at or order.created_at,
        )

    @staticmethod
    async def _lines(db: AsyncSession, order: Order) -> list[OrderLine]:
        rows = await db.execute(
            select(OrderLine)
            .where(OrderLine.shop_id == order.shop_id, OrderLine.order_id == order.id)
            .order_by(OrderLine.position, OrderLine.id)
        )
        return list(rows.scalars())

    @staticmethod
    async def _by_request(db: AsyncSession, shop_id: UUID, key: str) -> Order | None:
        return (
            await db.execute(
                select(Order).where(
                    Order.shop_id == shop_id, Order.source == "STOREFRONT", Order.source_request_id == key
                )
            )
        ).scalar_one_or_none()
