"""4-modul QA tuzatishlari — haqiqiy PostgreSQL: kesh va variantlar (F4), xato tafsiloti (F5), kalitli barmoq
izi (F2), qat'iy kirish (F8), sayt CORS'i (F1) va panelda qatorning filialdagi mavjudligi."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest

from app.shared.consent import STOREFRONT_CONSENT_VERSION
from tests.integration.helpers import World, _bearer, _code
from tests.integration.test_commerce import PHONE, _admin_sql, _hdr, _ok, _post
from tests.integration.test_storefront import Site

pytestmark = pytest.mark.integration


def _sku(code: str, variant: str, amount: int) -> dict[str, Any]:
    return {"sku_code": code, "variant_name": variant, "price": {"amount_minor": amount, "currency": "UZS"}}


def _two_variant_product(site: Site) -> tuple[str, str, str]:
    """Chiqarilgan mahsulot, ikki variant (A arzon, B qimmat): (product_id, sku_a, sku_b)."""
    code = uuid4().hex[:8]
    body = {
        "category_code": "RAM",
        "title": f"QA RAM {code}",
        "skus": [
            _sku(f"A-{code}", "16GB", 90_000_000),
            _sku(f"B-{code}", "32GB", 160_000_000),
        ],
    }
    product = _ok(site.world.client.post("/api/v1/shop/products", json=body, headers=_hdr(site.owner)), 201)
    _ok(_post(site.world, site.owner, f"/products/{product['id']}/publish"))
    skus = {s["sku_code"]: s["id"] for s in product["skus"]}
    return str(product["id"]), str(skus[f"A-{code}"]), str(skus[f"B-{code}"])


# ------------------------------ F4: arxivlangan variant va yangi narx darhol


def test_archived_variant_and_new_price_show_immediately_even_when_cached(world: World) -> None:
    site = Site(world)
    product_id, sku_a, sku_b = _two_variant_product(site)
    cached = _ok(site.get(f"/products/{product_id}"))  # endi keshda (60 s)
    assert {v["sku_id"] for v in cached["variants"]} == {sku_a, sku_b}

    _ok(_post(world, site.owner, f"/skus/{sku_b}/archive"))
    detail = _ok(site.get(f"/products/{product_id}"))
    assert [v["sku_id"] for v in detail["variants"]] == [sku_a]  # kesh 60 s, lekin variant darhol yo'q

    price = world.client.put(
        f"/api/v1/shop/skus/{sku_a}/price",
        json={"amount_minor": 85_000_000, "currency": "UZS"},
        headers=_hdr(site.owner, 1),
    )
    assert price.status_code == 200, price.text
    assert _ok(site.get(f"/products/{product_id}"))["variants"][0]["price_uzs_minor"] == 85_000_000

    # Chiqarilgan mahsulotning oxirgi faol variantini API arxivlatmaydi — holatni bazada o'zgartiramiz
    _admin_sql(world, "UPDATE catalog.skus SET status = 'ARCHIVED' WHERE id = $1", sku_a)
    assert site.get(f"/products/{product_id}").status_code == 404  # oxirgi variant ham ketdi


# ------------------------------ F5: sayt xatolarida ichki ID yo'q


def test_storefront_error_details_carry_no_internal_ids(world: World) -> None:
    site = Site(world)
    sku = site.shop.sku()
    site.shop.receive(sku, 2)
    _ok(_post(world, site.owner, f"/branches/{site.shop.branch2}/close"))
    closed = site.order({sku: 1}, branch_id=site.shop.branch2)
    assert closed.status_code == 409 and _code(closed) == "BRANCH_CLOSED"
    assert closed.json()["error"]["details"] == {}  # filial ID'si qaytarilmaydi (11 §6.3)

    product_id = _ok(site.get("/products"))["items"][0]["id"]
    product = _ok(world.client.get(f"/api/v1/shop/products/{product_id}", headers=_bearer(site.owner)))
    _ok(
        _post(world, site.owner, f"/products/{product_id}/hide", {"reason": "QA"}, version=product["version"])
    )
    hidden = site.order({sku: 1})
    assert hidden.status_code == 409 and _code(hidden) == "PRODUCT_NOT_AVAILABLE"
    assert hidden.json()["error"]["details"] == {"lines": [{"sku_id": sku}]}  # faqat xaridor yuborgani


# ------------------------------ F2 + F8: kalitli barmoq izi, qat'iy kirish


def test_order_request_hash_is_keyed_and_inputs_are_strict(world: World) -> None:
    site = Site(world)
    sku = site.shop.sku()
    site.shop.receive(sku, 3)
    key = f"sf-{uuid4()}"
    assert site.order({sku: 1}, key=key).status_code == 201
    rows = _admin_sql(
        world,
        "SELECT request_hash, response_body::text AS body FROM platform.idempotency_keys WHERE key = $1",
        key,
    )
    stored = rows[0]["request_hash"]
    assert stored.startswith("h1:") and not re.fullmatch(r"[0-9a-f]{64}", stored)  # oddiy SHA-256 emas
    assert PHONE[4:] not in rows[0]["body"]  # javobda faqat buyurtma ID'si

    for bad_qty in ("2", True):
        body = {
            "customer_name": "Jasur",
            "customer_phone": PHONE,
            "branch_id": site.shop.branch,
            "consent_version": STOREFRONT_CONSENT_VERSION,
            "lines": [{"sku_id": sku, "qty": bad_qty}],
        }
        refused = world.client.post(
            f"/api/v1/storefront/{site.slug}/order-requests",
            json=body,
            headers={"Idempotency-Key": f"sf-{uuid4()}"},
        )
        assert refused.status_code == 422, bad_qty
    newline = site.order({sku: 1}, customer_phone=f"{PHONE}\n")
    assert newline.status_code == 422 and _code(newline) == "VALIDATION_FAILED"


# ------------------------------ F1: haqiqiy sayt javobida cookie ruxsati yo'q


def test_live_storefront_and_panel_cors_headers(world: World) -> None:
    site = Site(world)
    origin = f"http://{site.slug}.localhost:3002"
    public = site.get("/site", Origin=origin)
    assert public.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in public.headers
    from_panel = site.get("/site", Origin="http://localhost:3000")
    assert "access-control-allow-origin" not in from_panel.headers
    assert "access-control-allow-credentials" not in from_panel.headers
    panel = world.client.get(
        "/api/v1/shop/profile", headers={**_bearer(site.owner), "Origin": "http://localhost:3000"}
    )
    assert panel.headers["access-control-allow-credentials"] == "true"


# ------------------------------ panel: qator filialda bormi (tasdiqdan oldin)


def _lines(order: dict[str, Any]) -> list[tuple[bool | None, int | None]]:
    return [(line["available_in_branch"], line["available_qty"]) for line in order["lines"]]


def test_order_lines_show_branch_availability_before_confirm(world: World) -> None:
    site = Site(world)
    shop = site.shop
    plenty, scarce, missing = shop.sku(), shop.sku(), shop.sku()
    shop.receive(plenty, 5)
    shop.receive(scarce, 1)
    shop.receive(missing, 4, branch=shop.branch2)  # boshqa filialda bor, tanlanganida yo'q

    draft = shop.order({plenty: 2, scarce: 2, missing: 1})
    by_sku = {line["sku_id"]: (line["available_in_branch"], line["available_qty"]) for line in draft["lines"]}
    assert by_sku == {plenty: (True, 5), scarce: (False, 1), missing: (False, 0)}

    other = _ok(_post(world, shop.owner, f"/orders/{draft['id']}/cancel", version=draft["version"]))
    assert all(flag is None for flag, _ in _lines(other))  # bekor qilingan — hisoblanmaydi

    confirmed = shop.step(shop.pending({plenty: 1}), "confirm")
    assert _lines(confirmed) == [(None, None)]  # tasdiqlangan — band bor, son kerak emas

    request = site.order({plenty: 1, scarce: 3})  # saytdan: band qilinmaydi
    assert request.status_code == 201
    order_id = _admin_sql(
        world,
        "SELECT id FROM commerce.orders WHERE shop_id = $1 AND source = 'STOREFRONT' "
        "ORDER BY number DESC LIMIT 1",
        shop.id,
    )[0]["id"]
    detail = shop.get(str(order_id))
    assert detail["status"] == "PENDING_CONFIRMATION"
    flags = {line["sku_id"]: line["available_in_branch"] for line in detail["lines"]}
    assert flags == {plenty: True, scarce: False}
