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


def test_global_advisor_uses_only_public_tools_and_returns_sources(world: World) -> None:
    """M34 (BL-097, BL-098): faqat ommaviy tool'lar va manbalar; sitemap — faqat amaldagi takliflar."""
    from app.platform.llm.providers.fake import FakeProvider, FakeText, FakeTools

    shop = Shop(world)
    _activate(world, shop)
    word = f"vega{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} RTX 4070", "MSI", f"V{uuid4().hex[:7].upper()}", amount=700_000_000)
    _ok(_publish(world, shop.owner, sku))
    llm: FakeProvider = world.client.app.state.sales_ai.router.provider
    llm.script.clear()
    llm.requests.clear()
    llm.push(
        FakeTools((("market_search", {"query": word, "max_price_uzs": None, "in_stock_only": False}),)),
        FakeText("Topildi: 1 ta do'konda, eng past e'lon qilingan narx 7 000 000 so'm."),
    )
    out = _ok(world.client.post(f"{API}/advisor", json={"message": f"{word} bormi? Tel: +998901234567"}))
    assert out["answer"].startswith("Topildi") and len(out["sources"]) == 1
    assert out["sources"][0]["min_price_uzs_minor"] == 700_000_000
    request = llm.requests[0]
    assert {t.name for t in request.tools} == {"market_search", "market_compare"}  # shop AI tool'lari yo'q
    assert "901234567" not in str(request.messages)  # PII tashqi AI'ga ketmadi
    usage = _admin_sql(
        world,
        "SELECT count(*) AS n FROM platform.ai_usage WHERE purpose = 'MARKET_ADVISOR' AND shop_id IS NULL",
    )
    assert usage[0]["n"] >= 2
    sitemap = _ok(world.client.get(f"{API}/sitemap"))["items"]
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    assert item["canonical_id"] in {i["canonical_id"] for i in sitemap}


def test_branch_map_only_when_permitted_and_straight_line_distance(world: World) -> None:
    """M33 (BL-095, BL-096): filial faqat ega `branch` ruxsat bersa; masofa — to'g'ri chiziq bo'yicha."""
    shop = Shop(world)
    _activate(world, shop)
    _admin_sql(
        world,
        "UPDATE platform.branches SET latitude = 41.311081, longitude = 69.240562 WHERE id = $1",
        shop.branch,
    )
    word = f"atlas{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} SSD", "Samsung", f"A{uuid4().hex[:7].upper()}")
    shop.receive(sku, 3)
    _ok(_publish(world, shop.owner, sku))  # standart — filialsiz
    [item] = _ok(world.client.get(f"{API}/search?q={word}"))["items"]
    product = _ok(world.client.get(f"{API}/products/{item['canonical_id']}"))
    assert product["offers"][0]["branches"] == []
    _ok(world.client.post(f"/api/v1/shop/network/offers/{sku}/withdraw", headers=_bearer(shop.owner)))
    fields = ["price", "availability", "branch"]
    _ok(
        world.client.post(
            "/api/v1/shop/network/offers",
            json={"sku_ids": [sku], "permitted_fields": fields},
            headers=_bearer(shop.owner),
        )
    )
    product = _ok(world.client.get(f"{API}/products/{item['canonical_id']}?lat=41.2995&lon=69.2401"))
    [branch] = product["offers"][0]["branches"]
    assert branch["availability"] == "IN_STOCK" and branch["name"] == "Chilonzor"
    assert 1.0 <= branch["distance_km"] <= 1.6  # ~1.3 km to'g'ri chiziq
    no_location = _ok(world.client.get(f"{API}/products/{item['canonical_id']}"))
    assert no_location["offers"][0]["branches"][0]["distance_km"] is None


def test_ads_are_labeled_separate_and_need_approval(world: World) -> None:
    """M37 (BL-099, BL-104): reklama alohida va belgilangan; tasdiqsiz yo'q; oddiy natija o'zgarmaydi."""
    from datetime import UTC, datetime, timedelta

    shop = Shop(world)
    _activate(world, shop)
    word = f"orion{uuid4().hex[:6]}"
    sku = _product(shop, f"{word} monitor 27", "LG", f"O{uuid4().hex[:7].upper()}")
    _ok(_publish(world, shop.owner, sku))
    before = _ok(world.client.get(f"{API}/search?q={word}"))
    assert before["sponsored"] == []
    now = datetime.now(UTC)
    ad = _ok(
        world.client.post(
            "/api/v1/shop/network/ads",
            json={
                "sku_id": sku,
                "starts_at": (now - timedelta(hours=1)).isoformat(),
                "ends_at": (now + timedelta(days=7)).isoformat(),
            },
            headers=_bearer(shop.owner),
        ),
        201,
    )
    assert ad["status"] == "PENDING_REVIEW"
    assert _ok(world.client.get(f"{API}/search?q={word}"))["sponsored"] == []  # tasdiqsiz — yo'q
    _ok(
        world.client.post(
            f"/api/v1/platform/network/ads/{ad['id']}/approve", headers=_bearer(world.admin_token)
        )
    )
    after = _ok(world.client.get(f"{API}/search?q={word}"))
    assert [s["label"] for s in after["sponsored"]] == ["Reklama"]
    assert after["items"] == before["items"]  # oddiy natijalar reklamadan mustaqil
    offer_id = after["sponsored"][0]["offer"]["offer_id"]
    _ok(world.client.post(f"{API}/offers/{offer_id}/visit?ad={ad['id']}"))
    ads = _ok(world.client.get("/api/v1/shop/network/ads", headers=_bearer(shop.owner)))["items"]
    assert ads[0]["clicks"] == 1
