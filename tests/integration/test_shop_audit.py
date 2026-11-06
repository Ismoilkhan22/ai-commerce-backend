"""M20: egaga "O'zgarishlar tarixi" — `GET /shop/audit` va CSV eksport (`audit.view`).

Ruxsat (ega, menejer), cursor sahifalash va filtrlar, qiymatlar ko'rsatilmasligi, boshqa shop yozuvlari
ko'rinmasligi (RLS), platforma izohi yashirilishi, CSV-injection himoyasi.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from tests.integration.helpers import World, _bearer
from tests.integration.test_commerce import Shop, _admin_sql, _ok

pytestmark = pytest.mark.integration

INSERT = (
    "INSERT INTO audit.audit_entries (id, shop_id, actor_type, action, entity_type, reason, diff) "
    "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6::jsonb)"
)


def _get(world: World, token: str, path: str = "", **params: Any) -> Any:
    return world.client.get(f"/api/v1/shop/audit{path}", params=params, headers=_bearer(token))


def test_audit_history_permissions_pages_filters_and_no_values(world: World) -> None:
    shop, other = Shop(world), Shop(world)
    manager, _ = shop.staff("MANAGER")
    sales, _ = shop.staff("SALES")
    _admin_sql(
        world, INSERT, shop.id, "STAFF", "catalog.price.changed", "sku", "narx", '{"amount_minor": 12345}'
    )
    _admin_sql(world, INSERT, other.id, "STAFF", "catalog.price.changed", "sku", None, None)

    # Ruxsat: ega va menejer ko'radi; sotuvchi — 403 (va bu urinish yozib qo'yiladi)
    assert _get(world, sales).status_code == 403
    assert _get(world, shop.owner).status_code == 200 and _get(world, manager).status_code == 200
    assert _get(world, sales, "/export").status_code == 403
    denied = _ok(_get(world, shop.owner, action="audit.denied"))
    assert denied["items"] and denied["items"][0]["entity_type"] == "audit"

    everything = _ok(_get(world, shop.owner, limit=100))
    ids = {UUID(i["id"]) for i in everything["items"]}
    mine = {
        r["id"] for r in _admin_sql(world, "SELECT id FROM audit.audit_entries WHERE shop_id = $1", shop.id)
    }
    assert ids == mine  # faqat shu shop (RLS), boshqa shop yozuvi yo'q
    assert everything["has_more"] is False and everything["next_cursor"] is None

    # Qiymatlar yo'q: faqat maydon nomlari
    [price] = [i for i in everything["items"] if i["action"] == "catalog.price.changed"]
    assert price["changed_fields"] == ["amount_minor"] and price["reason"] == "narx"
    assert "12345" not in str(everything) and not any("diff" in i for i in everything["items"])

    # Filtrlar
    by_action = _ok(_get(world, shop.owner, action="catalog.price"))
    assert [i["action"] for i in by_action["items"]] == ["catalog.price.changed"]
    assert _ok(_get(world, shop.owner, entity_type="sku"))["items"] == by_action["items"]
    assert not _ok(_get(world, shop.owner, entity_type="sku", date_to="2000-01-01T00:00:00Z"))["items"]
    assert _ok(_get(world, shop.owner, actor_id=str(UUID(int=1))))["items"] == []

    # Cursor: sahifalar kesishmaydi va hammasini qamraydi
    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = _ok(_get(world, shop.owner, limit=2, **({"cursor": cursor} if cursor else {})))
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert len(seen) == len(set(seen)) and {UUID(i) for i in seen} >= ids
    assert _get(world, shop.owner, cursor="!!!").status_code == 422


def test_audit_platform_reason_hidden_and_csv_is_injection_safe(world: World) -> None:
    shop = Shop(world)
    _admin_sql(world, INSERT, shop.id, "PLATFORM", "shops.shop.suspended", "shop", "ichki izoh", None)
    _admin_sql(world, INSERT, shop.id, "STAFF", "=HYPERLINK(1)", "sku", "+cmd|calc", '{"=evil": 1}')
    items = _ok(_get(world, shop.owner, limit=100))["items"]
    [platform] = [i for i in items if i["action"] == "shops.shop.suspended"]
    assert platform["reason"] is None and platform["actor_name"] is None  # platforma izohi egaga berilmaydi

    response = _get(world, shop.owner, "/export")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.text.removeprefix("﻿")
    assert (
        text.splitlines()[0] == "occurred_at,actor_type,actor_id,action,entity_type,entity_id,reason,fields"
    )
    assert "ichki izoh" not in text
    assert "'=HYPERLINK(1)" in text and "'+cmd|calc" in text and "'=evil" in text
    for line in text.splitlines()[1:]:
        for cell in line.split(","):
            assert not cell.startswith(("=", "+", "@"))  # hech bir katakcha formula bo'lib boshlanmaydi
