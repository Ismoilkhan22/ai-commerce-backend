"""4-modul (shop sayti): sozlamalar, ommaviy o'qish, buyurtma so'rovi va holat sahifasi — haqiqiy PostgreSQL.

Qabul mezonlari (vazifa kartasi): ommaviy javobda faqat ruxsat etilgan maydonlar (TC-SEC-09), bir shop
keshida boshqasi ko'rinmaydi, yashirilgan mahsulot darhol yo'qoladi, kursi yo'q dollar narxi ko'rsatilmaydi,
filial bo'yicha mavjudlik qoidasi (DEC-135), buyurtma so'rovi takrori — bitta buyurtma, rozilik majburiy,
yetkazish o'chiq bo'lsa — 422, so'rov chegaralari, sayt holatlari, ko'rib chiqish tokeni, holat sahifasida PII
yo'q, telefon shifrlangan, buyurtma panelda "Tasdiq kutilmoqda" va band qilinmagan, sozlamani faqat ega.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.domains.storefront.common import PreviewSigner
from app.shared.consent import STOREFRONT_CONSENT_VERSION
from tests.images import png
from tests.integration.helpers import World, _bearer, _code, _phone, _sql
from tests.integration.test_commerce import PHONE, Shop, _admin_sql, _fields, _hdr, _ok, _post

pytestmark = pytest.mark.integration


class Site:
    """Shop (ega, ikki olib ketish filiali) + faol holat + ochiq sayt."""

    def __init__(self, world: World, *, live: bool = True, active: bool = True) -> None:
        self.world = world
        self.shop = Shop(world)
        self.slug = str(
            world.client.get("/api/v1/shop/profile", headers=_bearer(self.shop.owner)).json()["slug"]
        )
        if active:
            _admin_sql(world, "UPDATE platform.shops SET status = 'ACTIVE' WHERE id = $1", self.shop.id)
        if live:
            self.configure({"contact_phone": "+998 71 200 00 00", "tagline": "Rasmiy kafolat bilan"})
            self.transition("publish")

    @property
    def owner(self) -> str:
        return self.shop.owner

    def settings(self, token: str | None = None) -> dict[str, Any]:
        return _ok(self.world.client.get("/api/v1/shop/storefront", headers=_bearer(token or self.owner)))

    def configure(self, body: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        version = self.settings()["version"]
        response = self.world.client.patch(
            "/api/v1/shop/storefront", json=body, headers=_hdr(token or self.owner, version)
        )
        return _ok(response)

    def transition(self, command: str) -> dict[str, Any]:
        version = self.settings()["version"]
        return _ok(_post(self.world, self.owner, f"/storefront/{command}", version=version))

    def get(self, path: str, **headers: str) -> Any:
        return self.world.client.get(f"/api/v1/storefront/{self.slug}{path}", headers=headers)

    def order(self, lines: dict[str, int], key: str | None = None, **extra: Any) -> Any:
        body = {
            "customer_name": "Jasur",
            "customer_phone": PHONE,
            "fulfillment_method": "PICKUP",
            "branch_id": self.shop.branch,
            "consent_version": STOREFRONT_CONSENT_VERSION,
            "lines": [{"sku_id": sku, "qty": qty} for sku, qty in lines.items()],
            **extra,
        }
        return self.world.client.post(
            f"/api/v1/storefront/{self.slug}/order-requests",
            json=body,
            headers={"Idempotency-Key": key or f"sf-{uuid4()}"},
        )


def _keys(value: dict[str, Any]) -> set[str]:
    return set(value)


# ------------------------------------------------------------------ TC-SEC-09: faqat ruxsat etilgan maydonlar


def test_public_responses_expose_only_allowlisted_fields(world: World) -> None:
    site = Site(world)
    shop = site.shop
    sku = shop.sku(480_000_000)
    shop.receive(sku, 3)
    site_body = _ok(site.get("/site"))
    assert _keys(site_body) == {
        "state", "preview", "shop", "theme", "logo_url", "tagline", "seo_description", "contacts", "pages",
        "delivery_enabled", "stock_display", "pickup_branch_count", "consent", "legal",
    }  # fmt: skip
    assert site_body["state"] == "LIVE" and site_body["contacts"]["phone"] == "+998712000000"
    assert _keys(site_body["shop"]) == {"name", "slug", "url"}
    slug = site_body["shop"]["slug"]
    assert site_body["shop"]["url"] == world.settings.storefront_public_url.format(slug=slug)  # U6
    assert site_body["consent"]["version"] == STOREFRONT_CONSENT_VERSION
    listing = _ok(site.get("/products"))
    card = listing["items"][0]
    assert _keys(card) == {
        "id", "slug", "title", "brand", "category_code", "image_url", "price_from_uzs_minor", "variant_count",
        "stock_status", "available",
    }  # fmt: skip
    assert card["available"] is None and card["stock_status"] == "IN_STOCK"  # STATUS_ONLY (DEC-128)
    detail = _ok(site.get(f"/products/{card['id']}"))
    assert _keys(detail) == {
        "id", "slug", "canonical_path", "title", "brand", "description", "category_code", "images",
        "variants",
        "as_of",
    }  # fmt: skip
    assert _keys(detail["variants"][0]) == {
        "sku_id", "name", "condition", "warranty_months", "attributes", "price_uzs_minor", "stock_status",
        "available", "branches",
    }  # fmt: skip
    raw = str(listing) + str(detail)
    for secret in ("sku_code", "mpn", "model_name", "amount_minor", "price_version", "created_by"):
        assert secret not in raw  # tannarx, SKU kodi va ichki maydonlar saytga chiqmaydi
    branches = _ok(site.get("/branches"))["items"]
    assert _keys(branches[0]) == {"id", "name", "address", "phone", "working_hours", "latitude", "longitude"}


# ------------------------------------------------------------------ sayt holatlari, ko'rib chiqish


def test_site_states_for_customers(world: World) -> None:
    assert world.client.get("/api/v1/storefront/yoq-bunday-shop/site").status_code == 404
    assert world.client.get("/api/v1/storefront/Bad_Slug!/site").status_code == 404
    draft_shop = Site(world, live=False, active=False)
    body = _ok(draft_shop.get("/site"))
    assert body["state"] == "COMING_SOON" and body["theme"] is None and body["shop"]["name"] == "TechPC"
    blocked = draft_shop.get("/products")
    assert blocked.status_code == 409 and _code(blocked) == "SITE_NOT_AVAILABLE"
    assert blocked.json()["error"]["details"]["state"] == "COMING_SOON"

    site = Site(world)
    assert _ok(site.get("/site"))["state"] == "LIVE"
    site.transition("pause")
    assert _ok(site.get("/site"))["state"] == "PAUSED"
    assert site.get("/categories").status_code == 409
    site.transition("resume")
    assert _ok(site.get("/site"))["state"] == "LIVE"
    _admin_sql(world, "UPDATE platform.shops SET status = 'SUSPENDED' WHERE id = $1", site.shop.id)
    assert _ok(site.get("/site"))["state"] == "PAUSED"  # to'xtatilgan shop — darhol (holat keshlanmaydi)
    _admin_sql(world, "UPDATE platform.shops SET status = 'CLOSED' WHERE id = $1", site.shop.id)
    assert site.get("/site").status_code == 404  # yopilgan shop — xuddi yo'qdek


def test_owner_preview_token(world: World) -> None:
    site = Site(world, live=False)
    other = Site(world, live=False)
    issued = _ok(_post(world, site.owner, "/storefront/preview"))
    token = issued["token"]
    assert issued["preview_url"].endswith(f"?preview={token}") and site.slug in issued["preview_url"]
    assert site.get("/products").status_code == 409
    by_query = _ok(world.client.get(f"/api/v1/storefront/{site.slug}/site", params={"preview": token}))
    assert (
        by_query["state"] == "COMING_SOON" and by_query["preview"] is True and by_query["theme"] is not None
    )
    assert _ok(site.get("/products", **{"X-Storefront-Preview": token}))["items"] == []
    foreign = _ok(other.get("/site", **{"X-Storefront-Preview": token}))
    assert foreign["preview"] is False and foreign["theme"] is None  # boshqa shop tokeni — kuchsiz
    expired, _ = PreviewSigner(world.settings.jwt_secret.get_secret_value()).issue(
        site.shop.id, now=datetime.now(UTC) - timedelta(hours=1)
    )
    assert _ok(site.get("/site", **{"X-Storefront-Preview": expired}))["preview"] is False
    assert _ok(site.get("/site", **{"X-Storefront-Preview": token[:-2] + "00"}))["preview"] is False
    sku = site.shop.sku()
    site.shop.receive(sku, 1)
    refused = site.order({sku: 1})  # ko'rib chiqishda buyurtma formasi o'chiq — sayt hali ochilmagan
    assert refused.status_code == 409 and _code(refused) == "SITE_NOT_AVAILABLE"


# ------------------------------------------------------------------ panel: faqat ega, tekshiruvlar


def test_only_owner_edits_and_manager_views(world: World) -> None:
    site = Site(world, live=False)
    manager, _ = site.shop.staff("MANAGER")
    sales, _ = site.shop.staff("SALES")
    assert site.settings(manager)["status"] == "DRAFT"
    patch = world.client.patch("/api/v1/shop/storefront", json={"tagline": "x"}, headers=_hdr(manager, 0))
    assert patch.status_code == 403
    assert _post(world, manager, "/storefront/publish", version=0).status_code == 403
    assert world.client.get("/api/v1/shop/storefront", headers=_bearer(sales)).status_code == 403
    page = world.client.put(
        "/api/v1/shop/storefront/pages/ABOUT",
        json={"title": "Biz", "body_md": "Matn", "is_published": True},
        headers=_hdr(manager, 0),
    )
    assert page.status_code == 403


def test_settings_validation_publish_rules_and_pages(world: World) -> None:
    site = Site(world, live=False)
    first = site.settings()
    assert first["version"] == 0 and first["publish_problems"] == [
        {"field": "contact_phone", "code": "required"}
    ]
    refused = _post(world, site.owner, "/storefront/publish", version=0)
    assert refused.status_code == 422 and _fields(refused) == {"contact_phone": "required"}
    stale = world.client.patch("/api/v1/shop/storefront", json={"tagline": "a"}, headers=_hdr(site.owner, 3))
    assert stale.status_code == 409 and _code(stale) == "VERSION_CONFLICT"
    pale = world.client.patch(
        "/api/v1/shop/storefront", json={"accent_color": "#FFF59D"}, headers=_hdr(site.owner, 0)
    )
    assert pale.status_code == 422 and _fields(pale) == {"accent_color": "low_contrast"}  # oq fonda och sariq
    bad = world.client.patch(
        "/api/v1/shop/storefront",
        json={"telegram_username": "t.me/x", "contact_email": "yoq", "contact_phone": "+998 99 1234"},
        headers=_hdr(site.owner, 0),
    )
    assert bad.status_code == 422
    assert set(_fields(bad)) >= {"telegram_username", "contact_email"}
    saved = site.configure(
        {"contact_phone": "71 200 00 00", "telegram_username": "@techpc_uz", "accent_color": "#2563eb"}
    )
    assert saved["contact_phone"] == "+998712000000" and saved["telegram_username"] == "techpc_uz"
    assert saved["accent_color"] == "#2563EB" and saved["version"] == 1 and saved["publish_problems"] == []
    live = site.transition("publish")
    assert live["status"] == "LIVE" and live["state"] == "LIVE" and live["published_at"]
    cleared = world.client.patch(
        "/api/v1/shop/storefront", json={"contact_phone": None}, headers=_hdr(site.owner, live["version"])
    )
    assert cleared.status_code == 422 and _fields(cleared) == {"contact_phone": "required"}
    assert _post(world, site.owner, "/storefront/publish", version=live["version"]).status_code == 409

    pages = _ok(world.client.get("/api/v1/shop/storefront/pages", headers=_bearer(site.owner)))["items"]
    assert [(p["kind"], p["version"]) for p in pages] == [
        ("ABOUT", 0),
        ("DELIVERY_PAYMENT", 0),
        ("WARRANTY_RETURNS", 0),
    ]
    html = world.client.put(
        "/api/v1/shop/storefront/pages/ABOUT",
        json={"title": "Biz", "body_md": "<script>alert(1)</script>", "is_published": True},
        headers=_hdr(site.owner, 0),
    )
    assert html.status_code == 422 and "body_md" in _fields(html)
    js_link = world.client.put(
        "/api/v1/shop/storefront/pages/ABOUT",
        json={"title": "Biz", "body_md": "[bos](javascript:alert(1))", "is_published": True},
        headers=_hdr(site.owner, 0),
    )
    assert js_link.status_code == 422
    body = {
        "title": "Biz haqimizda",
        "body_md": "**TechPC** — 2015 yildan. Narx a < b.",
        "is_published": True,
    }
    page = _ok(
        world.client.put("/api/v1/shop/storefront/pages/ABOUT", json=body, headers=_hdr(site.owner, 0))
    )
    assert page["version"] == 1
    hidden = {"title": "Yetkazish", "body_md": "Hali yozilmoqda", "is_published": False}
    _ok(
        world.client.put(
            "/api/v1/shop/storefront/pages/DELIVERY_PAYMENT", json=hidden, headers=_hdr(site.owner, 0)
        )
    )
    public = _ok(site.get("/site"))
    assert public["pages"] == [{"kind": "ABOUT", "title": "Biz haqimizda"}]  # chiqarilmagani menyuda yo'q
    assert _ok(site.get("/pages/ABOUT"))["body_md"].startswith("**TechPC**")
    assert site.get("/pages/DELIVERY_PAYMENT").status_code == 404
    privacy = _ok(site.get("/privacy", **{"Accept-Language": "ru"}))
    assert (
        privacy["version"] == STOREFRONT_CONSENT_VERSION and privacy["title"] == "Политика конфиденциальности"
    )
    assert any("TechPC" in s["text"] for s in privacy["sections"])


# ------------------------------------------------------------------ katalog: kesh, holat, narx, filial


def test_cache_is_isolated_between_shops(world: World) -> None:
    first, second = Site(world), Site(world)
    sku_a, sku_b = first.shop.sku(), second.shop.sku()
    first.shop.receive(sku_a, 1)
    second.shop.receive(sku_b, 1)
    items_a = _ok(first.get("/products"))["items"]
    items_b = _ok(second.get("/products"))["items"]
    assert len(items_a) == len(items_b) == 1
    assert items_a[0]["id"] != items_b[0]["id"]  # bir xil parametr — har shop o'z keshidan
    assert second.get(f"/products/{items_a[0]['id']}").status_code == 404  # boshqa shop mahsuloti
    assert _ok(first.get("/products"))["items"] == items_a  # keshdan, o'zgarmagan


def test_hidden_product_disappears_immediately_even_when_cached(world: World) -> None:
    site = Site(world)
    sku = site.shop.sku()
    product_id = _ok(site.get("/products"))["items"][0]["id"]
    assert _ok(site.get(f"/products/{product_id}"))["id"] == product_id  # endi keshda
    _ok(
        _post(
            world,
            site.owner,
            f"/products/{product_id}/hide",
            {"reason": "QA"},
            version=_version(site, product_id),
        )
    )
    assert site.get(f"/products/{product_id}").status_code == 404  # kesh bo'lsa ham — darhol (UAT-M07)
    refused = site.order({sku: 1})
    assert refused.status_code == 409 and _code(refused) == "PRODUCT_NOT_AVAILABLE"


def _version(site: Site, product_id: str) -> int:
    product = _ok(site.world.client.get(f"/api/v1/shop/products/{product_id}", headers=_bearer(site.owner)))
    return int(product["version"])


def test_usd_price_needs_rate_and_converts_exactly(world: World) -> None:
    site = Site(world)
    site.shop.rate("12800")
    sku = site.shop.sku(30_000, "USD")  # 300 $ — chiqarish uchun kurs kerak
    # Kurs yo'qolgan holat (API'da kursni o'chirib bo'lmaydi — superuser bilan): saytda ko'rinmaydi (BL-012)
    _admin_sql(world, "DELETE FROM catalog.exchange_rates WHERE shop_id = $1", site.shop.id)
    assert _ok(site.get("/products"))["items"] == []
    site.shop.rate("12835")
    site.transition("pause")  # kesh versiyasi oshadi (sayt sozlamasi o'zgardi)
    site.transition("resume")
    items = _ok(site.get("/products"))["items"]
    assert [i["price_from_uzs_minor"] for i in items] == [385_050_000]  # 3 850 500 so'm, yaxlitlanmaydi
    detail = _ok(site.get(f"/products/{items[0]['id']}"))
    assert detail["variants"][0]["sku_id"] == sku and detail["variants"][0]["price_uzs_minor"] == 385_050_000


def test_branch_availability_shown_only_with_two_pickup_points(world: World) -> None:
    site = Site(world)
    shop = site.shop
    sku = shop.sku()
    shop.receive(sku, 3, branch=shop.branch)
    _ok(_post(world, shop.owner, "/storefront/pause", version=site.settings()["version"]))
    site.transition("resume")
    product_id = _ok(site.get("/products"))["items"][0]["id"]
    variant = _ok(site.get(f"/products/{product_id}"))["variants"][0]
    by_branch = {b["branch_id"]: b["stock_status"] for b in variant["branches"]}
    assert by_branch == {shop.branch: "IN_STOCK", shop.branch2: "OUT_OF_STOCK"}  # 2 ta olib ketish joyi
    _admin_sql(
        world, "UPDATE platform.branches SET is_pickup_point = false WHERE id = $1", UUID(shop.branch2)
    )
    _ok(_post(world, shop.owner, "/storefront/pause", version=site.settings()["version"]))
    site.transition("resume")
    single = _ok(site.get(f"/products/{product_id}"))["variants"][0]
    assert single["branches"] is None  # bitta joy — filial bo'yicha ko'rsatilmaydi (DEC-135)
    assert _ok(site.get("/site"))["pickup_branch_count"] == 1


# ------------------------------------------------------------------ buyurtma so'rovi va holat sahifasi


def test_order_request_creates_pending_unreserved_order_and_tracking(world: World) -> None:
    site = Site(world)
    shop = site.shop
    sku, absent = shop.sku(480_000_000), shop.sku(120_000_000)
    shop.receive(sku, 2)
    key = f"sf-{uuid4()}"
    first = site.order({sku: 1, absent: 1}, key=key, customer_comment="Kechqurun qo'ng'iroq qiling")
    body = _ok(first, 201)
    assert body["status"] == "RECEIVED" and body["total_uzs_minor"] == 600_000_000
    flags = {line["sku_id"]: line["available_in_branch"] for line in body["lines"]}
    assert flags == {sku: True, absent: False}  # filialda yo'q — baribir qabul qilindi (DEC-135)
    token = body["tracking_token"]
    assert body["tracking_path"] == f"/orders/{token}"

    replay = _ok(
        site.order({sku: 1, absent: 1}, key=key, customer_comment="Kechqurun qo'ng'iroq qiling"), 201
    )
    assert replay["number"] == body["number"] and replay["tracking_token"] != token  # bitta buyurtma
    reused = site.order({sku: 2}, key=key)
    assert reused.status_code == 409 and _code(reused) == "IDEMPOTENCY_KEY_REUSED"
    assert site.get(f"/orders/{token}").status_code == 404  # eski havola bekor — faqat oxirgisi ishlaydi

    orders = _ok(world.client.get("/api/v1/shop/orders", headers=_bearer(shop.owner)))["items"]
    assert len(orders) == 1
    order = shop.get(orders[0]["id"])
    assert (order["status"], order["source"], order["assigned"]) == (
        "PENDING_CONFIRMATION",
        "STOREFRONT",
        None,
    )
    assert order["customer_phone"] == PHONE
    reservations = _admin_sql(
        world, "SELECT count(*) AS n FROM commerce.reservations WHERE order_id = $1", UUID(order["id"])
    )
    assert reservations[0]["n"] == 0
    balance = shop.balance(sku)
    assert (balance["reserved"], balance["available"]) == (0, 2)  # band qilinmaydi (DEC-100b)
    raw = _admin_sql(
        world,
        "SELECT customer_phone_enc, tracking_token_hash, consent_version, source_request_id"
        " FROM commerce.orders WHERE id = $1",
        UUID(order["id"]),
    )[0]
    assert PHONE not in raw["customer_phone_enc"] and raw["customer_phone_enc"].startswith("v1.")
    assert (
        replay["tracking_token"] not in raw["tracking_token_hash"]
        and raw["consent_version"] == STOREFRONT_CONSENT_VERSION
    )
    stored = _admin_sql(
        world,
        "SELECT response_body::text AS body FROM platform.idempotency_keys"
        " WHERE operation = 'storefront.order_request'",
    )
    assert all(
        token not in r["body"] and replay["tracking_token"] not in r["body"] and "998" not in r["body"]
        for r in stored
    )
    logs = _admin_sql(
        world,
        "SELECT actor_type, command FROM platform.transition_log WHERE entity_id = $1",
        UUID(order["id"]),
    )
    assert [(r["actor_type"], r["command"]) for r in logs] == [("CUSTOMER", "SUBMIT")]

    tracking = _ok(site.get(f"/orders/{replay['tracking_token']}"))
    assert _keys(tracking) == {
        "number", "status", "fulfillment_method", "branch", "lines", "total_uzs_minor", "created_at",
        "updated_at",
    }  # fmt: skip
    assert tracking["status"] == "RECEIVED" and tracking["branch"]["name"] == "Chilonzor"
    text = str(tracking)
    assert PHONE not in text and "Jasur" not in text and "qo'ng'iroq" not in text  # PII yo'q
    assert site.get("/orders/" + "a" * 43).status_code == 404 and site.get("/orders/qisqa").status_code == 404
    shop.receive(absent, 1)
    confirmed = shop.step(order, "confirm")
    assert confirmed["status"] == "CONFIRMED"
    assert _ok(site.get(f"/orders/{replay['tracking_token']}"))["status"] == "CONFIRMED"
    site.transition("pause")  # sayt yopilsa ham xaridor o'z buyurtmasini ko'radi
    assert _ok(site.get(f"/orders/{replay['tracking_token']}"))["status"] == "CONFIRMED"


def test_order_request_validation_rules(world: World) -> None:
    site = Site(world)
    shop = site.shop
    sku = shop.sku()
    other = Site(world)
    foreign = other.shop.sku()
    missing_consent = site.order({sku: 1}, customer_phone=_phone(), consent_version="")
    assert missing_consent.status_code == 422 and _fields(missing_consent) == {
        "consent_version": "invalid_choice"
    }
    old_consent = site.order({sku: 1}, customer_phone=_phone(), consent_version="sf-order-2020-01-01")
    assert _fields(old_consent) == {"consent_version": "invalid_choice"}
    no_branch = site.order({sku: 1}, customer_phone=_phone(), branch_id=None)
    assert no_branch.status_code == 422 and _fields(no_branch) == {"branch_id": "required"}
    no_address = site.order({sku: 1}, customer_phone=_phone(), fulfillment_method="DELIVERY", branch_id=None)
    assert _fields(no_address) == {"delivery_address": "required"}
    foreign_sku = site.order({foreign: 1}, customer_phone=_phone())
    assert foreign_sku.status_code == 422 and _fields(foreign_sku) == {"lines[0].sku_id": "invalid"}
    foreign_branch = site.order({sku: 1}, customer_phone=_phone(), branch_id=other.shop.branch)
    assert _fields(foreign_branch) == {"branch_id": "invalid"}
    bad_phone = site.order({sku: 1}, customer_phone="+998 99 1234")
    assert bad_phone.status_code == 422 and _fields(bad_phone) == {"customer_phone": "invalid_format"}
    no_key = world.client.post(f"/api/v1/storefront/{site.slug}/order-requests", json={})
    assert no_key.status_code in (400, 422)

    policies = _ok(world.client.get("/api/v1/shop/policies", headers=_bearer(shop.owner)))
    assert policies["delivery_enabled"] is True
    update = {k: v for k, v in policies.items() if k != "version"} | {"delivery_enabled": False}
    _ok(
        world.client.patch(
            "/api/v1/shop/policies", json=update, headers=_hdr(shop.owner, policies["version"])
        )
    )
    assert _ok(site.get("/site"))["delivery_enabled"] is False
    delivery = site.order(
        {sku: 1}, fulfillment_method="DELIVERY", branch_id=None, delivery_address="Chilonzor 1"
    )
    assert delivery.status_code == 422 and _fields(delivery) == {"fulfillment_method": "invalid_choice"}

    _admin_sql(world, "UPDATE platform.shops SET status = 'SUSPENDED' WHERE id = $1", shop.id)
    suspended = site.order({sku: 1}, customer_phone=_phone())
    assert suspended.status_code == 409 and _code(suspended) == "SITE_NOT_AVAILABLE"


def test_order_request_and_read_rate_limits(world: World) -> None:
    site = Site(world)
    sku = site.shop.sku()
    statuses = [site.order({sku: 1}).status_code for _ in range(6)]
    assert statuses[:5] == [201] * 5 and statuses[5] == 429  # IP + shop + telefon: 10 daqiqada 5 ta
    other_phone = site.order({sku: 1}, customer_phone="+998 93 555 01 24")
    assert other_phone.status_code == 201  # boshqa telefon — alohida hisob
    limited = site.order({sku: 1})
    assert limited.status_code == 429 and limited.headers.get("Retry-After")
    reads = [site.get("/site").status_code for _ in range(121)]
    assert reads.count(429) >= 1 and reads[0] == 200


# ------------------------------------------------------------------ RLS


def test_rls_isolates_storefront_tables(world: World) -> None:
    first, second = Site(world), Site(world)
    body = {"title": "Biz", "body_md": "Matn", "is_published": True}
    _ok(world.client.put("/api/v1/shop/storefront/pages/ABOUT", json=body, headers=_hdr(first.owner, 0)))
    runtime = world.urls.runtime
    for table in ("sites", "pages"):
        assert _sql(runtime, f"SELECT count(*) AS n FROM storefront.{table}")[0]["n"] == 0  # kontekstsiz — 0
    rows = _sql(
        runtime,
        "SELECT count(*) AS n FROM (SELECT set_config('app.shop_id', $1, false)) c, storefront.pages",
        str(second.shop.id),
    )
    assert rows[0]["n"] == 0  # boshqa shop konteksti — birinchisining sahifasi ko'rinmaydi
    forced = _admin_sql(
        world,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relnamespace = 'storefront'::regnamespace AND relkind = 'r' AND relname IN ('sites', 'pages')",
    )
    assert {r["relname"] for r in forced if r["relrowsecurity"] and r["relforcerowsecurity"]} == {
        "sites",
        "pages",
    }


def _upload_logo(world: World, token: str, data: bytes) -> Any:
    return world.client.post(
        "/api/v1/shop/files?purpose=SITE_LOGO&filename=logo.png",
        content=data,
        headers={
            **_bearer(token),
            "Idempotency-Key": f"up-{uuid4()}",
            "Content-Type": "application/octet-stream",
        },
    )


def test_logo_upload_is_owner_only_public_and_replaced(world: World) -> None:
    site = Site(world)
    manager, _ = site.shop.staff("MANAGER")
    assert _upload_logo(world, manager, png(64, 64)).status_code == 403  # logotipni faqat ega
    too_big = _upload_logo(world, site.owner, b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10))
    assert too_big.status_code in (413, 415)
    first = _ok(_upload_logo(world, site.owner, png(64, 64)), 201)
    assert first["is_public"] is True and first["url_expires_at"] is None
    saved = site.configure({"logo_file_id": first["id"]})
    assert saved["logo"]["file_id"] == first["id"]
    public_url = _ok(site.get("/site"))["logo_url"]
    assert public_url == first["url"]
    second = _ok(_upload_logo(world, site.owner, png(32, 32, (200, 10, 10))), 201)
    site.configure({"logo_file_id": second["id"]})
    states = _admin_sql(
        world,
        "SELECT id, status FROM platform.stored_files WHERE id = ANY($1::uuid[])",
        [UUID(first["id"]), UUID(second["id"])],
    )
    assert {str(r["id"]): r["status"] for r in states} == {first["id"]: "DELETED", second["id"]: "ACTIVE"}
    product_image = _ok(
        world.client.post(
            "/api/v1/shop/files?purpose=PRODUCT_IMAGE&filename=p.png",
            content=png(8, 8),
            headers={**_bearer(site.owner), "Idempotency-Key": f"up-{uuid4()}"},
        ),
        201,
    )
    wrong = world.client.patch(
        "/api/v1/shop/storefront",
        json={"logo_file_id": product_image["id"]},
        headers=_hdr(site.owner, site.settings()["version"]),
    )
    assert wrong.status_code == 422 and _fields(wrong) == {"file_id": "invalid"}  # boshqa turdagi fayl
