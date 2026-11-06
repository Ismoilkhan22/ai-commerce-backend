"""4-modul QA tuzatishlari (DB'siz): sayt CORS'i, mijoz IP'si, ko'rib chiqish tokeni, qat'iy kirish."""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_network
from uuid import uuid4

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.config.settings import Settings
from app.domains.commerce.orders.storefront_schemas import OrderRequestIn
from app.domains.storefront.api.public_routes import READ_LIMIT_PER_MINUTE, read_bucket
from app.domains.storefront.common import PreviewSigner
from app.domains.storefront.schemas import SiteUpdate
from app.main import create_app
from app.shared.client_ip import client_ip, resolve_client_ip
from app.shared.errors.base import ValidationError
from app.shared.phone import normalize_phone
from app.shared.types.manifest import DomainManifest

SITE_ORIGIN = "http://noutbukuz.localhost:3002"
PANEL_ORIGIN = "http://localhost:3000"
EVIL_ORIGIN = "http://noutbukuz.localhost.evil.com:3002"


def _app(settings: Settings) -> TestClient:
    storefront, shop = APIRouter(), APIRouter()

    @storefront.get("/ping")
    async def site_ping(request: Request) -> dict[str, str]:
        return {"ip": client_ip(request)}

    @storefront.get("/bucket")
    async def site_bucket(request: Request) -> dict[str, object]:
        key, limit = read_bucket(request, "noutbukuz")
        return {"key": key, "limit": limit}

    @shop.get("/ping")
    async def shop_ping() -> dict[str, str]:
        return {"ok": "yes"}

    manifest = DomainManifest(name="t", routers={"storefront": storefront, "shop": shop})
    return TestClient(create_app(settings, manifests=[manifest]))


# ------------------------------ F1/F6: sayt CORS'i cookie'siz


@pytest.mark.parametrize(
    ("origin", "reflected"), [(SITE_ORIGIN, True), (EVIL_ORIGIN, False), (PANEL_ORIGIN, False)]
)
def test_storefront_responses_never_allow_credentials(
    settings: Settings, origin: str, reflected: bool
) -> None:
    response = _app(settings).get("/api/v1/storefront/noutbukuz/ping", headers={"Origin": origin})
    assert response.status_code == 200
    assert "access-control-allow-credentials" not in response.headers
    assert (response.headers.get("access-control-allow-origin") == origin) is reflected
    vary = [part.strip().lower() for part in response.headers.get("vary", "").split(",")]
    assert vary.count("origin") == 1  # bir marta (F6)


def test_storefront_preflight_rejects_panel_origin_and_allows_site(settings: Settings) -> None:
    client = _app(settings)
    path = "/api/v1/storefront/noutbukuz/ping"
    preflight = {"Access-Control-Request-Method": "POST"}
    refused = client.options(path, headers={"Origin": PANEL_ORIGIN, **preflight})
    assert refused.status_code == 400 and "access-control-allow-origin" not in refused.headers
    allowed = client.options(path, headers={"Origin": SITE_ORIGIN, **preflight})
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == SITE_ORIGIN
    assert "access-control-allow-credentials" not in allowed.headers


def test_panel_paths_keep_credentialed_cors(settings: Settings) -> None:
    response = _app(settings).get("/api/v1/shop/ping", headers={"Origin": PANEL_ORIGIN})
    assert response.headers["access-control-allow-origin"] == PANEL_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    other = _app(settings).get("/api/v1/shop/ping", headers={"Origin": SITE_ORIGIN})
    assert "access-control-allow-origin" not in other.headers  # sayt manzili panel API'siga ruxsatsiz


# ------------------------------ F3: X-Forwarded-For faqat ishonchli proksidan

TRUSTED = [ip_network("127.0.0.1/32"), ip_network("10.0.0.0/8")]


