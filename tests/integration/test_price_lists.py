"""DEC-149: yetkazib beruvchi narx ro'yxati (1-qism) va kartochka qoralamasi (3-qism) — haqiqiy PostgreSQL,
AI — `FakeProvider` (`seller` navbati).

Qabul mezonlari: fayl fonda o'qiladi; kod bo'yicha aniq moslash AI'siz; qolganini AI nomzodlar ichidan
tanlaydi, nomzodsiz qator moslanmaydi; taklif narxi kurs, ustama va yaxlitlash bilan; ega tasdiqlamaguncha
narx o'zgarmaydi; qo'llash oddiy narx versiyasi; sotuvchi rol kira olmaydi; boshqa shop ko'rmaydi.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from app.platform.llm.providers.fake import FakeProvider, FakeText
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _hdr, _ok
from tests.integration.test_jobs_events import _drain_now

pytestmark = pytest.mark.integration

API = "/api/v1/shop/catalog/price-lists"


@pytest.fixture
def llm(world: World) -> Iterator[FakeProvider]:
    provider: FakeProvider = world.client.app.state.sales_ai.router.provider
    provider.script.clear()
    provider.requests.clear()
    yield provider
    provider.script.clear()


def _product(shop: Shop, title: str, amount: int, mpn: str | None = None) -> str:
    sku: dict[str, Any] = {
        "sku_code": f"C-{uuid4().hex[:8]}",
        "price": {"amount_minor": amount, "currency": "UZS"},
    }
    if mpn:
        sku["mpn"] = mpn
    body = {"category_code": "GPU", "title": title, "skus": [sku]}
    created = _ok(shop.world.client.post("/api/v1/shop/products", json=body, headers=_hdr(shop.owner)), 201)
    return str(created["skus"][0]["id"])


def _upload(world: World, token: str, data: bytes, filename: str = "prays.csv") -> str:
    response = world.client.post(
        f"/api/v1/shop/files?purpose=PRICE_LIST&filename={filename}",
        content=data,
        headers=_bearer(token, **_idem(), **{"Content-Type": "application/octet-stream"}),
    )
    return str(_ok(response, 201)["id"])


def _if(run: dict[str, Any]) -> dict[str, str]:
    return {"If-Match": f'"v{run["version"]}"'}


def test_price_list_read_match_review_and_apply(world: World, llm: FakeProvider) -> None:
    shop = Shop(world)
    shop.rate("12800")
    gpu = _product(shop, "MSI GeForce RTX 4060 Ventus 2X 8GB", 400_000_000, mpn="V516-012R")
    ram = _product(shop, "Kingston Fury Beast 16GB DDR5", 90_000_000)
    rows = "Model;Kod;Narx\nMSI RTX 4060 Ventus;V516012R;300\nKingston FURY Beast DDR5 16GB 5600;;65\n"
    file_id = _upload(world, shop.owner, (rows + "Qandaydir buyum;;10\n").encode())
    llm.push(
        FakeText(
            json.dumps(
                {
                    "items": [
                        {
                            "name": "MSI RTX 4060 Ventus",
                            "code": "V516012R",
                            "price": "300",
                            "currency": "USD",
                        },
                        {
                            "name": "Kingston FURY Beast DDR5 16GB 5600",
                            "code": None,
                            "price": "65",
                            "currency": "USD",
                        },
                        {"name": "Qandaydir buyum", "code": None, "price": "10", "currency": "USD"},
                        {"name": "", "price": "abc", "currency": "EUR"},  # buzuq — tashlanadi
                    ]
                }
            )
        ),
        FakeText(json.dumps({"matches": [{"line": 2, "pick": 1}]})),
    )
    created = _ok(
        world.client.post(
            API,
            json={"file_id": file_id, "supplier_name": "Dealer", "markup_percent": "10"},
            headers=_hdr(shop.owner),
        ),
        201,
    )
    assert created["status"] == "READING" and created["source_format"] == "CSV"
    _drain_now(world)
    run = _ok(world.client.get(f"{API}/{created['id']}", headers=_bearer(shop.owner)))
    assert run["status"] == "READY", run
    assert run["item_count"] == 3 and run["matched_count"] == 2
    first, second, third = run["items"]
    assert first["sku_id"] == gpu and first["match_method"] == "CODE"
    # 300 $ × 12 800 = 3 840 000 so'm, +10% = 4 224 000 so'm (1 000 so'mga yaxlitlangan)
    assert first["proposed_amount_minor"] == 422_400_000 and first["proposed_currency"] == "UZS"
    assert first["selected"] is True and first["changed"] is True
    assert second["sku_id"] == ram and second["match_method"] == "AI"
    assert third["sku_id"] is None and third["selected"] is False
    assert len(llm.requests) == 2  # o'qish + bitta moslash (uchinchi qatorning nomzodi yo'q)

    # Ega tasdiqlamaguncha narx o'zgarmaydi
    history = _ok(world.client.get(f"/api/v1/shop/skus/{gpu}/price-history", headers=_bearer(shop.owner)))
    assert history["items"][0]["amount_minor"] == 400_000_000

    run = _ok(
        world.client.patch(
            f"{API}/{run['id']}", json={"markup_percent": "0"}, headers=_bearer(shop.owner, **_if(run))
        )
    )
    assert run["items"][0]["proposed_amount_minor"] == 384_000_000
    ram_item = run["items"][1]
    run = _ok(
        world.client.patch(
            f"{API}/{run['id']}/items/{ram_item['id']}",
            json={"selected": False},
            headers=_bearer(shop.owner, **_if(run)),
        )
    )
    assert run["selected_count"] == 1

    applied = _ok(
        world.client.post(f"{API}/{run['id']}/apply", headers=_bearer(shop.owner, **_if(run), **_idem()))
    )
    assert applied["status"] == "APPLIED" and applied["applied_count"] == 1
    assert applied["items"][0]["result"] == "APPLIED" and applied["items"][1]["result"] is None
    history = _ok(world.client.get(f"/api/v1/shop/skus/{gpu}/price-history", headers=_bearer(shop.owner)))
    assert history["items"][0]["amount_minor"] == 384_000_000
    assert history["items"][0]["reason"] == "Narx ro'yxati: Dealer"
    ram_history = _ok(world.client.get(f"/api/v1/shop/skus/{ram}/price-history", headers=_bearer(shop.owner)))
    assert ram_history["items"][0]["amount_minor"] == 90_000_000  # tanlanmagan — o'zgarmadi


def test_price_list_ai_failure_access_and_isolation(world: World, llm: FakeProvider) -> None:
    shop, other = Shop(world), Shop(world)
    file_id = _upload(world, shop.owner, b"Model;Narx\nX;1\n")
    llm.push(FakeText("bu JSON emas"))
    created = _ok(world.client.post(API, json={"file_id": file_id}, headers=_hdr(shop.owner)), 201)
    _drain_now(world)
    run = _ok(world.client.get(f"{API}/{created['id']}", headers=_bearer(shop.owner)))
    assert run["status"] == "FAILED" and run["error_code"] == "NO_ITEMS"
    # Boshqa shop ko'rmaydi, sotuvchi kira olmaydi
    assert world.client.get(f"{API}/{created['id']}", headers=_bearer(other.owner)).status_code == 404
    sales, _ = shop.staff("SALES")
    assert world.client.get(API, headers=_bearer(sales)).status_code == 403
    # Boshqa shopning fayli bilan ro'yxat ochib bo'lmaydi
    response = world.client.post(API, json={"file_id": file_id}, headers=_hdr(other.owner))
    assert response.status_code == 422


def test_card_draft_from_photo_and_name(world: World, llm: FakeProvider) -> None:
    """DEC-149, 3-qism: kartochka qoralamasi — hech narsa saqlanmaydi, narx yo'q, toifa faqat ro'yxatdan."""
    from tests.images import png

    shop = Shop(world)
    response = world.client.post(
        "/api/v1/shop/files?purpose=PRODUCT_IMAGE&filename=gpu.png",
        content=png(),
        headers=_bearer(shop.owner, **_idem(), **{"Content-Type": "application/octet-stream"}),
    )
    file_id = _ok(response, 201)["id"]
    llm.push(
        FakeText(
            json.dumps(
                {
                    "title": "MSI GeForce RTX 4060 Ventus 2X 8GB",
                    "brand": "MSI",
                    "category_code": "GPU",
                    "mpn": "V516-012R",
                    "condition": "NEW",
                    "attributes": {"Xotira": "8 GB GDDR6", "Narx": 999, "x" * 60: "nomi qisqaradi"},
                    "description": "Kompakt videokarta.",
                    "price": "450",
                    "confidence": 0.9,
                }
            )
        ),
        FakeText(json.dumps({"title": "Noma'lum", "category_code": "NOT_A_CATEGORY"})),
    )
    draft = _ok(
        world.client.post(
            "/api/v1/shop/products/ai-draft", json={"file_id": file_id}, headers=_hdr(shop.owner)
        )
    )
    assert draft["title"] == "MSI GeForce RTX 4060 Ventus 2X 8GB" and draft["category_code"] == "GPU"
    assert draft["file_id"] == file_id and "price" not in draft
    assert draft["attributes"]["Xotira"] == "8 GB GDDR6" and len(draft["attributes"]) == 2
    assert llm.requests[-1].messages[0].parts[0].mime == "image/png"  # type: ignore[union-attr]
    by_name = _ok(
        world.client.post(
            "/api/v1/shop/products/ai-draft", json={"name": "rtx 4060"}, headers=_hdr(shop.owner)
        )
    )
    assert by_name["category_code"] is None  # ro'yxatda yo'q toifa olinmaydi
    products = _ok(world.client.get("/api/v1/shop/products", headers=_bearer(shop.owner)))
    assert products["items"] == []  # hech narsa saqlanmadi
    empty = world.client.post("/api/v1/shop/products/ai-draft", json={}, headers=_hdr(shop.owner))
    assert empty.status_code == 422
    sales, _ = shop.staff("SALES")
    assert (
        world.client.post(
            "/api/v1/shop/products/ai-draft", json={"name": "x"}, headers=_hdr(sales)
        ).status_code
        == 403
    )
