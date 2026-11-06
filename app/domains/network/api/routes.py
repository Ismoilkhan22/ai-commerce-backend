"""Shop paneli: global qidiruvdagi takliflar (Stage 2, M24). Standartda hammasi yopiq (BL-079).

GET  /network/skus?q=          — mahsulotlar va ularning ommaviy holati
POST /network/offers {sku_ids} — ommaviy qilish (faqat ACTIVE shop)
POST /network/offers/{sku_id}/withdraw — darhol yopish (BL-080)
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.domains.network import permissions as perm
from app.domains.network.models.orm import CanonicalProduct
from app.domains.network.providers import NetworkServices, network_services
from app.domains.network.schemas import NetworkSkuList, NetworkSkuRow, OfferList, OfferOut, PublishIn
from app.domains.network.services.api_keys import ApiKeyCreatedOut, ApiKeyIn, ApiKeyList, ApiKeyOut
from app.domains.network.services.offers import _problem
from app.platform.shops.models.orm import Shop
from app.platform.staff.infrastructure.guard import RequestContext, require_permission

router = APIRouter(prefix="/network", tags=["network"])

Network = Annotated[NetworkServices, Depends(network_services)]
CanView = Annotated[RequestContext, Depends(require_permission(perm.VIEW))]
CanManage = Annotated[RequestContext, Depends(require_permission(perm.MANAGE))]


@router.get("/skus", response_model=NetworkSkuList)
async def list_network_skus(
    request: Request,
    ctx: CanView,
    svc: Network,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> NetworkSkuList:
    assert ctx.actor.shop_id is not None
    shop_id = ctx.actor.shop_id
    catalog = svc.offers.catalog
    sku_ids = await catalog.pick_sku_ids(ctx.db, shop_id, q, limit)
    facts = await catalog.network_facts(ctx.db, shop_id, sku_ids)
    offers = await svc.offers.offers_for(ctx.db, shop_id, sku_ids)
    links = await svc.offers.links_for(ctx.db, shop_id, sku_ids)
    canonical_ids = {link.canonical_id for link in links.values() if link.canonical_id}
    titles: dict[UUID, str] = {}
    for canonical_id in canonical_ids:
        canonical = await ctx.db.get(CanonicalProduct, canonical_id)
        if canonical is not None:
            titles[canonical_id] = canonical.title
    shop = await ctx.db.get(Shop, shop_id)
    items: list[NetworkSkuRow] = []
    for sku_id in sku_ids:
        fact = facts.get(sku_id)
        if fact is None:
            continue
        link = links.get(sku_id)
        offer = offers.get(sku_id)
        items.append(
            NetworkSkuRow(
                sku_id=sku_id,
                title=fact.title,
                brand=fact.brand,
                sellable=fact.sellable,
                price_uzs_minor=fact.uzs_amount_minor,
                publishable_problem=_problem(fact),
                offer=OfferOut.model_validate(offer) if offer else None,
                link_status=link.status if link else None,
                link_reason=link.reason if link else None,
                canonical_title=titles.get(link.canonical_id) if link and link.canonical_id else None,
            )
        )
    return NetworkSkuList(items=items, shop_verified=bool(shop and shop.status == "ACTIVE"))


@router.post("/offers", response_model=OfferList)
async def publish_offers(body: PublishIn, ctx: CanManage, svc: Network) -> OfferList:
    """Faqat tekshirilgan (ACTIVE) shop: aks holda 422 `SHOP_NOT_VERIFIED`. Narxi yo'q yoki sotuvda bo'lmagan
    SKU — 422 (`not_publishable`, har biri sababi bilan)."""
    offers = await svc.offers.publish(
        ctx.db, ctx.actor, list(dict.fromkeys(body.sku_ids)), body.permitted_fields
    )
    return OfferList(items=[OfferOut.model_validate(o) for o in offers])


@router.post("/offers/{sku_id}/withdraw", response_model=OfferOut)
async def withdraw_offer(sku_id: UUID, ctx: CanManage, svc: Network) -> OfferOut:
    return OfferOut.model_validate(await svc.offers.withdraw(ctx.db, ctx.actor, sku_id))


# ------------------------------------------------------------------ M30: hamkor API kalitlari (faqat ega)
CanKeys = Annotated[RequestContext, Depends(require_permission(perm.API_KEYS))]


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=200)


@router.get("/api-keys", response_model=ApiKeyList)
async def list_api_keys(ctx: CanKeys, svc: Network) -> ApiKeyList:
    return await svc.api_keys.list_keys(ctx.db, ctx.actor)


@router.post("/api-keys", response_model=ApiKeyCreatedOut, status_code=201)
async def create_api_key(body: ApiKeyIn, ctx: CanKeys, svc: Network) -> ApiKeyCreatedOut:
    """Sir (`secret`) faqat shu javobda — saqlab qo'ying; bazada faqat xesh."""
    return await svc.api_keys.create(ctx.db, ctx.actor, body)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_api_key(key_id: UUID, body: RevokeIn, ctx: CanKeys, svc: Network) -> ApiKeyOut:
    """Darhol: keyingi so'rovdanoq 401 (sizib chiqqan kalit — BL-089)."""
    return await svc.api_keys.revoke(ctx.db, ctx.actor, key_id, body.reason)
