"""Stage 2 (M23, M24): ommaviy takliflar va umumiy mahsulot — db/network.md.

Qabul mezonlari: standartda yopiq; faqat ACTIVE shop; (brend + MPN) bo'yicha ikki shop bitta umumiy
mahsulotga; MPN'siz — ko'rib chiqishga; narx o'zgarsa `listing_version` oshadi; yopish darhol;
shop to'xtatilsa — hammasi yashiriladi (TC-NET-03); boshqa shop taklifini yopa olmaydi;
sotuvchi kira olmaydi.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.shared.events.models import OUTBOX_SCHEMAS
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _hdr, _ok, _post
from tests.integration.test_jobs_events import _drain_now

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> None:
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )


def _activate(world: World, shop: Shop) -> None:
    _ok(
        world.client.post(
            "/api/v1/shop/profile/submit-for-verification", headers=_bearer(shop.owner, **_idem())
        )
    )
    _ok(
        world.client.post(
            f"/api/v1/platform/shops/{shop.id}/activate", headers=_bearer(world.admin_token, **_idem())
        )
    )


def _product(shop: Shop, title: str, brand: str | None, mpn: str | None, amount: int = 400_000_000) -> str:
    sku: dict[str, Any] = {
        "sku_code": f"N-{uuid4().hex[:8]}",
        "price": {"amount_minor": amount, "currency": "UZS"},
    }
    if mpn:
        sku["mpn"] = mpn
    body: dict[str, Any] = {"category_code": "GPU", "title": title, "skus": [sku]}
    if brand:
        body["brand"] = brand
    product = _ok(shop.world.client.post("/api/v1/shop/products", json=body, headers=_hdr(shop.owner)), 201)
    _ok(_post(shop.world, shop.owner, f"/products/{product['id']}/publish"))
    return str(product["skus"][0]["id"])


def _publish(world: World, token: str, *sku_ids: str) -> Any:
    return world.client.post(
        "/api/v1/shop/network/offers", json={"sku_ids": list(sku_ids)}, headers=_bearer(token)
    )


def _offer(world: World, shop: Shop, sku_id: str) -> dict[str, Any] | None:
    rows = _ok(world.client.get("/api/v1/shop/network/skus?limit=100", headers=_bearer(shop.owner)))["items"]
    row = next(r for r in rows if r["sku_id"] == sku_id)
    return row


def test_offers_publish_match_refresh_withdraw_and_suspend(world: World) -> None:
    a, b = Shop(world), Shop(world)
    mpn = f"V{uuid4().hex[:6].upper()}-012R"
    gpu_a = _product(a, "MSI RTX 4060 Ventus 2X 8G", "MSI", mpn)
    gpu_b = _product(b, "MSI GeForce RTX 4060 VENTUS 8GB", "msi", mpn.replace("-", ""))
    lonely = _product(a, "Noma'lum videokarta", None, None)

    # Standartda yopiq; tekshirilmagan shop chiqara olmaydi
    row = _offer(world, a, gpu_a)
    assert row is not None and row["offer"] is None and row["publishable_problem"] is None
    assert _publish(world, a.owner, gpu_a).status_code == 422  # SHOP_NOT_VERIFIED
    _activate(world, a)
    _activate(world, b)

    offers = _ok(_publish(world, a.owner, gpu_a, lonely))["items"]
    assert {o["status"] for o in offers} == {"ACTIVE"} and all(o["listing_version"] == 1 for o in offers)
    _ok(_publish(world, b.owner, gpu_b))
    row_a, row_b = _offer(world, a, gpu_a), _offer(world, b, gpu_b)
    assert row_a and row_b
    assert (
        row_a["link_status"] == "LINKED" and row_a["offer"]["canonical_id"] == row_b["offer"]["canonical_id"]
    )
    row_lonely = _offer(world, a, lonely)
    assert (
        row_lonely
        and row_lonely["link_status"] == "PENDING_REVIEW"
        and row_lonely["link_reason"] == "NO_BRAND"
    )

    # Narx o'zgardi → proyeksiya va versiya yangilanadi (event orqali)
    history = _ok(world.client.get(f"/api/v1/shop/skus/{gpu_a}/price-history", headers=_bearer(a.owner)))
    current_version = len(history["items"])
    _ok(
        world.client.put(
            f"/api/v1/shop/skus/{gpu_a}/price",
            json={"amount_minor": 390_000_000, "currency": "UZS"},
            headers=_bearer(a.owner, **_idem(), **{"If-Match": f'"v{current_version}"'}),
        )
    )
    _drain_now(world)
    row_a = _offer(world, a, gpu_a)
    assert (
        row_a and row_a["offer"]["price_uzs_minor"] == 390_000_000 and row_a["offer"]["listing_version"] == 2
    )

    # Boshqa shop yopa olmaydi; sotuvchi kira olmaydi
    assert (
        world.client.post(
            f"/api/v1/shop/network/offers/{gpu_a}/withdraw", headers=_bearer(b.owner)
        ).status_code
        == 404
    )
    sales, _ = a.staff("SALES")
    assert world.client.get("/api/v1/shop/network/skus", headers=_bearer(sales)).status_code == 403

    # Ega yopdi — darhol, narx o'zgarsa ham qaytmaydi
    closed = _ok(world.client.post(f"/api/v1/shop/network/offers/{gpu_a}/withdraw", headers=_bearer(a.owner)))
    assert (
        closed["status"] == "WITHDRAWN"
        and closed["withdraw_reason"] == "OWNER"
        and closed["listing_version"] == 3
    )

    # Shop to'xtatildi → hamma takliflari yashiriladi (TC-NET-03)
    _ok(
        world.client.post(
            f"/api/v1/platform/shops/{b.id}/suspend",
            json={"reason": "Tekshiruv"},
            headers=_bearer(world.admin_token, **_idem()),
        )
    )
    _drain_now(world)
    row_b = _offer(world, b, gpu_b)
    assert (
        row_b
        and row_b["offer"]["status"] == "SUSPENDED"
        and row_b["offer"]["withdraw_reason"] == "SHOP_SUSPENDED"
    )
    events = _admin_sql(
        world,
        "SELECT event_type FROM network.outbox_events WHERE shop_id = $1 ORDER BY occurred_at",
        UUID(str(b.id)),
    )
    assert [e["event_type"] for e in events][-1] == "network.public_offer.withdrawn"


def test_platform_review_links_offer_without_mpn(world: World) -> None:
    shop = Shop(world)
    _activate(world, shop)
    sku = _product(shop, "Gigabyte RTX 4070 Windforce", "Gigabyte", None)
    _ok(_publish(world, shop.owner, sku))
    queue = _ok(world.client.get("/api/v1/platform/network/review", headers=_bearer(world.admin_token)))[
        "items"
    ]
    item = next(i for i in queue if i["sku_id"] == sku)
    assert item["reason"] == "NO_MPN" and item["shop_name"] == "TechPC"
    decided = world.client.post(
        f"/api/v1/platform/network/review/{shop.id}/{sku}",
        json={
            "create": {
                "brand": "Gigabyte",
                "mpn": "GV-N4070WF2-12GD",
                "title": "Gigabyte RTX 4070 Windforce 12GB",
                "category_code": "GPU",
            }
        },
        headers=_bearer(world.admin_token),
    )
    assert decided.status_code == 204, decided.text
    row = _offer(world, shop, sku)
    assert (
        row
        and row["link_status"] == "LINKED"
        and row["canonical_title"] == "Gigabyte RTX 4070 Windforce 12GB"
    )
    canonicals = _ok(
        world.client.get(
            "/api/v1/platform/network/canonicals?q=GV-N4070WF2", headers=_bearer(world.admin_token)
        )
    )
    assert [c["title"] for c in canonicals["items"]] == ["Gigabyte RTX 4070 Windforce 12GB"]
    # Shop xodimi platforma navbatini ko'ra olmaydi
    assert world.client.get("/api/v1/platform/network/review", headers=_bearer(shop.owner)).status_code in (
        401,
        403,
    )
