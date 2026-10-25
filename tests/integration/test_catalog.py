"""2-modul — katalog: mahsulot va FSM-02, narx va kurs, rasmlar, texnik kutubxona, izolyatsiya (DEC-133).

Haqiqiy PostgreSQL, HTTP orqali.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests import images
from tests.integration.helpers import PASSWORD, World, _bearer, _code, _idem, _phone, _sql

pytestmark = pytest.mark.integration

PNG = images.png()
JPEG = images.jpeg()
PLATFORM = {"audience": "platform"}


# ------------------------------------------------------------------ yordamchilar


def _sku(code: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"sku_code": code or f"SKU-{uuid4().hex[:8]}", **extra}


def _create(world: World, token: str, **body: Any) -> dict[str, Any]:
    payload = {"category_code": "GPU", "title": "MSI GeForce RTX 4060 Ventus 2X", "brand": "MSI", **body}
    response = world.client.post("/api/v1/shop/products", json=payload, headers=_bearer(token, **_idem()))
    assert response.status_code == 201, response.text
    return dict(response.json())


def _priced(
    world: World, token: str, amount: int = 480_000_000, currency: str = "UZS", **sku: Any
) -> dict[str, Any]:
    return _create(world, token, skus=[_sku(price={"amount_minor": amount, "currency": currency}, **sku)])


def _post(world: World, token: str, path: str, body: Any = None) -> Any:
    return world.client.post(f"/api/v1/shop{path}", json=body, headers=_bearer(token, **_idem()))


def _rate(world: World, token: str, rate: str) -> dict[str, Any]:
    response = _post(world, token, "/exchange-rates", {"rate": rate})
    assert response.status_code == 201, response.text
    return dict(response.json())


def _upload(
    world: World, token: str, data: bytes = PNG, purpose: str = "PRODUCT_IMAGE", name: str = "a.png"
) -> Any:
    return world.client.post(
        f"/api/v1/shop/files?purpose={purpose}&filename={name}",
        content=data,
        headers=_bearer(token, **_idem(), **{"Content-Type": "application/octet-stream"}),
    )


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def _platform_member(world: World, role: str = "SPEC_EDITOR") -> str:
    """Ikkinchi platforma xodimi (ikki ko'z qoidasi uchun) — taklif va qabul orqali."""
    c = world.client
    invited = c.post(
        "/api/v1/platform/staff/invites",
        json={"phone": _phone(), "full_name": "Bekzod Kutubxona", "role": role},
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["invite"]["url"].rsplit("/", 1)[1]
    accepted = c.post(f"/api/v1/auth/platform-invites/{token}/accept", json={"password": PASSWORD})
    assert accepted.status_code == 200, accepted.text
    return str(accepted.json()["access_token"])


def _spec(world: World, token: str, **body: Any) -> dict[str, Any]:
    payload = {
        "category": "GPU",
        "brand": "MSI",
        "model_name": f"GeForce RTX {uuid4().hex[:6]}",
        "attributes": {"length_mm": 199, "board_power_w": 115},
        "source_url": "https://www.msi.com/Graphics-Card/GeForce-RTX-4060-VENTUS-2X",
        **body,
    }
    response = world.client.post(
        "/api/v1/platform/hardware-specs", json=payload, headers=_bearer(token, **_idem())
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _approve(world: World, token: str, spec_id: str, version: int = 1) -> Any:
    return world.client.post(
        f"/api/v1/platform/hardware-specs/{spec_id}/versions/{version}/approve",
        headers=_bearer(token, **_idem()),
    )


def _approved_spec(world: World, editor: str, **body: Any) -> dict[str, Any]:
    spec = _spec(world, world.admin_token, **body)
    response = _approve(world, editor, spec["id"])
    assert response.status_code == 200, response.text
    return dict(response.json())


# ------------------------------------------------------------------ mahsulot va FSM-02


def test_product_lifecycle_publish_hide_republish_archive(world: World) -> None:  # UAT-M04, FSM-02
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    product = _priced(world, owner, mpn="V516-012R", warranty_months=36)
    assert product["status"] == "DRAFT" and product["spec_category"] == "GPU"
    [sku] = product["skus"]
    assert sku["price"]["amount_minor"] == 480_000_000 and sku["price"]["uzs_amount_minor"] == 480_000_000
    assert sku["price"]["version"] == 1 and sku["spec_link"] is None

    published = _post(world, owner, f"/products/{product['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED" and published.json()["published_at"]
    hidden = _post(world, owner, f"/products/{product['id']}/hide", {"reason": "yangi partiya kutilmoqda"})
    assert hidden.json()["status"] == "HIDDEN"
    again = _post(world, owner, f"/products/{product['id']}/publish")
    assert again.json()["status"] == "PUBLISHED"
    archived = _post(world, owner, f"/products/{product['id']}/archive")
    assert archived.json()["status"] == "ARCHIVED" and archived.json()["archived_at"]

    log = _sql(
        world.urls.admin,
        "SELECT command, from_status, to_status FROM platform.transition_log "
        "WHERE entity_id = $1 ORDER BY occurred_at",
        UUID(product["id"]),
    )
    assert [(r["command"], r["from_status"], r["to_status"]) for r in log] == [
        ("PUBLISH", "DRAFT", "PUBLISHED"),
        ("HIDE", "PUBLISHED", "HIDDEN"),
        ("REPUBLISH", "HIDDEN", "PUBLISHED"),
        ("ARCHIVE", "PUBLISHED", "ARCHIVED"),
    ]
    actions = {
        r["action"]
        for r in _sql(
            world.urls.admin,
            "SELECT action FROM audit.audit_entries WHERE entity_id = $1",
            UUID(product["id"]),
        )
    }
    assert {"catalog.product.created", "catalog.product.publish", "catalog.product.archive"} <= actions

    # Arxivdagi mahsulot o'zgartirilmaydi va qayta chiqmaydi (BL-014)
    patch = c.patch(
        f"/api/v1/shop/products/{product['id']}",
        json={"title": "Yangi nom"},
        headers=_bearer(owner, **{"If-Match": f'"v{archived.json()["version"]}"'}),
    )
    assert (patch.status_code, _code(patch)) == (409, "INVALID_STATE_TRANSITION")
    assert _code(_post(world, owner, f"/products/{product['id']}/publish")) == "INVALID_STATE_TRANSITION"


def test_publish_requires_sku_price_and_rate_for_dollars(world: World) -> None:  # BL-012
    s = world.create_shop()
    owner = s["owner_token"]
    bare = _create(world, owner)
    response = _post(world, owner, f"/products/{bare['id']}/publish")
    assert (response.status_code, _code(response)) == (422, "VALIDATION_FAILED")
    assert response.json()["error"]["details"]["fields"] == [
        {"field": "skus", "code": "required", "params": {}}
    ]

    added = _post(world, owner, f"/products/{bare['id']}/skus", _sku())
    assert added.status_code == 201, added.text
    response = _post(world, owner, f"/products/{bare['id']}/publish")
    assert response.json()["error"]["details"]["fields"][0]["field"] == "price"

    sku = added.json()["skus"][0]
    price = world.client.put(
        f"/api/v1/shop/skus/{sku['id']}/price",
        json={"amount_minor": 30_000, "currency": "USD"},
        headers=_bearer(owner, **_idem(), **{"If-Match": '"v0"'}),
    )
    assert price.status_code == 200, price.text
    assert price.json()["uzs_amount_minor"] is None  # kurs yo'q — so'mda ko'rsatib bo'lmaydi
    response = _post(world, owner, f"/products/{bare['id']}/publish")
    assert response.json()["error"]["details"]["fields"][0]["field"] == "exchange_rate"

    _rate(world, owner, "12800")
    assert _post(world, owner, f"/products/{bare['id']}/publish").json()["status"] == "PUBLISHED"


def test_roles_limit_catalog_actions(world: World) -> None:  # business/04, DEC-131, DEC-133
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    _, _, manager = world.invite(owner, "MANAGER")
    _, _, sales = world.invite(owner, "SALES")
    _, _, warehouse = world.invite(owner, "WAREHOUSE")

    product = _priced(world, manager)  # menejer qo'shadi va chiqaradi
    assert _post(world, manager, f"/products/{product['id']}/publish").json()["status"] == "PUBLISHED"
    archive = _post(world, manager, f"/products/{product['id']}/archive")
    assert (archive.status_code, _code(archive)) == (403, "FORBIDDEN")  # arxivlash — faqat ega

    for token in (sales, warehouse):  # operator va omborchi faqat ko'radi
        assert c.get("/api/v1/shop/products", headers=_bearer(token)).status_code == 200
        assert c.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(token)).status_code == 200
        assert _post(world, token, "/products", {"category_code": "GPU", "title": "X"}).status_code == 403
        price = c.put(
            f"/api/v1/shop/skus/{product['skus'][0]['id']}/price",
            json={"amount_minor": 1, "currency": "UZS"},
            headers=_bearer(token, **_idem(), **{"If-Match": '"v1"'}),
        )
        assert price.status_code == 403
        assert _post(world, token, "/exchange-rates", {"rate": "12800"}).status_code == 403
        assert _post(world, token, f"/products/{product['id']}/hide").status_code == 403

    assert _post(world, owner, f"/products/{product['id']}/archive").json()["status"] == "ARCHIVED"


def test_sku_code_unique_within_shop_only(world: World) -> None:  # BL-011
    a, b = world.create_shop(), world.create_shop()
    _create(world, a["owner_token"], skus=[_sku("MSI-4060-V2X-N")])
    response = _post(
        world,
        a["owner_token"],
        "/products",
        {"category_code": "GPU", "title": "Ikkinchi", "skus": [_sku("MSI-4060-V2X-N")]},
    )
    assert (response.status_code, _code(response)) == (422, "VALIDATION_FAILED")
    assert response.json()["error"]["details"]["fields"] == [
        {"field": "skus[0].sku_code", "code": "not_unique", "params": {}}
    ]
    _create(world, b["owner_token"], skus=[_sku("MSI-4060-V2X-N")])  # boshqa shopda — mumkin


def test_create_product_is_idempotent(world: World) -> None:  # K-06
    c, s = world.client, world.create_shop()
    headers = _bearer(s["owner_token"], **_idem())
    body = {"category_code": "CPU", "title": "AMD Ryzen 5 7600", "brand": "AMD", "skus": [_sku()]}
    first = c.post("/api/v1/shop/products", json=body, headers=headers)
    second = c.post("/api/v1/shop/products", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    listed = c.get(
        "/api/v1/shop/products", params={"q": "Ryzen 5 7600"}, headers=_bearer(s["owner_token"])
    ).json()
    assert len(listed["items"]) == 1
    other = c.post("/api/v1/shop/products", json={**body, "title": "Boshqa"}, headers=headers)
    assert (other.status_code, _code(other)) == (409, "IDEMPOTENCY_KEY_REUSED")


def test_if_match_conflicts_for_product_and_price(world: World) -> None:  # 12 §4
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    product = _priced(world, owner)
    sku = product["skus"][0]
    ok = c.patch(
        f"/api/v1/shop/products/{product['id']}",
        json={"description": "8 GB GDDR6"},
        headers=_bearer(owner, **{"If-Match": f'"v{product["version"]}"'}),
    )
    assert ok.status_code == 200 and ok.headers["ETag"] == f'"v{product["version"] + 1}"'
    stale = c.patch(
        f"/api/v1/shop/products/{product['id']}",
        json={"title": "Eski sahifadan"},
        headers=_bearer(owner, **{"If-Match": f'"v{product["version"]}"'}),
    )
    assert (stale.status_code, _code(stale)) == (409, "VERSION_CONFLICT")

    def put(amount: int, version: int) -> Any:
        return c.put(
            f"/api/v1/shop/skus/{sku['id']}/price",
            json={"amount_minor": amount, "currency": "UZS", "reason": "yangi partiya"},
            headers=_bearer(owner, **_idem(), **{"If-Match": f'"v{version}"'}),
        )

    assert _code(put(490_000_000, 0)) == "VERSION_CONFLICT"  # narx bor — "v0" endi eskirgan
    changed = put(490_000_000, 1)
    assert changed.status_code == 200 and changed.json()["version"] == 2
    assert _code(put(500_000_000, 1)) == "VERSION_CONFLICT"
    history = c.get(f"/api/v1/shop/skus/{sku['id']}/price-history", headers=_bearer(owner)).json()["items"]
    assert [h["amount_minor"] for h in history] == [490_000_000, 480_000_000]
    assert history[0]["reason"] == "yangi partiya"
    same = put(490_000_000, 2)  # o'sha narx — yangi versiya yozilmaydi
    assert same.json()["price_version_id"] == changed.json()["price_version_id"]


def test_price_and_rate_history_cannot_be_rewritten(world: World) -> None:  # BL-016
    s = world.create_shop()
    owner = s["owner_token"]
    _priced(world, owner)
    _rate(world, owner, "12800")
    shop_id = s["shop"]["id"]

    async def attempt(statement: str) -> type[BaseException] | None:
        conn = await asyncpg.connect(world.urls.runtime.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", shop_id)
                await conn.execute(statement)
        except asyncpg.PostgresError as exc:
            return type(exc)
        finally:
            await conn.close()
        return None

    for statement in (
        "UPDATE catalog.price_versions SET amount_minor = 1",
        "DELETE FROM catalog.price_versions",
        "UPDATE catalog.exchange_rates SET rate = 1",
        "DELETE FROM catalog.exchange_rates",
    ):
        assert asyncio.run(attempt(statement)) is asyncpg.InsufficientPrivilegeError, statement


def test_dollar_price_shown_in_sum_without_rounding(world: World) -> None:  # UAT-M05, DEC-133
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    product = _priced(world, owner, amount=30_000, currency="USD")  # 300 dollar
    sku_id = product["skus"][0]["id"]

    def uzs() -> int:
        detail = c.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(owner)).json()
        return int(detail["skus"][0]["price"]["uzs_amount_minor"])

    _rate(world, owner, "12800")
    assert uzs() == 384_000_000  # 3 840 000 so'm
    _rate(world, owner, "12835")
    assert uzs() == 385_050_000  # 3 850 500 so'm — yaxlitlanmaydi
    _rate(world, owner, "12800.123456")
    assert uzs() == 384_003_700  # kasr kursdan chiqqan tiyinlar — eng yaqin so'mgacha
    listed = c.get("/api/v1/shop/products", headers=_bearer(owner)).json()["items"]
    assert next(i for i in listed if i["id"] == product["id"])["price_from_uzs_minor"] == 384_003_700
    assert (
        c.get(f"/api/v1/shop/skus/{sku_id}/price-history", headers=_bearer(owner)).json()["items"][0][
            "currency"
        ]
        == "USD"
    )


def test_exchange_rate_staleness_and_future_dates(world: World) -> None:  # catalog.md §7
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    rate = _rate(world, owner, "12750.50")
    assert rate["rate"] == "12750.500000" and rate["is_stale"] is False
    _sql(
        world.urls.admin,  # superuser: tarixni faqat test uchun orqaga suramiz
        "UPDATE catalog.exchange_rates SET effective_at = now() - interval '4 days' WHERE id = $1",
        UUID(rate["id"]),
    )
    listed = c.get("/api/v1/shop/exchange-rates", headers=_bearer(owner)).json()
    assert listed["current"]["is_stale"] is True and listed["max_age_hours"] == 72
    _rate(world, owner, "12800")
    assert c.get("/api/v1/shop/exchange-rates", headers=_bearer(owner)).json()["current"]["is_stale"] is False
    future = _post(world, owner, "/exchange-rates", {"rate": "12900", "effective_at": "2099-01-01T00:00:00Z"})
    assert (future.status_code, _code(future)) == (422, "VALIDATION_FAILED")


def test_last_active_sku_of_listed_product_cannot_be_archived(world: World) -> None:
    s = world.create_shop()
    owner = s["owner_token"]
    product = _priced(world, owner)
    _post(world, owner, f"/products/{product['id']}/publish")
    response = _post(world, owner, f"/skus/{product['skus'][0]['id']}/archive")
    assert (response.status_code, _code(response)) == (409, "INVALID_STATE_TRANSITION")


def test_list_uses_cursor_filters_and_counts(world: World) -> None:  # 11 §4.1
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    ids = [_create(world, owner, title=f"Mahsulot {i}", skus=[_sku(f"CODE-{i}")])["id"] for i in range(3)]
    first = c.get("/api/v1/shop/products", params={"limit": 2}, headers=_bearer(owner)).json()
    assert first["has_more"] is True and len(first["items"]) == 2
    second = c.get(
        "/api/v1/shop/products", params={"limit": 2, "cursor": first["next_cursor"]}, headers=_bearer(owner)
    ).json()
    assert second["has_more"] is False and second["next_cursor"] is None
    assert {i["id"] for i in first["items"] + second["items"]} == set(ids)
    by_code = c.get("/api/v1/shop/products", params={"q": "code-1"}, headers=_bearer(owner)).json()["items"]
    assert [i["id"] for i in by_code] == [ids[1]]
    titles = c.get("/api/v1/shop/products", params={"sort": "title"}, headers=_bearer(owner)).json()["items"]
    assert [i["title"] for i in titles] == ["Mahsulot 0", "Mahsulot 1", "Mahsulot 2"]
    bad = c.get("/api/v1/shop/products", params={"cursor": "not-a-cursor"}, headers=_bearer(owner))
    assert (bad.status_code, _code(bad)) == (422, "VALIDATION_FAILED")
    counts = c.get("/api/v1/shop/products/counts", headers=_bearer(owner)).json()
    assert counts["by_status"]["DRAFT"] == 3 and counts["total"] == 3
    drafts = c.get("/api/v1/shop/products", params={"status": "PUBLISHED"}, headers=_bearer(owner)).json()
    assert drafts["items"] == []


# ------------------------------------------------------------------ fayllar va rasmlar


def test_upload_detects_type_from_content_and_limits_size(world: World) -> None:  # S0-08
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    uploaded = _upload(world, owner, JPEG, name="rtx.jpg")
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["mime_type"] == "image/jpeg" and body["is_public"] is True and body["url_expires_at"] is None
    assert body["original_name"] == "rtx.jpg"
    served = c.get(_path(body["url"]))
    assert served.status_code == 200 and served.content == JPEG
    assert served.headers["content-type"] == "image/jpeg" and "immutable" in served.headers["cache-control"]
    assert served.headers["x-content-type-options"] == "nosniff"

    fake = _upload(world, owner, b"<html><script>alert(1)</script></html>", name="photo.jpg")
    assert (fake.status_code, _code(fake)) == (415, "UNSUPPORTED_MEDIA_TYPE")  # nomi .jpg, ichi HTML
    big = _upload(world, owner, PNG + b"\x00" * (5 * 1024 * 1024))
    assert (big.status_code, _code(big)) == (413, "PAYLOAD_TOO_LARGE")
    evidence = _upload(world, owner, purpose="STOCK_EVIDENCE")  # 3-modul: tuzatish dalili — yopiq fayl
    assert evidence.status_code == 201 and evidence.json()["is_public"] is False
    _, _, sales = world.invite(owner, "SALES")
    assert _upload(world, sales).status_code == 403
    assert _upload(world, sales, purpose="STOCK_EVIDENCE").status_code == 403  # operatorda tuzatish yo'q
    assert c.get("/api/v1/public/files/shops/not-a-uuid/x/y").status_code == 404


def test_private_file_needs_valid_signature(world: World) -> None:  # catalog.md §12
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    body = _upload(world, owner).json()
    _sql(
        world.urls.admin, "UPDATE platform.stored_files SET is_public = false WHERE id = $1", UUID(body["id"])
    )
    plain = _path(body["url"])
    assert c.get(plain).status_code == 404  # imzosiz — yo'q

    signed = c.get(f"/api/v1/shop/files/{body['id']}", headers=_bearer(owner)).json()
    assert signed["is_public"] is False and signed["url_expires_at"]
    ok = c.get(_path(signed["url"]))
    assert ok.status_code == 200 and ok.headers["cache-control"] == "private, no-store"
    tampered = _path(signed["url"])[:-4] + "0000"
    assert c.get(tampered).status_code == 404
    assert (
        c.get(f"{plain}?exp=1&sig={signed['url'].rsplit('sig=', 1)[1]}").status_code == 404
    )  # muddati o'tgan


def test_media_attach_reorder_and_remove(world: World) -> None:
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    product = _priced(world, owner)
    files = [_upload(world, owner).json() for _ in range(2)]
    for f in files:
        attached = _post(world, owner, f"/products/{product['id']}/media", {"file_id": f["id"]})
        assert attached.status_code == 200, attached.text
    media = attached.json()["media"]
    assert [m["file_id"] for m in media] == [files[0]["id"], files[1]["id"]]
    reordered = c.put(
        f"/api/v1/shop/products/{product['id']}/media/order",
        json={"media_ids": [media[1]["id"], media[0]["id"]]},
        headers=_bearer(owner),
    ).json()["media"]
    assert [m["file_id"] for m in reordered] == [files[1]["id"], files[0]["id"]]
    listed = c.get("/api/v1/shop/products", headers=_bearer(owner)).json()["items"]
    assert next(i for i in listed if i["id"] == product["id"])["image_url"] == files[1]["url"]

    removed = c.delete(
        f"/api/v1/shop/products/{product['id']}/media/{reordered[0]['id']}", headers=_bearer(owner)
    )
    assert [m["file_id"] for m in removed.json()["media"]] == [files[0]["id"]]
    assert removed.json()["media"][0]["position"] == 0
    assert c.get(_path(files[1]["url"])).status_code == 404  # olib tashlangan rasm endi berilmaydi


# ------------------------------------------------------------------ izolyatsiya


def test_shop_a_cannot_read_or_touch_shop_b_catalog(world: World) -> None:  # TC-001, TC-ISO-05
    c = world.client
    a, b = world.create_shop(), world.create_shop()
    a_product = _priced(world, a["owner_token"])
    a_sku = a_product["skus"][0]["id"]
    a_file = _upload(world, a["owner_token"]).json()
    b_owner = b["owner_token"]
    b_product = _priced(world, b_owner)

    for response in (
        c.get(f"/api/v1/shop/products/{a_product['id']}", headers=_bearer(b_owner)),
        c.patch(
            f"/api/v1/shop/products/{a_product['id']}",
            json={"title": "Buzish"},
            headers=_bearer(b_owner, **{"If-Match": '"v1"'}),
        ),
        _post(world, b_owner, f"/products/{a_product['id']}/publish"),
        c.put(
            f"/api/v1/shop/skus/{a_sku}/price",
            json={"amount_minor": 1, "currency": "UZS"},
            headers=_bearer(b_owner, **_idem(), **{"If-Match": '"v1"'}),
        ),
        c.get(f"/api/v1/shop/skus/{a_sku}/price-history", headers=_bearer(b_owner)),
        c.get(f"/api/v1/shop/files/{a_file['id']}", headers=_bearer(b_owner)),
    ):
        assert (response.status_code, _code(response)) == (404, "NOT_FOUND"), response.text
    stolen = _post(world, b_owner, f"/products/{b_product['id']}/media", {"file_id": a_file["id"]})
    assert (stolen.status_code, _code(stolen)) == (
        422,
        "VALIDATION_FAILED",
    )  # birovning faylini ulab bo'lmaydi
    listed = c.get("/api/v1/shop/products", headers=_bearer(b_owner)).json()["items"]
    assert [i["id"] for i in listed] == [b_product["id"]]


def test_rls_hides_catalog_rows_without_or_with_other_shop_context(world: World) -> None:  # TC-ISO-08
    a, b = world.create_shop(), world.create_shop()
    editor = _platform_member(world)
    spec = _approved_spec(world, editor, model_name="GeForce RTX 4060 RLS")
    product = _priced(world, a["owner_token"], model_name="GeForce RTX 4060 RLS")
    assert product["skus"][0]["spec_link"]["spec_id"] == spec["id"]
    file_id = _upload(world, a["owner_token"]).json()["id"]
    _post(world, a["owner_token"], f"/products/{product['id']}/media", {"file_id": file_id})
    _rate(world, a["owner_token"], "12800")
    tables = (
        "catalog.products",
        "catalog.skus",
        "catalog.product_media",
        "catalog.price_versions",
        "catalog.current_prices",
        "catalog.exchange_rates",
        "catalog.sku_spec_links",
        "platform.stored_files",
    )

    async def check() -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        conn = await asyncpg.connect(world.urls.runtime.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            no_ctx = {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in tables}
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", b["shop"]["id"])
                other = {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in tables}
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.shop_id', $1, true)", a["shop"]["id"])
                own = {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in tables}
            return no_ctx, other, own
        finally:
            await conn.close()

    no_ctx, other, own = asyncio.run(check())
    assert set(no_ctx.values()) == {0} and set(other.values()) == {0}  # fail closed
    assert all(count >= 1 for count in own.values()), own


# ------------------------------------------------------------------ texnik kutubxona


def test_spec_needs_second_person_to_approve(world: World) -> None:  # engineering/17 §10
    c = world.client
    editor = _platform_member(world)
    spec = _spec(world, world.admin_token, model_name="GeForce RTX 4060", mpn="V516-012R")
    assert spec["status"] == "DRAFT" and spec["pending_version"] == 1
    own = _approve(world, world.admin_token, spec["id"])
    assert (own.status_code, _code(own)) == (403, "SELF_APPROVAL_NOT_ALLOWED")
    queue = c.get("/api/v1/platform/hardware-specs/review-queue", headers=_bearer(editor)).json()["items"]
    assert any(item["spec_id"] == spec["id"] and item["is_new"] for item in queue)
    approved = _approve(world, editor, spec["id"]).json()
    assert (
        approved["status"] == "APPROVED" and approved["version"] == 1 and approved["pending_version"] is None
    )

    # O'zgarish: tasdiqgacha eski ma'lumot ishlaydi
    change = c.post(
        f"/api/v1/platform/hardware-specs/{spec['id']}/versions",
        json={
            "brand": "MSI",
            "model_name": "GeForce RTX 4060",
            "mpn": "V516-012R",
            "attributes": {"length_mm": 199, "board_power_w": 115, "recommended_psu_w": 550},
            "source_url": "https://www.msi.com/Graphics-Card/GeForce-RTX-4060-VENTUS-2X",
        },
        headers=_bearer(editor, **_idem()),
    )
    assert change.status_code == 201, change.text
    assert change.json()["attributes"] == {"length_mm": 199, "board_power_w": 115}  # hali eski
    assert _code(_approve(world, editor, spec["id"], 2)) == "SELF_APPROVAL_NOT_ALLOWED"
    done = _approve(world, world.admin_token, spec["id"], 2).json()
    assert done["version"] == 2 and done["attributes"]["recommended_psu_w"] == 550
    assert [v["status"] for v in done["versions"]] == ["APPROVED", "APPROVED"]
    assert done["versions"][0]["proposed_by_name"] == "Bekzod Kutubxona"

    # Rad etish: sabab bilan, asosiy yozuv o'zgarmaydi
    c.post(
        f"/api/v1/platform/hardware-specs/{spec['id']}/versions",
        json={
            "brand": "MSI",
            "model_name": "GeForce RTX 4060",
            "attributes": {},
            "source_url": "https://msi.com/x",
        },
        headers=_bearer(editor, **_idem()),
    )
    rejected = c.post(
        f"/api/v1/platform/hardware-specs/{spec['id']}/versions/3/reject",
        json={"note": "manba noto'g'ri"},
        headers=_bearer(world.admin_token, **_idem()),
    ).json()
    assert rejected["version"] == 2 and rejected["versions"][0]["review_note"] == "manba noto'g'ri"

    bad = c.post(
        "/api/v1/platform/hardware-specs",
        json={
            "category": "GPU",
            "brand": "MSI",
            "model_name": "X",
            "attributes": {"length_mm": "uzun"},
            "source_url": "https://a.uz",
        },
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert bad.json()["error"]["details"]["fields"][0]["field"] == "attributes.length_mm"
    duplicate = c.post(
        "/api/v1/platform/hardware-specs",
        json={
            "category": "GPU",
            "brand": "msi",
            "model_name": "GeForce  RTX-4060",
            "attributes": {},
            "source_url": "https://a.uz",
        },
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert duplicate.json()["error"]["details"]["fields"][0] == {
        "field": "model_name",
        "code": "not_unique",
        "params": {},
    }


def test_support_sees_library_but_cannot_edit(world: World) -> None:  # business/15 §5
    support = _platform_member(world, "PLATFORM_SUPPORT")
    c = world.client
    assert c.get("/api/v1/platform/hardware-specs", headers=_bearer(support)).status_code == 200
    payload = {
        "category": "CPU",
        "brand": "AMD",
        "model_name": "Ryzen 5 7600",
        "attributes": {},
        "source_url": "https://amd.com",
    }
    response = c.post("/api/v1/platform/hardware-specs", json=payload, headers=_bearer(support, **_idem()))
    assert response.status_code == 403
    category = c.post(
        "/api/v1/platform/catalog/categories",
        json={"code": "TABLET", "name_uz": "Planshetlar", "name_ru": "Планшеты", "name_en": "Tablets"},
        headers=_bearer(support, **_idem()),
    )
    assert category.status_code == 403


def test_auto_link_exact_match_only(world: World) -> None:  # engineering/17 §5, TC-016 printsipi
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    editor = _platform_member(world)
    tag = uuid4().hex[:4].upper()
    base = _approved_spec(world, editor, model_name=f"GeForce RTX 50{tag}")
    _approved_spec(world, editor, model_name=f"GeForce RTX 50{tag} Ti")
    by_mpn = _approved_spec(world, editor, model_name=f"GeForce RTX 51{tag}", mpn=f"MPN-{tag}-01")
    for variant in ("8GB", "16GB"):
        _approved_spec(world, editor, model_name=f"GeForce RTX 52{tag}", variant_key=variant)

    product = _create(
        world,
        owner,
        skus=[
            _sku(model_name=f"geforce rtx 50{tag}"),  # brend + model (katta-kichik harf ahamiyatsiz)
            _sku(mpn=f"mpn {tag} 01"),  # MPN, boshqacha yozilgan
            _sku(model_name=f"GeForce RTX 52{tag}"),  # ikki variant — avtomatik emas
            _sku(model_name=f"GeForce RTX 53{tag}"),  # kutubxonada yo'q
        ],
    )
    links = [sku["spec_link"] for sku in product["skus"]]
    assert (links[0]["spec_id"], links[0]["method"]) == (base["id"], "AUTO_MODEL")
    assert (links[1]["spec_id"], links[1]["method"]) == (by_mpn["id"], "AUTO_MPN")
    assert links[2] is None and links[3] is None

    variants_sku = product["skus"][2]
    candidates = c.get(
        f"/api/v1/shop/skus/{variants_sku['id']}/spec-candidates", headers=_bearer(owner)
    ).json()
    assert sorted(item["variant_key"] for item in candidates["items"]) == ["16GB", "8GB"]
    chosen = candidates["items"][0]["id"]
    linked = c.put(
        f"/api/v1/shop/skus/{variants_sku['id']}/spec-link", json={"spec_id": chosen}, headers=_bearer(owner)
    )
    assert linked.status_code == 200 and linked.json()["method"] == "MANUAL"

    # Qo'lda tanlangan bog'lanishni avtomatika o'zgartirmaydi
    updated = c.patch(
        f"/api/v1/shop/skus/{variants_sku['id']}",
        json={"mpn": f"MPN-{tag}-01"},
        headers=_bearer(owner, **{"If-Match": f'"v{variants_sku["version"]}"'}),
    ).json()
    assert updated["skus"][2]["spec_link"]["spec_id"] == chosen

    # Boshqa turdagi model (CPU) GPU SKU'ga bog'lanmaydi
    cpu = _approved_spec(
        world, editor, category="CPU", brand="AMD", model_name=f"Ryzen {tag}", attributes={"socket": "AM5"}
    )
    wrong = c.put(
        f"/api/v1/shop/skus/{product['skus'][3]['id']}/spec-link",
        json={"spec_id": cpu["id"]},
        headers=_bearer(owner),
    )
    assert (wrong.status_code, _code(wrong)) == (422, "VALIDATION_FAILED")
    found = c.get("/api/v1/shop/hardware-specs", params={"q": f"rtx 50{tag}"}, headers=_bearer(owner)).json()[
        "items"
    ]
    assert {i["id"] for i in found} >= {base["id"]}


def test_spec_request_resolution_links_requested_sku(world: World) -> None:  # DEC-120
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    editor = _platform_member(world)
    tag = uuid4().hex[:6]
    product = _create(world, owner, skus=[_sku(model_name=f"Arc B{tag}")])
    sku_id = product["skus"][0]["id"]
    request = _post(
        world,
        owner,
        "/hardware-spec-requests",
        {
            "sku_id": sku_id,
            "category": "GPU",
            "brand": "Intel",
            "model_name": f"Arc B{tag}",
            "comment": "tez kerak",
        },
    )
    assert request.status_code == 201, request.text
    queue = c.get(
        "/api/v1/platform/hardware-spec-requests", params={"status": "OPEN"}, headers=_bearer(editor)
    ).json()
    item = next(i for i in queue["items"] if i["id"] == request.json()["id"])
    assert item["shop_slug"] == s["shop"]["slug"] and item["model_name"] == f"Arc B{tag}"

    spec = _approved_spec(world, editor, brand="Intel", model_name=f"Arc B{tag} Limited")
    resolved = c.post(
        f"/api/v1/platform/hardware-spec-requests/{item['id']}/resolve",
        json={"spec_id": spec["id"]},
        headers=_bearer(editor, **_idem()),
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVED"
    detail = c.get(f"/api/v1/shop/products/{product['id']}", headers=_bearer(owner)).json()
    assert detail["skus"][0]["spec_link"]["spec_id"] == spec["id"]
    mine = c.get("/api/v1/shop/hardware-spec-requests", headers=_bearer(owner)).json()["items"]
    assert mine[0]["status"] == "RESOLVED" and mine[0]["resolved_spec_id"] == spec["id"]
    again = c.post(
        f"/api/v1/platform/hardware-spec-requests/{item['id']}/reject",
        json={"note": "kech"},
        headers=_bearer(editor, **_idem()),
    )
    assert _code(again) == "INVALID_STATE_TRANSITION"


def test_categories_are_platform_managed(world: World) -> None:  # DEC-133
    c, s = world.client, world.create_shop()
    owner = s["owner_token"]
    codes = {cat["code"] for cat in c.get("/api/v1/shop/categories", headers=_bearer(owner)).json()["items"]}
    assert {"GPU", "CPU", "LAPTOP", "MONITOR", "PC_PARTS"} <= codes
    code = f"TEST_{uuid4().hex[:6].upper()}"
    created = c.post(
        "/api/v1/platform/catalog/categories",
        json={
            "code": code,
            "parent_code": "PERIPHERALS",
            "name_uz": "Sinov",
            "name_ru": "Тест",
            "name_en": "Test",
        },
        headers=_bearer(world.admin_token, **_idem()),
    )
    assert created.status_code == 201, created.text
    _create(world, owner, category_code=code, title="Yangi toifadagi mahsulot")
    off = c.patch(
        f"/api/v1/platform/catalog/categories/{code}",
        json={"is_active": False},
        headers=_bearer(world.admin_token),
    )
    assert off.json()["is_active"] is False
    blocked = _post(world, owner, "/products", {"category_code": code, "title": "Yana"})
    assert blocked.json()["error"]["details"]["fields"][0] == {
        "field": "category_code",
        "code": "invalid_choice",
        "params": {},
    }
    loop = c.patch(
        "/api/v1/platform/catalog/categories/PERIPHERALS",
        json={"parent_code": code},
        headers=_bearer(world.admin_token),
    )
    assert _code(loop) == "VALIDATION_FAILED"  # aylana: PERIPHERALS → TEST → PERIPHERALS


def test_catalog_query_port_gives_price_snapshot_for_other_domains(world: World) -> None:  # 12 §5.1
    from app.dependencies import get_catalog_query
    from app.shared.db.session import Database, DatabaseConfig

    a, b = world.create_shop(), world.create_shop()
    owner = a["owner_token"]
    product = _priced(world, owner, amount=30_000, currency="USD", variant_name="8 GB", warranty_months=36)
    rate = _rate(world, owner, "12835")
    sku_id = UUID(product["skus"][0]["id"])
    b_sku = UUID(_priced(world, b["owner_token"])["skus"][0]["id"])

    async def read() -> dict[UUID, Any]:
        database = Database(DatabaseConfig(url=world.urls.runtime))
        try:
            async with database.transaction(UUID(a["shop"]["id"])) as db:
                return dict(await get_catalog_query().get_skus(db, UUID(a["shop"]["id"]), [sku_id, b_sku]))
        finally:
            await database.dispose()

    snapshots = asyncio.run(read())
    assert set(snapshots) == {sku_id}  # boshqa shop SKU'si qaytmaydi
    snap = snapshots[sku_id]
    assert snap.title == "MSI GeForce RTX 4060 Ventus 2X · 8 GB" and snap.sellable is False  # hali qoralama
    assert (snap.amount_minor, snap.currency, snap.uzs_amount_minor) == (30_000, "USD", 385_050_000)
    assert str(snap.exchange_rate_id) == rate["id"] and snap.warranty_months == 36
