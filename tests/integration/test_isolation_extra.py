"""TC-ISO-03 (bilim bazasi) va TC-ISO-07 (fon vazifasida soxta shop_id) — M09 da alohida test yo'q edi.

ISO-03: A shopning FAQ/siyosati B shop paneli va AI'siga ko'rinmaydi, B uni o'zgartira olmaydi.
ISO-07: event'dagi `shop_id` bilan boshqa shop obyektiga ishora qilinsa — RLS tufayli obyekt topilmaydi,
hech narsa o'zgarmaydi.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _ok

pytestmark = pytest.mark.integration


def test_knowledge_base_is_isolated_between_shops(world: World) -> None:  # TC-ISO-03
    a, b = Shop(world), Shop(world)
    body = {"kind": "POLICY", "locale": "uz", "title": "Kafolat", "body": "A do'konning maxfiy siyosati"}
    item = _ok(
        world.client.post("/api/v1/shop/ai/knowledge", json=body, headers=_bearer(a.owner, **_idem())), 201
    )
    listed_b = _ok(world.client.get("/api/v1/shop/ai/knowledge", headers=_bearer(b.owner)))
    assert all(i["id"] != item["id"] for i in listed_b["items"])
    patch = world.client.patch(
        f"/api/v1/shop/ai/knowledge/{item['id']}",
        json={"title": "buzildi"},
        headers=_bearer(b.owner, **{"If-Match": '"v1"'}),
    )
    assert patch.status_code == 404
    publish = world.client.post(
        f"/api/v1/shop/ai/knowledge/{item['id']}/publish",
        headers=_bearer(b.owner, **_idem(), **{"If-Match": '"v1"'}),
    )
    assert publish.status_code == 404


def test_forged_shop_id_in_job_cannot_touch_other_shop(world: World) -> None:  # TC-ISO-07
    a, b = Shop(world), Shop(world)
    run_id = _admin_sql(
        world,
        "INSERT INTO catalog.price_list_runs (id, shop_id, file_id, status, source_format, version) "
        "VALUES (gen_random_uuid(), $1, gen_random_uuid(), 'READING', 'CSV', 1) RETURNING id",
        b.id,
    )[0]["id"]
    service = world.client.app.state.catalog.price_lists

    async def go() -> Any:
        from app.shared.db.session import Database

        database = Database(world.settings.database_config())
        try:
            return await service.read(database, a.id, run_id)  # A nomidan B'ning obyekti
        finally:
            await database.dispose()

    assert asyncio.run(go()) == "skipped"
    status = _admin_sql(world, "SELECT status FROM catalog.price_list_runs WHERE id = $1", run_id)[0][
        "status"
    ]
    assert status == "READING"  # tegilmadi
