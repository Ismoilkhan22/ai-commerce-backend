"""Stage 3 (M31, M32, M35): global qidiruv, narx solishtirish, shopga yo'naltirish — db/marketplace.md.

Qabul mezonlari: faqat ommaviy (ACTIVE) takliflar; bir xil mahsulot — bitta natija, narx oralig'i bilan;
yopilgan taklif darhol yo'qoladi (TC-015) va unga o'tib bo'lmaydi; ruxsat etilmagan maydon (narx)
ko'rinmaydi; yo'naltirish yoziladi va shop sayti havolasini beradi.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok
from tests.integration.test_network import _activate, _product, _publish, clean_outbox  # noqa: F401

pytestmark = pytest.mark.integration
API = "/api/v1/public/marketplace"


def test_search_compare_visit_and_withdraw(world: World) -> None:
    a, b = Shop(world), Shop(world)
    _activate(world, a)
    _activate(world, b)
    mpn = f"Z{uuid4().hex[:8].upper()}"
    word = f"zenit{uuid4().hex[:6]}"
    gpu_a = _product(a, f"{word} RTX 4060 8GB", "MSI", mpn, amount=410_000_000)
    gpu_b = _product(b, f"{word} RTX 4060 OC", "MSI", mpn, amount=395_000_000)
    hidden = _product(a, f"{word} yashirin", "MSI", None)
    _ok(_publish(world, a.owner, gpu_a))
    _ok(_publish(world, b.owner, gpu_b))

    found = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert len(found) == 1, found  # bir xil (brend + MPN) — bitta natija; yopiq SKU yo'q
    item = found[0]
    assert item["offers_count"] == 2 and item["min_price_uzs_minor"] == 395_000_000
    assert item["max_price_uzs_minor"] == 410_000_000 and item["offer"]["price_uzs_minor"] == 395_000_000
    assert "eng arzon" not in str(item).lower()
    product = _ok(world.client.get(f"{API}/products/{item['canonical_id']}"))
    assert [o["price_uzs_minor"] for o in product["offers"]] == [395_000_000, 410_000_000]
    cheap = product["offers"][0]

    visit = _ok(world.client.post(f"{API}/offers/{cheap['offer_id']}/visit"))
    assert visit["url"].startswith(f"http://{cheap['shop_slug']}.") and "/p/" in visit["url"]
    count = _admin_sql(
        world, "SELECT count(*) AS n FROM network.referrals WHERE offer_id = $1", cheap["offer_id"]
    )
    assert count[0]["n"] == 1

    # Yopildi — darhol yo'qoladi, unga o'tib bo'lmaydi (TC-015)
    _ok(world.client.post(f"/api/v1/shop/network/offers/{gpu_b}/withdraw", headers=_bearer(b.owner)))
    found = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert found[0]["offers_count"] == 1 and found[0]["min_price_uzs_minor"] == 410_000_000
    assert world.client.post(f"{API}/offers/{cheap['offer_id']}/visit").status_code == 404
    assert hidden  # ommaviy qilinmagan — qidiruvda hech qachon chiqmagan


def test_price_hidden_when_not_permitted_and_price_filter(world: World) -> None:
    shop = Shop(world)
    _activate(world, shop)
    word = f"orbit{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} SSD 1TB", "Samsung", f"MZ{uuid4().hex[:6].upper()}", amount=120_000_000)
    _ok(
        world.client.post(
            "/api/v1/shop/network/offers",
            json={"sku_ids": [sku], "permitted_fields": ["condition", "availability"]},
            headers=_bearer(shop.owner),
        )
    )
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert item["offer"]["price_uzs_minor"] is None and item["min_price_uzs_minor"] is None
    assert _ok(world.client.get(f"{API}/search?q={word}&max_price_uzs_minor=200000000"))["items"] == []


def test_verified_badge_and_buyer_report(world: World) -> None:
    """M29: belgi faqat dalil bilan va muddatli; shikoyat bo'yicha yashirilgan taklif qaytmaydi."""
    shop = Shop(world)
    _activate(world, shop)
    word = f"nova{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} Ryzen 7 7700", "AMD", f"100-{uuid4().hex[:6].upper()}")
    _ok(_publish(world, shop.owner, sku))
    admin = _bearer(world.admin_token)
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert item["offer"]["shop_verified"] is False

    bad = world.client.post(
        f"/api/v1/platform/network/shops/{shop.id}/badges", json={"evidence": "x"}, headers=admin
    )
    assert bad.status_code == 422  # dalil majburiy
    badge = _ok(
        world.client.post(
            f"/api/v1/platform/network/shops/{shop.id}/badges",
            json={"evidence": "STIR va guvohnoma tekshirildi (2026-11-03)", "valid_months": 12},
            headers=admin,
        ),
        201,
    )
    assert badge["active"] is True
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert item["offer"]["shop_verified"] is True
    _admin_sql(
        world,
        "UPDATE network.shop_badges SET valid_until = now() - interval '1 day' WHERE shop_id = $1",
        shop.id,
    )
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert item["offer"]["shop_verified"] is False  # muddati o'tdi — o'zi yo'qoladi

    offer_id = item["offer"]["offer_id"]
    reported = world.client.post(
        f"{API}/offers/{offer_id}/report", json={"reason": "WRONG_PRICE", "note": "Narx boshqa"}
    )
    assert reported.status_code == 202
    reports = _ok(world.client.get("/api/v1/platform/network/reports", headers=admin))["items"]
    report = next(r for r in reports if r["offer_id"] == offer_id)
    assert report["reason"] == "WRONG_PRICE" and report["offer_title"].startswith(word)
    resolved = world.client.post(
        f"/api/v1/platform/network/reports/{report['id']}/resolve",
        json={"action": "SUSPEND_OFFER", "resolution": "Narx saytdagidan farq qiladi"},
        headers=admin,
    )
    assert resolved.status_code == 204
    assert _ok(world.client.get(f"{API}/search?q={word}"))["items"] == []
    again = _publish(world, shop.owner, sku)
    assert again.status_code == 422 and "platform_suspended" in again.text
