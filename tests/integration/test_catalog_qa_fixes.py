"""2-modul QA tuzatishlari — HTTP orqali, haqiqiy PostgreSQL (progress/M02 §QA, M1–M6, L1–L17).

Har test QA hisobotidagi bitta topilmani takrorlaydi: avval 500 yoki noto'g'ri natija bergan so'rov endi
to'g'ri javob beradi.
"""

from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.shared.money import MAX_USD_MINOR
from tests import images
from tests.integration.helpers import World, _bearer, _code, _idem, _sql
from tests.integration.test_catalog import (
    _approve,
    _approved_spec,
    _create,
    _path,
    _platform_member,
    _post,
    _priced,
    _rate,
    _sku,
    _spec,
    _upload,
)

pytestmark = pytest.mark.integration


def _fields(response: Any) -> dict[str, dict[str, Any]]:
    assert response.status_code == 422, response.text
    return {f["field"]: f for f in response.json()["error"]["details"]["fields"]}


def _raw_post(world: World, token: str, path: str, raw: str) -> Any:
    return world.client.post(
        path,
        content=raw.encode(),
        headers=_bearer(token, **_idem(), **{"Content-Type": "application/json"}),
    )


def _cursor(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


# ------------------------------------------------------------------ M1, L1: NUL va NaN


def test_nul_and_non_finite_input_is_422_or_404_never_500(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    nul_title = _raw_post(
        world, owner, "/api/v1/shop/products", '{"category_code":"GPU","title":"QA \\u0000"}'
    )
    assert _fields(nul_title)["title"]["code"] == "invalid_format"
    nested = _raw_post(
        world,
        owner,
        "/api/v1/shop/products",
        '{"category_code":"GPU","title":"QA","skus":[{"sku_code":"A-1","variant_name":"x\\u0000",'
        '"attributes":{"k\\u0000":1,"n":NaN}}]}',
    )
    assert set(_fields(nested)) == {"skus[0].variant_name", "skus[0].attributes", "skus[0].attributes.n"}
    big = _post(
        world,
        owner,
        "/products",
        {"category_code": "GPU", "title": "QA", "skus": [_sku(attributes={"x": 2**60})]},
    )
    assert big.status_code == 422
    for path in ("/api/v1/shop/products", "/api/v1/shop/hardware-specs"):
        assert (
            _fields(c.get(path, params={"q": "\x00"}, headers=_bearer(owner)))["q"]["code"]
            == "invalid_format"
        )
    platform = c.get(
        "/api/v1/platform/hardware-specs", params={"q": "\x00"}, headers=_bearer(world.admin_token)
    )
    assert "q" in _fields(platform)
    category = _raw_post(
        world,
        world.admin_token,
        "/api/v1/platform/catalog/categories",
        '{"code":"QA_NUL","name_uz":"a\\u0000","name_ru":"b","name_en":"c"}',
    )
    assert "name_uz" in _fields(category)
    # Ochiq manzil, tokensiz: avval 500 edi
    public = c.get(f"/api/v1/public/files/shops/{s['shop']['id']}/product_image/x%00.png")
    assert (public.status_code, _code(public)) == (404, "NOT_FOUND")


# ------------------------------------------------------------------ M2: kurs vaqti


def test_exchange_rate_time_needs_timezone_and_sane_date(world: World) -> None:
    owner = world.create_shop()["owner_token"]
    for naive in ("2026-01-01T00:00:00", "2026-01-01"):
        response = _post(world, owner, "/exchange-rates", {"rate": "12500", "effective_at": naive})
        assert _fields(response)["effective_at"]["code"] == "invalid_format"
    ancient = _post(
        world, owner, "/exchange-rates", {"rate": "12500", "effective_at": "0001-01-01T00:00:00Z"}
    )
    assert _fields(ancient)["effective_at"]["code"] == "min_value"
    ok = _post(
        world, owner, "/exchange-rates", {"rate": "12500", "effective_at": "2026-01-01T09:00:00+05:00"}
    )
    assert ok.status_code == 201, ok.text


# ------------------------------------------------------------------ M3: variant va MPN


def test_auto_link_needs_variant_and_mpn_agreement(world: World) -> None:  # engineering/17 §5
    owner = world.create_shop()["owner_token"]
    editor = _platform_member(world)
    tag = uuid4().hex[:6].upper()
    model = f"RTX 99{tag}"
    eight = _approved_spec(
        world,
        editor,
        model_name=model,
        variant_key="8GB",
        mpn=f"QA-{tag}-8G",
        attributes={"memory_gb": 8},
    )
    product = _create(
        world,
        owner,
        title=f"MSI {model}",
        skus=[
            _sku(model_name=model, variant_name="16GB"),  # boshqa hajm
            _sku(model_name=model, mpn=f"QA-{tag}-16G"),  # MPN zid
            _sku(model_name=model),  # hajm aytilmagan — shubhali
            _sku(model_name=model, variant_name="8 GB GDDR6"),  # mos
        ],
    )
    links = [sku["spec_link"] for sku in product["skus"]]
    assert links[:3] == [None, None, None]
    assert (links[3]["spec_id"], links[3]["method"]) == (eight["id"], "AUTO_MODEL")


# ------------------------------------------------------------------ M4, L10: so'rov va hal qilish


def test_spec_request_and_resolve_check_sku_type_and_state(world: World) -> None:  # DEC-120
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    editor = _platform_member(world)
    tag = uuid4().hex[:6]
    product = _create(world, owner, skus=[_sku(model_name=f"Arc C{tag}")])
    sku = product["skus"][0]
    body = {"sku_id": sku["id"], "brand": "Intel", "model_name": f"Arc C{tag}"}
    wrong = _post(world, owner, "/hardware-spec-requests", {**body, "category": "CPU"})
    assert _fields(wrong)["category"]["params"] == {"expected": "GPU"}
    request = _post(world, owner, "/hardware-spec-requests", {**body, "category": "GPU"})
    assert request.status_code == 201, request.text

    # Mahsulot toifasi so'rovdan keyin almashdi — navbatda ko'rinadi va bog'lab bo'lmaydi
    moved = c.patch(
        f"/api/v1/shop/products/{product['id']}",
        json={"category_code": "CPU"},
        headers=_bearer(owner, **{"If-Match": f'"v{product["version"]}"'}),
    )
    assert moved.status_code == 200, moved.text
    queue = c.get(
        "/api/v1/platform/hardware-spec-requests", params={"status": "OPEN"}, headers=_bearer(editor)
    )
    item = next(i for i in queue.json()["items"] if i["id"] == request.json()["id"])
    assert (item["category"], item["sku_spec_category"]) == ("GPU", "CPU")
    gpu = _approved_spec(world, editor, brand="Intel", model_name=f"Arc C{tag} LE")
    mismatch = c.post(
        f"/api/v1/platform/hardware-spec-requests/{item['id']}/resolve",
        json={"spec_id": gpu["id"]},
        headers=_bearer(editor, **_idem()),
    )
    assert "spec_id" in _fields(mismatch)

    # Arxivdagi mahsulot SKU'si — so'rov ham, hal qilish ham o'tmaydi
    other = _create(world, owner, skus=[_sku(model_name=f"Arc D{tag}")])
    pending = _post(
        world,
        owner,
        "/hardware-spec-requests",
        {"sku_id": other["skus"][0]["id"], "brand": "Intel", "model_name": f"Arc D{tag}", "category": "GPU"},
    )
    assert pending.status_code == 201
    assert _post(world, owner, f"/products/{other['id']}/archive").status_code == 200
    archived = c.post(
        f"/api/v1/platform/hardware-spec-requests/{pending.json()['id']}/resolve",
        json={"spec_id": gpu["id"]},
        headers=_bearer(editor, **_idem()),
    )
    assert (archived.status_code, _code(archived)) == (409, "INVALID_STATE_TRANSITION")
    late = _post(
        world,
        owner,
        "/hardware-spec-requests",
        {"sku_id": other["skus"][0]["id"], "brand": "Intel", "model_name": "x", "category": "GPU"},
    )
    assert _code(late) == "INVALID_STATE_TRANSITION"


# ------------------------------------------------------------------ M5: toifa almashsa


def test_category_change_drops_links_of_another_type(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    editor = _platform_member(world)
    spec = _approved_spec(world, editor)
    product = _create(world, owner, skus=[_sku()])
    sku_id = product["skus"][0]["id"]
    linked = c.put(
        f"/api/v1/shop/skus/{sku_id}/spec-link", json={"spec_id": spec["id"]}, headers=_bearer(owner)
    )
    assert linked.status_code == 200 and linked.json()["method"] == "MANUAL"
    moved = c.patch(
        f"/api/v1/shop/products/{product['id']}",
        json={"category_code": "MONITOR"},
        headers=_bearer(owner, **{"If-Match": f'"v{product["version"]}"'}),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["spec_category"] is None and moved.json()["skus"][0]["spec_link"] is None
    audit = _sql(
        world.urls.admin,
        "SELECT reason FROM audit.audit_entries "
        "WHERE entity_id = $1 AND action = 'catalog.sku.spec_unlinked'",
        UUID(sku_id),
    )
    assert [row["reason"] for row in audit] == ["category_changed"]


# ------------------------------------------------------------------ M6: bitta fayl — bitta mahsulot


def test_file_backs_only_one_product_image(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    first, second = _priced(world, owner), _priced(world, owner)
    file = _upload(world, owner).json()
    assert _post(world, owner, f"/products/{first['id']}/media", {"file_id": file["id"]}).status_code == 200
    again = _post(world, owner, f"/products/{second['id']}/media", {"file_id": file["id"]})
    assert (again.status_code, _code(again)) == (409, "FILE_IN_USE")
    assert again.json()["error"]["details"]["product_id"] == first["id"]

    # O'chirilgan faylga havola ko'rsatilmaydi (404 beradigan manzil chiqmasin)
    other = _upload(world, owner).json()
    attached = _post(world, owner, f"/products/{second['id']}/media", {"file_id": other["id"]})
    assert attached.status_code == 200
    _sql(
        world.urls.admin,
        "UPDATE platform.stored_files SET status = 'DELETED' WHERE id = $1",
        UUID(other["id"]),
    )
    detail = c.get(f"/api/v1/shop/products/{second['id']}", headers=_bearer(owner)).json()
    assert detail["media"] == []
    listed = c.get("/api/v1/shop/products", headers=_bearer(owner)).json()["items"]
    assert next(i for i in listed if i["id"] == second["id"])["image_url"] is None


# ------------------------------------------------------------------ L2: buzilgan cursor


def test_tampered_cursor_is_422(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    sku_id = str(uuid4())
    shapes = [
        ("title", {"s": "title", "v": 5, "id": sku_id}),
        ("title", {"s": "title", "v": True, "id": sku_id}),
        ("title", {"s": "title", "v": ["a"], "id": sku_id}),
        ("title", {"s": "title", "v": "a\x00", "id": sku_id}),
        ("-updated_at", {"s": "-updated_at", "v": "2026-10-25T00:00:00+00:00", "id": 5}),
        ("-updated_at", {"s": "-updated_at", "v": "2026-10-25T00:00:00", "id": sku_id}),
        ("-updated_at", {"s": "-updated_at", "v": "0001-01-01T00:00:00+00:00", "id": sku_id}),
        ("-updated_at", {"s": "-updated_at", "v": {"x": 1}, "id": []}),
    ]
    for sort, raw in shapes:
        response = c.get(
            "/api/v1/shop/products", params={"sort": sort, "cursor": _cursor(raw)}, headers=_bearer(owner)
        )
        assert _fields(response)["cursor"]["code"] == "invalid_format", raw


# ------------------------------------------------------------------ L3: katta sonlar


def test_platform_lists_and_versions_bound_integers(world: World) -> None:
    c, admin = world.client, world.admin_token
    for path in ("/api/v1/platform/hardware-specs", "/api/v1/platform/hardware-spec-requests"):
        assert "offset" in _fields(c.get(path, params={"offset": 10**19}, headers=_bearer(admin)))
    spec = _spec(world, admin)
    for action in ("approve", "reject"):
        response = c.post(
            f"/api/v1/platform/hardware-specs/{spec['id']}/versions/2147483648/{action}",
            json={"note": "uzun izoh"} if action == "reject" else None,
            headers=_bearer(admin, **_idem()),
        )
        assert "version" in _fields(response)


# ------------------------------------------------------------------ L4: parallel ota toifa


def test_concurrent_parent_swap_never_500(world: World) -> None:  # 12 §3
    c, admin = world.client, world.admin_token
    for _ in range(3):
        tag = uuid4().hex[:5].upper()
        codes = [f"QA_C{tag}", f"QA_D{tag}"]
        for code in codes:
            created = c.post(
                "/api/v1/platform/catalog/categories",
                json={"code": code, "name_uz": code, "name_ru": code, "name_en": code},
                headers=_bearer(admin, **_idem()),
            )
            assert created.status_code == 201, created.text

        def swap(pair: tuple[str, str]) -> int:
            child, parent = pair
            return c.patch(
                f"/api/v1/platform/catalog/categories/{child}",
                json={"parent_code": parent},
                headers=_bearer(admin),
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(swap, [(codes[0], codes[1]), (codes[1], codes[0])]))
        assert statuses == [200, 422]  # biri o'tadi, ikkinchisi aylanani ko'radi — 500 emas


# ------------------------------------------------------------------ L5, L6: faqat bo'shliq


def test_whitespace_only_text_is_rejected(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner, admin = s["owner_token"], world.admin_token
    editor = _platform_member(world)
    spec = _spec(world, admin)
    for action, url in (
        ("reject", f"/api/v1/platform/hardware-specs/{spec['id']}/versions/1/reject"),
        ("retire", f"/api/v1/platform/hardware-specs/{spec['id']}/retire"),
    ):
        response = c.post(url, json={"note": "    "}, headers=_bearer(editor, **_idem()))
        assert _fields(response)["note"]["code"] == "min_length", action
    blank_brand = c.post(
        "/api/v1/platform/hardware-specs",
        json={
            "category": "GPU",
            "brand": "   ",
            "model_name": "QA blank",
            "source_url": "https://example.com/x",
        },
        headers=_bearer(admin, **_idem()),
    )
    assert "brand" in _fields(blank_brand)
    request = _post(
        world, owner, "/hardware-spec-requests", {"category": "GPU", "brand": " ", "model_name": " "}
    )
    assert set(_fields(request)) == {"brand", "model_name"}
    category = c.post(
        "/api/v1/platform/catalog/categories",
        json={"code": "QA_BLANK", "name_uz": "   ", "name_ru": " ", "name_en": "\t"},
        headers=_bearer(admin, **_idem()),
    )
    assert set(_fields(category)) == {"name_uz", "name_ru", "name_en"}
    renamed = c.patch(
        "/api/v1/platform/catalog/categories/GPU", json={"name_en": "   "}, headers=_bearer(admin)
    )
    assert "name_en" in _fields(renamed)
    request_ok = _post(
        world, owner, "/hardware-spec-requests", {"category": "GPU", "brand": "AMD", "model_name": "X"}
    )
    rejected = c.post(
        f"/api/v1/platform/hardware-spec-requests/{request_ok.json()['id']}/reject",
        json={"note": "   "},
        headers=_bearer(editor, **_idem()),
    )
    assert "note" in _fields(rejected)


# ------------------------------------------------------------------ L7: arxivdagi mahsulot SKU'si


def test_sku_of_archived_product_cannot_be_archived(world: World) -> None:  # BL-014
    owner = world.create_shop()["owner_token"]
    product = _create(world, owner, skus=[_sku(), _sku()])
    assert _post(world, owner, f"/products/{product['id']}/archive").status_code == 200
    response = _post(world, owner, f"/skus/{product['skus'][0]['id']}/archive")
    assert (response.status_code, _code(response)) == (409, "INVALID_STATE_TRANSITION")


# ------------------------------------------------------------------ L8: brend harfi va eskirgan model


def test_spec_uniqueness_ignores_brand_case_and_retired_specs(world: World) -> None:  # catalog.md §8
    c, admin = world.client, world.admin_token
    editor = _platform_member(world)
    model = f"QA Case {uuid4().hex[:6]}"
    first = _spec(world, admin, category="CASE", brand="QA Race", model_name=model, attributes={})
    duplicate = c.post(
        "/api/v1/platform/hardware-specs",
        json={
            "category": "CASE",
            "brand": "qa race",
            "model_name": model,
            "source_url": "https://example.com/case",
        },
        headers=_bearer(editor, **_idem()),
    )
    assert _fields(duplicate)["model_name"]["code"] == "not_unique"
    retired = c.post(
        f"/api/v1/platform/hardware-specs/{first['id']}/retire",
        json={"note": "eskirdi"},
        headers=_bearer(admin, **_idem()),
    )
    assert retired.status_code == 200
    recreated = _spec(world, editor, category="CASE", brand="qa race", model_name=model, attributes={})
    assert _approve(world, admin, recreated["id"]).status_code == 200  # eskirgani to'sqinlik qilmaydi

    # Parallel kiritish: baza indeksi ikkinchisini ushlaydi (avval ikkalasi o'tib, abadiy bloklanardi)
    race_model = f"QA Race {uuid4().hex[:6]}"

    def create(args: tuple[str, str]) -> int:
        token, brand = args
        return c.post(
            "/api/v1/platform/hardware-specs",
            json={
                "category": "CASE",
                "brand": brand,
                "model_name": race_model,
                "source_url": "https://e.x/c",
            },
            headers=_bearer(token, **_idem()),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, [(admin, "QA Race"), (editor, "qa race")])) == [201, 422]


# ------------------------------------------------------------------ L9: qo'lda uzilgan bog'lanish


def test_manual_unlink_is_not_undone_by_auto_link(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    editor = _platform_member(world)
    spec = _approved_spec(world, editor, model_name=f"RTX 77{uuid4().hex[:4]}")
    product = _create(world, owner, skus=[_sku(model_name=spec["model_name"])])
    sku = product["skus"][0]
    assert sku["spec_link"]["method"] == "AUTO_MODEL"
    assert c.delete(f"/api/v1/shop/skus/{sku['id']}/spec-link", headers=_bearer(owner)).status_code == 204
    rerun = _post(world, owner, "/skus/auto-link")
    assert rerun.status_code == 200
    blocked = c.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(owner)).json()["skus"][0]
    assert blocked["spec_autolink_blocked"] is True and blocked["spec_link"] is None
    patched = c.patch(
        f"/api/v1/shop/skus/{sku['id']}",
        json={"model_name": f" {spec['model_name']} "},
        headers=_bearer(owner, **{"If-Match": f'"v{blocked["version"]}"'}),
    )
    assert patched.status_code == 200
    detail = c.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(owner)).json()
    assert detail["skus"][0]["spec_link"] is None  # xodim qarori turibdi
    linked = c.put(
        f"/api/v1/shop/skus/{sku['id']}/spec-link", json={"spec_id": spec["id"]}, headers=_bearer(owner)
    )
    assert linked.status_code == 200 and linked.json()["method"] == "MANUAL"
    after = c.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(owner)).json()["skus"][0]
    assert after["spec_autolink_blocked"] is False  # xodim o'zi bog'ladi — taqiq olindi


# ------------------------------------------------------------------ L11, L12: yuklash


def test_upload_checks_token_before_body_and_rejects_fake_images(world: World) -> None:
    c = world.client
    owner = world.create_shop()["owner_token"]
    anonymous = c.post(
        "/api/v1/shop/files?purpose=PRODUCT_IMAGE",
        content=b"\x00" * (6 * 1024 * 1024),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert (anonymous.status_code, _code(anonymous)) == (401, "UNAUTHENTICATED")  # avval 413 edi
    for fake in (b"\xff\xd8\xff", b"RIFF\x00\x00\x00\x00WEBP", b"\x89PNG\r\n\x1a\n<html></html>"):
        response = _upload(world, owner, fake)
        assert (response.status_code, _code(response)) == (415, "UNSUPPORTED_MEDIA_TYPE")
    webp = _upload(world, owner, images.webp(), name="a.webp")
    assert webp.status_code == 201 and webp.json()["mime_type"] == "image/webp"


# ------------------------------------------------------------------ L13, L14, L15


def test_sku_patch_etag_comma_status_filter_and_location(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    product = _priced(world, owner)
    sku = product["skus"][0]
    patched = c.patch(
        f"/api/v1/shop/skus/{sku['id']}",
        json={"warranty_months": 24},
        headers=_bearer(owner, **{"If-Match": f'"v{sku["version"]}"'}),
    )
    new_version = patched.json()["skus"][0]["version"]
    assert patched.headers["ETag"] == f'"v{new_version}"'  # SKU versiyasi, mahsulotniki emas
    again = c.patch(
        f"/api/v1/shop/skus/{sku['id']}",
        json={"warranty_months": 12},
        headers=_bearer(owner, **{"If-Match": patched.headers["ETag"]}),
    )
    assert again.status_code == 200

    _post(world, owner, f"/products/{product['id']}/publish")
    draft = _create(world, owner)
    for params in ({"status": "PUBLISHED,DRAFT"}, {"status": ["PUBLISHED", "DRAFT"]}):
        ids = {
            i["id"]
            for i in c.get("/api/v1/shop/products", params=params, headers=_bearer(owner)).json()["items"]
        }
        assert {product["id"], draft["id"]} <= ids
    bad = c.get("/api/v1/shop/products", params={"status": "PUBLISHED,NOPE"}, headers=_bearer(owner))
    assert bad.status_code == 422

    created = c.post(
        "/api/v1/shop/products",
        json={"category_code": "GPU", "title": "QA Location"},
        headers=_bearer(owner, **_idem()),
    )
    assert created.headers["Location"] == f"/api/v1/shop/products/{created.json()['id']}"
    file = _upload(world, owner)
    assert file.headers["Location"] == f"/api/v1/shop/files/{file.json()['id']}"
    spec = c.post(
        "/api/v1/platform/hardware-specs",
        json={
            "category": "CASE",
            "brand": "QA",
            "model_name": f"QA Loc {uuid4().hex[:6]}",
            "source_url": "https://e.x",
        },
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert spec.headers["Location"] == f"/api/v1/platform/hardware-specs/{spec.json()['id']}"
    code = f"QA_L{uuid4().hex[:5].upper()}"
    category = c.post(
        "/api/v1/platform/catalog/categories",
        json={"code": code, "name_uz": "a", "name_ru": "b", "name_en": "c"},
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert category.headers["Location"] == f"/api/v1/platform/catalog/categories/{code}"
    assert c.get(category.headers["Location"], headers=_bearer(world.admin_token)).json()["code"] == code


def test_rate_and_spec_request_have_location_and_single_get(world: World) -> None:  # QA 2-tur, B1
    c, a, b = world.client, world.create_shop(), world.create_shop()
    owner = a["owner_token"]
    rate = _post(world, owner, "/exchange-rates", {"rate": "12850"})
    assert rate.status_code == 201
    assert rate.headers["Location"] == f"/api/v1/shop/exchange-rates/{rate.json()['id']}"
    assert c.get(rate.headers["Location"], headers=_bearer(owner)).json()["rate"] == rate.json()["rate"]
    request = _post(
        world, owner, "/hardware-spec-requests", {"category": "GPU", "brand": "QA", "model_name": "QA x"}
    )
    assert request.status_code == 201
    assert request.headers["Location"] == f"/api/v1/shop/hardware-spec-requests/{request.json()['id']}"
    assert c.get(request.headers["Location"], headers=_bearer(owner)).json()["id"] == request.json()["id"]
    # Boshqa shop — 404 (RLS va shop filtri)
    for path in (rate.headers["Location"], request.headers["Location"]):
        assert c.get(path, headers=_bearer(b["owner_token"])).status_code == 404


# ------------------------------------------------------------------ L16, L17: chegaralar


def test_bounds_report_allowed_values_and_usd_is_capped(world: World) -> None:
    owner = world.create_shop()["owner_token"]
    zero = _post(
        world,
        owner,
        "/products",
        {"category_code": "GPU", "title": "QA", "skus": [_sku(price={"amount_minor": 0, "currency": "UZS"})]},
    )
    assert _fields(zero)["skus[0].price.amount_minor"]["params"] == {"min": 1}
    rate = _post(world, owner, "/exchange-rates", {"rate": "0"})
    assert _fields(rate)["rate"]["params"] == {"min": "0.000001"}
    huge = _post(
        world,
        owner,
        "/products",
        {
            "category_code": "GPU",
            "title": "QA",
            "skus": [_sku(price={"amount_minor": 10**15, "currency": "USD"})],
        },
    )
    assert _fields(huge)["skus[0].price.amount_minor"] == {
        "field": "skus[0].price.amount_minor",
        "code": "max_value",
        "params": {"max": MAX_USD_MINOR},
    }
    _rate(world, owner, "1000000")
    capped = _priced(world, owner, amount=MAX_USD_MINOR, currency="USD")
    assert capped["skus"][0]["price"]["uzs_amount_minor"] <= 2**53 - 1


# ------------------------------------------------------------------ kuzatuvlar: SKU kodi, fayl nomi


def test_sku_code_unique_ignoring_case_and_names_drop_bidi(world: World) -> None:  # BL-011
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    code = f"QA-CASE-{uuid4().hex[:4].upper()}"
    product = _create(world, owner, skus=[_sku(code)])
    lower = _post(world, owner, f"/products/{product['id']}/skus", _sku(code.lower()))
    assert _fields(lower)["sku_code"]["code"] == "not_unique"
    same_request = _post(
        world,
        owner,
        "/products",
        {"category_code": "GPU", "title": "QA", "skus": [_sku("ab-1"), _sku("AB-1")]},
    )
    assert _fields(same_request)["skus[1].sku_code"]["code"] == "not_unique"
    sku = product["skus"][0]
    own_case = c.patch(
        f"/api/v1/shop/skus/{sku['id']}",
        json={"sku_code": code.lower()},
        headers=_bearer(owner, **{"If-Match": f'"v{sku["version"]}"'}),
    )
    assert own_case.status_code == 200  # o'z kodining harfini o'zgartirish mumkin

    named = _upload(world, owner, name="rasm‮gnp.exe")
    assert named.json()["original_name"] == "rasmgnp.exe"
    assert c.get(_path(named.json()["url"])).status_code == 200