def test_resolve_client_ip_trusts_forwarded_for_only_from_trusted_peer() -> None:
    assert resolve_client_ip("203.0.113.9", "1.2.3.4", TRUSTED) == "203.0.113.9"  # soxta XFF — e'tiborsiz
    assert resolve_client_ip("127.0.0.1", "1.2.3.4", TRUSTED) == "1.2.3.4"  # sayt serveri (SSR) yoki Nginx
    # Xaridor chapga nima yozsa ham — o'ngdan birinchi ishonchsiz manzil (Nginx qo'shgani)
    assert resolve_client_ip("127.0.0.1", "6.6.6.6, 1.2.3.4, 10.0.0.7", TRUSTED) == "1.2.3.4"
    assert resolve_client_ip("127.0.0.1", "10.0.0.5, 10.0.0.7", TRUSTED) == "10.0.0.5"  # hammasi ichki
    assert resolve_client_ip("127.0.0.1", "1.2.3.4, bad-value", TRUSTED) == "127.0.0.1"  # buzilgan zanjir
    assert resolve_client_ip("127.0.0.1", None, TRUSTED) == "127.0.0.1"
    assert resolve_client_ip(None, "1.2.3.4", TRUSTED) == "unknown"
    assert resolve_client_ip("2001:db8::1", "1.2.3.4", TRUSTED) == "2001:db8::1"


def test_rate_limit_ip_ignores_spoofed_forwarded_for(settings: Settings) -> None:
    app = _app(settings).app
    path = "/api/v1/storefront/noutbukuz/ping"
    untrusted = TestClient(app, client=("203.0.113.9", 50000))
    assert untrusted.get(path, headers={"X-Forwarded-For": "1.2.3.4"}).json()["ip"] == "203.0.113.9"
    proxy = TestClient(app, client=("127.0.0.1", 50000))  # lokal standart: o'z kompyuteri ishonchli
    assert proxy.get(path, headers={"X-Forwarded-For": "198.51.100.7"}).json()["ip"] == "198.51.100.7"


def test_client_ip_reads_every_forwarded_for_line(settings: Settings) -> None:  # QA M04 B1
    proxy = TestClient(_app(settings).app, client=("127.0.0.1", 50000))
    two_lines = [("X-Forwarded-For", "5.5.5.5"), ("X-Forwarded-For", "198.51.100.88")]
    assert proxy.get("/api/v1/storefront/noutbukuz/ping", headers=two_lines).json()["ip"] == "198.51.100.88"


def test_ssr_without_visitor_ip_gets_its_own_bucket(settings: Settings) -> None:  # QA M04 U1
    app = _app(settings).app
    path = "/api/v1/storefront/noutbukuz/bucket"
    proxy = TestClient(app, client=("127.0.0.1", 50000))
    outsider = TestClient(app, client=("203.0.113.9", 50000))
    ssr = proxy.get(path).json()
    assert ssr == {"key": "sf-ssr:noutbukuz", "limit": settings.storefront_ssr_read_limit_per_minute}
    forwarded = proxy.get(path, headers={"X-Forwarded-For": "198.51.100.7"})
    assert forwarded.json() == {"key": "sf-read:198.51.100.7:noutbukuz", "limit": READ_LIMIT_PER_MINUTE}
    visitor = outsider.get(path, headers={"X-Forwarded-For": "10.0.0.1"})
    assert visitor.json() == {"key": "sf-read:203.0.113.9:noutbukuz", "limit": READ_LIMIT_PER_MINUTE}


def test_trusted_proxies_setting_is_validated() -> None:
    with pytest.raises(ValueError, match="trusted_proxies"):
        Settings(app_env="test", trusted_proxies=["nginx.internal"])
    assert len(Settings(app_env="test", trusted_proxies=["10.0.0.0/8", "::1"]).proxy_networks()) == 2


# ------------------------------ F2: barmoq izi kaliti prod'da majburiy


