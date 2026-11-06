"""4-modul yordamchilari (DB'siz): havola nomi, rang kontrasti, ko'rib chiqish tokeni, rozilik versiyasi,
sayt holati, kesh kalitlari va xotira keshi, sayt CORS'i, sxema tekshiruvlari, xaridorga ko'rinadigan
holat."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domains.commerce.orders.services.storefront_service import (
    TRACKING_TOKEN,
    public_status,
    tracking_hash,
)
from app.domains.storefront.common import (
    DARK_BACKGROUND,
    LIGHT_BACKGROUND,
    PreviewSigner,
    accent_text_color,
    contrast,
    title_slug,
)
from app.domains.storefront.schemas import PageUpdate, SiteUpdate
from app.domains.storefront.site_gate import site_state
from app.shared.cache import MemoryCache
from app.shared.cache.keys import global_key, shop_key
from app.shared.consent import CONSENT_FINGERPRINT, consent_fingerprint
from app.shared.contracts.storefront import SiteAccess, ensure_open
from app.shared.errors.base import SiteNotAvailableError
from app.shared.storefront_cors import StorefrontCorsMiddleware


def test_title_slug_transliterates_and_trims() -> None:
    assert title_slug("MSI GeForce RTX 4060 Ventus 2X") == "msi-geforce-rtx-4060-ventus-2x"
    assert title_slug("Видеокарта Палит  RTX/3060!!") == "videokarta-palit-rtx-3060"
    assert title_slug("Ўқувчи ноутбуки") == "oquvchi-noutbuki"
    assert title_slug("!!!") == "mahsulot"
    assert len(title_slug("a" * 200)) == 80


def test_accent_contrast_rules() -> None:
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#FFF59D", LIGHT_BACKGROUND) < 3  # och sariq oq fonda o'qilmaydi
    assert contrast("#2563EB", LIGHT_BACKGROUND) >= 3
    assert (
        contrast("#7C3AED", LIGHT_BACKGROUND) >= 3 and contrast("#7C3AED", DARK_BACKGROUND) >= 3
    )  # standart
    assert accent_text_color("#2563EB") == "#FFFFFF" and accent_text_color("#FFF59D") == "#000000"


def test_preview_token_is_shop_bound_and_expires() -> None:
    signer = PreviewSigner("secret")
    shop, other = uuid4(), uuid4()
    token, expires_at = signer.issue(shop)
    assert signer.valid_for(token, shop) and not signer.valid_for(token, other)
    assert expires_at - datetime.now(UTC) <= timedelta(minutes=30)
    old, _ = signer.issue(shop, now=datetime.now(UTC) - timedelta(minutes=31))
    assert not signer.valid_for(old, shop)
    head, exp, nonce, sig = token.split(".")
    assert not signer.valid_for(f"{head}.{int(exp) + 3600}.{nonce}.{sig}", shop)  # muddat uzaymaydi
    assert not PreviewSigner("boshqa").valid_for(token, shop)
    for junk in (None, "", "a.b", "x" * 300, f"{head}.abc.{nonce}.{sig}"):
        assert not signer.valid_for(junk, shop)


def test_consent_text_change_requires_new_version() -> None:
    # Yiqilsa: rozilik yoki maxfiylik matni o'zgargan — STOREFRONT_CONSENT_VERSION ni ham yangilang
    assert consent_fingerprint() == CONSENT_FINGERPRINT


@pytest.mark.parametrize(
    ("shop", "site", "expected"),
    [
        ("ACTIVE", "LIVE", "LIVE"),
        ("ACTIVE", "DRAFT", "COMING_SOON"),
        ("ACTIVE", "PAUSED", "PAUSED"),
        ("PENDING_VERIFICATION", "LIVE", "COMING_SOON"),
        ("DRAFT", "PAUSED", "COMING_SOON"),
        ("SUSPENDED", "LIVE", "PAUSED"),
        ("SUSPENDED", "DRAFT", "PAUSED"),
    ],
)
def test_site_state_matrix(shop: str, site: str, expected: str) -> None:
    assert site_state(shop, site) == expected


def _access(state: str, preview: bool) -> SiteAccess:
    return SiteAccess(uuid4(), "techpc", "TechPC", "ACTIVE", "LIVE", state, preview)  # type: ignore[arg-type]


def test_ensure_open_reads_and_orders() -> None:
    ensure_open(_access("LIVE", False))
    ensure_open(_access("LIVE", False), for_order=True)
    ensure_open(_access("COMING_SOON", True))  # egasining ko'rib chiqishi — o'qish mumkin
    with pytest.raises(SiteNotAvailableError) as info:
        ensure_open(_access("COMING_SOON", True), for_order=True)  # buyurtma — yo'q
    assert info.value.details["state"] == "COMING_SOON"
    with pytest.raises(SiteNotAvailableError):
        ensure_open(_access("PAUSED", False))


def test_cache_keys_are_shop_prefixed_and_hashed() -> None:
    shop = uuid4()
    key = shop_key(shop, "storefront", "products:list", q="rtx 4060", sort="newest")
    assert key.startswith(f"cos:v1:shop:{shop}:storefront:products:list:") and "rtx" not in key
    assert key == shop_key(
        shop, "storefront", "products:list", sort="newest", q="rtx 4060"
    )  # tartib muhim emas
    assert key != shop_key(uuid4(), "storefront", "products:list", q="rtx 4060", sort="newest")
    assert shop_key(shop, "storefront", "site") == f"cos:v1:shop:{shop}:storefront:site"
    assert global_key("storefront", slug="techpc").startswith("cos:v1:global:storefront:")


def test_memory_cache_ttl_delete_and_counter() -> None:
    async def run() -> None:
        cache = MemoryCache()
        await cache.set("a", "1", 60)
        await cache.set("gone", "x", -1)
        assert await cache.get("a") == "1" and await cache.get("gone") is None
        await cache.delete("a", "missing")
        assert await cache.get("a") is None
        assert [await cache.incr("v") for _ in range(3)] == [1, 2, 3]

    asyncio.run(run())


def _cors_client() -> TestClient:
    app = FastAPI()

    @app.get("/api/v1/storefront/techpc/site")
    def site() -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/api/v1/shop/profile")
    def profile() -> dict[str, str]:
        return {"ok": "1"}

    app.add_middleware(StorefrontCorsMiddleware, origin_regex=r"^http://([a-z0-9-]+\.)?localhost:3002$")
    return TestClient(app)


def test_storefront_cors_only_for_site_origins_without_credentials() -> None:
    client = _cors_client()
    origin = {"Origin": "http://techpc.localhost:3002"}
    ok = client.get("/api/v1/storefront/techpc/site", headers=origin)
    assert ok.headers["access-control-allow-origin"] == "http://techpc.localhost:3002"
    assert "access-control-allow-credentials" not in ok.headers  # cookie'siz
    evil = client.get("/api/v1/storefront/techpc/site", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    pre = client.options(
        "/api/v1/storefront/techpc/site",
        headers={**origin, "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 200 and "Idempotency-Key" in pre.headers["access-control-allow-headers"]
    denied = client.options(
        "/api/v1/storefront/techpc/site",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.status_code == 400
    panel = client.get("/api/v1/shop/profile", headers=origin)
    assert "access-control-allow-origin" not in panel.headers  # panel API'si saytga ochilmaydi


def test_page_and_site_schema_validation() -> None:
    PageUpdate(
        title="Biz", body_md="**Qalin**, ro'yxat va [havola](https://t.me/x). Narx a < b.", is_published=True
    )
    for bad in (
        "<script>alert(1)</script>",
        "<img src=x onerror=1>",
        "[x](javascript:alert(1))",
        "<!-- x -->",
    ):
        with pytest.raises(ValidationError):
            PageUpdate(title="Biz", body_md=bad, is_published=True)
    site = SiteUpdate(telegram_username="@techpc_uz", contact_email="Info@TechPC.uz")
    assert site.telegram_username == "techpc_uz" and site.contact_email == "info@techpc.uz"
    for field, value in (
        ("telegram_username", "t.me/techpc"),
        ("instagram_username", "https://instagram.com/x"),
        ("contact_email", "yoq"),
        ("accent_color", "red"),
    ):
        with pytest.raises(ValidationError):
            SiteUpdate(**{field: value})


@pytest.mark.parametrize(
    ("status", "ready", "expected"),
    [
        ("DRAFT", False, "RECEIVED"),
        ("PENDING_CONFIRMATION", False, "RECEIVED"),
        ("CONFIRMED", False, "CONFIRMED"),
        ("PROCESSING", False, "PREPARING"),
        ("PROCESSING", True, "READY"),
        ("EXCEPTION", True, "PREPARING"),  # ichki muammo xaridorga "tayyorlanmoqda"
        ("COMPLETED", True, "COMPLETED"),
        ("CANCELLED", False, "CANCELLED"),
    ],
)
def test_public_order_status(status: str, ready: bool, expected: str) -> None:
    order = SimpleNamespace(status=status, ready_at=datetime.now(UTC) if ready else None)
    assert public_status(order) == expected  # type: ignore[arg-type]


def test_tracking_token_format_and_hash() -> None:
    assert (
        TRACKING_TOKEN.match("A" * 43)
        and not TRACKING_TOKEN.match("qisqa")
        and not TRACKING_TOKEN.match("a/b" * 10)
    )
    assert tracking_hash("abc") == tracking_hash("abc") and len(tracking_hash("abc")) == 64
