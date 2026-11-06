"""M25 (Stage 2): filiallar orasida ko'chirish — BL-082: qoldiq ikki marta hisoblanmaydi.

Jo'natish manbadan darhol ayiradi (band qilingani ketmaydi), yo'lda hech qaysi filialda mavjud emas;
qabul qo'shadi, kam kelsa — kamomad va vazifa; bekor — manbaga qaytadi; ikki marta qabul yo'q.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _ok

pytestmark = pytest.mark.integration
API = "/api/v1/shop/stock/transfers"


def _available(world: World, shop: Shop, sku: str) -> dict[str, int]:
    rows = _ok(world.client.get(f"/api/v1/shop/stock?sku_id={sku}", headers=_bearer(shop.owner)))["items"]
    return {r["branch_id"]: r["available"] for r in rows}


def _send(world: World, shop: Shop, sku: str, qty: int, token: str | None = None) -> Any:
    body = {
        "from_branch_id": shop.branch,
        "to_branch_id": shop.branch2,
        "lines": [{"sku_id": sku, "qty": qty}],
    }
    return world.client.post(API, json=body, headers=_bearer(token or shop.owner, **_idem()))


def test_transfer_send_receive_shortage_and_cancel(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 10)
    assert _send(world, shop, sku, 11).status_code == 409  # bor narsadan ko'p emas

    sent = _ok(_send(world, shop, sku, 6), 201)
    assert sent["status"] == "IN_TRANSIT"
    levels = _available(world, shop, sku)
    assert levels.get(shop.branch) == 4 and levels.get(shop.branch2, 0) == 0  # yo'lda — hech qayerda yo'q

    received = _ok(
        world.client.post(
            f"{API}/{sent['id']}/receive",
            json={"lines": [{"sku_id": sku, "received_qty": 5}]},
            headers=_bearer(shop.owner, **{"If-Match": f'"v{sent["version"]}"'}),
        )
    )
    assert received["status"] == "RECEIVED" and received["shortage_units"] == 1
    levels = _available(world, shop, sku)
    assert levels[shop.branch] == 4 and levels[shop.branch2] == 5
    again = world.client.post(
        f"{API}/{sent['id']}/receive",
        json={},
        headers=_bearer(shop.owner, **{"If-Match": f'"v{received["version"]}"'}),
    )
    assert again.status_code == 409  # ikki marta qabul yo'q
    tasks = _ok(world.client.get("/api/v1/shop/tasks", headers=_bearer(shop.owner)))["items"]
    assert any(t["type"] == "TRANSFER_SHORTAGE" for t in tasks)

    second = _ok(_send(world, shop, sku, 3), 201)
    assert _available(world, shop, sku)[shop.branch] == 1
    cancelled = _ok(
        world.client.post(
            f"{API}/{second['id']}/cancel",
            headers=_bearer(shop.owner, **{"If-Match": f'"v{second["version"]}"'}),
        )
    )
    assert cancelled["status"] == "CANCELLED" and _available(world, shop, sku)[shop.branch] == 4

    sales, _ = shop.staff("SALES")
    assert _send(world, shop, sku, 1, sales).status_code == 403
    listed = _ok(world.client.get(f"{API}?status=RECEIVED", headers=_bearer(shop.owner)))["items"]
    assert [t["id"] for t in listed] == [sent["id"]]


def test_transfer_suggestions(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 8)
    shop.receive(sku, 1, branch=shop.branch2)
    back = {"from_branch_id": shop.branch2, "to_branch_id": shop.branch, "lines": [{"sku_id": sku, "qty": 1}]}
    _ok(world.client.post(API, json=back, headers=_bearer(shop.owner, **_idem())), 201)  # Yunusobodda 0 qoldi
    items = _ok(world.client.get(f"{API}/suggestions", headers=_bearer(shop.owner)))["items"]
    hint = next(i for i in items if i["sku_id"] == sku)
    assert hint["from_branch_id"] == shop.branch and hint["to_branch_id"] == shop.branch2
    assert hint["suggested_qty"] == 4
