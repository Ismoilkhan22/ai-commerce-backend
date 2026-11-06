"""Sayt (anonim): buyurtma so'rovi va buyurtma holati — `/api/v1/storefront/{slug}/…` (DEC-115, 08 §5).

So'rov chegarasi: IP + shop + telefon xeshi — 10 daqiqada 5 ta; telefonni almashtirib aylanib o'tmaslik uchun
IP + shop bo'yicha ham 10 daqiqada 20 ta. Holat sahifasi — IP bo'yicha daqiqasiga 30 ta.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.domains.commerce.orders.services.storefront_service import CreatedRequest, StorefrontOrderService
from app.domains.commerce.orders.storefront_schemas import OrderRequestIn, OrderRequestOut, TrackingOut
from app.domains.commerce.providers import CommerceServices, commerce_services
from app.shared.client_ip import client_ip
from app.shared.contracts.storefront import ensure_open
from app.shared.db.encryption import search_hmac
from app.shared.db.session import Database
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent
from app.shared.phone import normalize_phone
from app.shared.ratelimit import RateLimiter, enforce

router = APIRouter(tags=["storefront_orders"])

Commerce = Annotated[CommerceServices, Depends(commerce_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]

ORDER_WINDOW_S = 600
ORDER_LIMIT_PER_PHONE = 5
ORDER_LIMIT_PER_IP = 20
TRACK_LIMIT_PER_MINUTE = 30


def _ip(request: Request) -> str:
    return client_ip(request)  # XFF faqat ishonchli proksidan (TRUSTED_PROXIES)


@router.post("/order-requests", response_model=OrderRequestOut, status_code=status.HTTP_201_CREATED)
async def create_order_request(
    slug: str, body: OrderRequestIn, request: Request, svc: Commerce, key: IdemKey
) -> Any:
    """Savatchadan buyurtma so'rovi. Javob — "qabul qilindi" (tasdiqlandi emas): operator bog'lanadi.
    Mahsulot band qilinmaydi; narx va mavjudlik bazadan qayta tekshiriladi. To'lov tizimdan tashqarida."""
    phone = normalize_phone(body.customer_phone, "customer_phone")
    limiter: RateLimiter = request.app.state.rate_limiter
    ip = _ip(request)
    scope = slug[:63]
    await enforce(limiter, f"sf-order-ip:{ip}:{scope}", ORDER_LIMIT_PER_IP, ORDER_WINDOW_S)
    await enforce(
        limiter, f"sf-order:{ip}:{scope}:{search_hmac(phone)[:16]}", ORDER_LIMIT_PER_PHONE, ORDER_WINDOW_S
    )
    database: Database = request.app.state.db
    storefront: StorefrontOrderService = svc.storefront
    async with database.transaction() as db:
        access = await svc.site.resolve(db, slug)
        ensure_open(access, for_order=True)

        async def replay(saved: Any) -> OrderRequestOut:
            return await storefront.reissue(db, access.shop_id, UUID(str(saved["order_id"])))

        result = await run_idempotent(
            db,
            access.shop_id,
            "storefront.order_request",
            key,
            body,
            lambda: storefront.request(db, access, body, phone, key),
            # Holat havolasi tokeni va xaridor ma'lumoti jadvalga yozilmaydi — faqat buyurtma ID'si
            stored=lambda created: {"order_id": str(created.order_id)},
            on_replay=replay,
            status=status.HTTP_201_CREATED,
        )
    return result.out if isinstance(result, CreatedRequest) else result


@router.get("/orders/{token}", response_model=TrackingOut)
async def track_order(slug: str, token: str, request: Request, svc: Commerce) -> TrackingOut:
    """Buyurtma holati — havoladagi token bo'yicha. Telefon, manzil va izoh ko'rsatilmaydi.
    Sayt vaqtincha yopilgan bo'lsa ham xaridor o'z buyurtmasini ko'radi; shop yopilgan bo'lsa — 404."""
    limiter: RateLimiter = request.app.state.rate_limiter
    await enforce(limiter, f"sf-track:{_ip(request)}", TRACK_LIMIT_PER_MINUTE)
    database: Database = request.app.state.db
    async with database.transaction(read_only=True) as db:
        access = await svc.site.resolve(db, slug)
        return await svc.storefront.track(db, access, token)