def test_idempotency_hash_key_must_be_set_outside_dev() -> None:
    secrets = {
        "database_url": "postgresql+asyncpg://app_runtime:a-strong-password-1@db.internal/cos",
        "database_migrator_url": "postgresql+asyncpg://app_migrator:a-strong-password-2@db.internal/cos",
        "jwt_secret": "x" * 40,
        "app_public_url": "https://app.example.uz",
        "platform_app_public_url": "https://admin.example.uz",
        "public_files_url": "https://files.example.uz",
        "messaging_webhook_base_url": "https://api.example.uz",
        "pii_encryption_keys": "k1:" + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU=",
        "pii_active_key_id": "k1",
        "pii_hmac_key": "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDY=",
    }
    with pytest.raises(ValueError, match="idempotency_hash_key"):
        Settings(app_env="production", **secrets)  # type: ignore[arg-type]
    ok = Settings(app_env="production", idempotency_hash_key="z" * 40, **secrets)  # type: ignore[arg-type]
    assert ok.idempotency_hash_key.get_secret_value() == "z" * 40


# ------------------------------ F7: ko'rib chiqish tokeni har safar boshqa


def test_preview_tokens_are_unique_and_still_stateless() -> None:
    signer, shop_id = PreviewSigner("secret"), uuid4()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    first, _ = signer.issue(shop_id, now)
    second, _ = signer.issue(shop_id, now)  # o'sha soniyada
    assert first != second
    assert signer.valid_for(first, shop_id, now) and signer.valid_for(second, shop_id, now)
    shop_hex, exp, nonce, sig = first.split(".")
    assert not signer.valid_for(f"{shop_hex}.{exp}.{nonce}x.{sig}", shop_id, now)  # nonce imzoda
    assert not signer.valid_for(f"{shop_hex}.{exp}.{sig}", shop_id, now)  # eski 3 qismli shakl
    assert not signer.valid_for(first, uuid4(), now)


# ------------------------------ F8: qat'iy son va qator oxiri


def _request(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "lines": [{"sku_id": str(uuid4()), "qty": 1}],
        "customer_name": "Jasur",
        "customer_phone": "+998901234567",
        "branch_id": str(uuid4()),
        "consent_version": "v1",
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize("qty", ["2", True, 1.0])
def test_storefront_qty_must_be_a_real_integer(qty: object) -> None:
    with pytest.raises(PydanticValidationError):
        OrderRequestIn.model_validate(_request(lines=[{"sku_id": str(uuid4()), "qty": qty}]))
    assert OrderRequestIn.model_validate(_request()).lines[0].qty == 1


@pytest.mark.parametrize("raw", ["+998901234567\n", "901234567\n", "+998 90 123 45 67\r\n"])
def test_phone_with_trailing_newline_is_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        normalize_phone(raw, "customer_phone")
    assert normalize_phone("+998 90 123 45 67") == "+998901234567"


def test_site_email_newlines_never_survive() -> None:
    # Chetdagi bo'shliqni umumiy `Text` turi kesadi; ichidagi yangi qator — rad (fullmatch)
    assert SiteUpdate.model_validate({"contact_email": "info@techpc.uz\n"}).contact_email == "info@techpc.uz"
    with pytest.raises(PydanticValidationError):
        SiteUpdate.model_validate({"contact_email": "info@techpc.uz\nbcc@evil.uz"})


def test_page_body_strips_invisible_characters_but_keeps_lines() -> None:  # QA M04 U11
    from app.domains.storefront.schemas import PageUpdate

    page = PageUpdate(title="Biz", body_md="Salom\u202e dunyo\n\n- band\u200b bir\n- ikki", is_published=True)
    assert page.body_md == "Salom dunyo\n\n- band bir\n- ikki"
    with pytest.raises(PydanticValidationError):  # nol kenglik ichidagi "javascript:" ham ushlanadi
        PageUpdate(title="Biz", body_md="[x](java\u200bscript:alert(1))", is_published=True)
