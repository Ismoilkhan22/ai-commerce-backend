"""5c: katalog importi (S1-06, 18-catalog-import.md, DEC-140) — haqiqiy PostgreSQL, fon bosqichlari outbox
orqali.

Qabul mezonlari: CSV/XLSX o'qiladi; sinov hech narsa yozmaydi va qatorlarni yangi / yangilanadi /
o'tkaziladi /
xato deb ajratadi; tasdiq qoralama mahsulot, narx versiyasi va qoldiqni (kirim yoki tuzatish) yozadi; qayta
tasdiq va takroriy event hech narsani ikki marta qilmaydi; omborchi importi tuzatishni tasdiqqa yuboradi;
shopda bitta faol import; 24 soatlik sinov eskiradi; xatolar CSV'si formula sifatida o'qilmaydi; shoplar
bir-birining importini ko'rmaydi.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from openpyxl import Workbook

from app.shared.events.models import OUTBOX_SCHEMAS
from tests.integration.helpers import World, _bearer, _code, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _hdr, _ok
from tests.integration.test_jobs_events import _drain_now, _events, _job

pytestmark = pytest.mark.integration

API = "/api/v1/shop/catalog/imports"


@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> Iterator[None]:
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )
    yield


def _upload(world: World, token: str, data: bytes, filename: str = "prays.csv") -> str:
    response = world.client.post(
        f"/api/v1/shop/files?purpose=IMPORT_FILE&filename={filename}",
        content=data,
        headers=_bearer(token, **_idem(), **{"Content-Type": "application/octet-stream"}),
    )
    return str(_ok(response, 201)["id"])


def _open(world: World, token: str, data: bytes, filename: str = "prays.csv") -> dict[str, Any]:
    """Yuklash → `PARSING` (arzon tekshiruv) → worker faylni o'qiydi → `UPLOADED` (QA F1)."""
    file_id = _upload(world, token, data, filename)
    created = _ok(world.client.post(API, json={"file_id": file_id}, headers=_hdr(token)), 201)
    assert created["status"] == "PARSING", created
    _drain_now(world)
    return _get(world, token, str(created["id"]))


def _map(world: World, token: str, batch: dict[str, Any], **body: Any) -> dict[str, Any]:
    mapping = body.pop("mapping", None) or {
        c["suggested_field"]: c["index"] for c in batch["detected_columns"] if c["suggested_field"]
    }
    response = world.client.put(
        f"{API}/{batch['id']}/mapping",
        json={"mapping": mapping, **body},
        headers=_bearer(token, **{"If-Match": f'"v{batch["version"]}"'}),
    )
    return _ok(response)


def _act(world: World, token: str, batch: dict[str, Any], action: str, status: int = 202) -> Any:
    return world.client.post(
        f"{API}/{batch['id']}/{action}",
        headers=_bearer(token, **_idem(), **{"If-Match": f'"v{batch["version"]}"'}),
    )


def _get(world: World, token: str, batch_id: str) -> dict[str, Any]:
    return _ok(world.client.get(f"{API}/{batch_id}", headers=_bearer(token)))


def _rows(world: World, token: str, batch_id: str) -> dict[int, dict[str, Any]]:
    page = _ok(world.client.get(f"{API}/{batch_id}/rows?limit=200", headers=_bearer(token)))
    return {r["row_number"]: r for r in page["items"]}


def _csv(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerows(rows)
    return buffer.getvalue().encode()


HEADER = ["Артикул", "Наименование", "Категория", "Бренд", "Цена", "Валюта", "Количество", "Филиал"]


def test_full_import_flow_writes_drafts_prices_and_stock_once(world: World) -> None:
    shop = Shop(world)
    existing = shop.sku(amount=100_000_000)  # 1 000 000 so'm, qoldiq Chilonzorda 5
    shop.receive(existing, 5)
    code = _admin_sql(world, "SELECT sku_code FROM catalog.skus WHERE id = $1", UUID(existing))[0]["sku_code"]
    data = _csv(
        [
            HEADER,
            ["NEW-1", "MSI RTX 4060 Ventus", "Видеокарта", "MSI", "4 800 000", "UZS", "3", "Chilonzor"],
            [code, "Yangi nom", "GPU", "", "1 200 000", "UZS", "8", "Chilonzor"],
            ["NEW-2", "Bad price", "GPU", "", "1.250", "UZS", "", ""],
            ["DUP-1", "Dup a", "GPU", "", "100", "", "", ""],
            ["DUP-1", "Dup b", "GPU", "", "100", "", "", ""],
            ["NEW-3", '=HYPERLINK("http://evil")', "GPU", "", "100", "", "", ""],
            ["NEW-4", "No such category", "Samolyot", "", "100", "", "", ""],
            ["NEW-5", "Dollar narx", "CPU", "", "$300", "", "", ""],
        ]
    )
    batch = _open(world, shop.owner, data)
    assert batch["status"] == "UPLOADED" and batch["total_rows"] == 8 and batch["created_by_name"]
    batch = _map(world, shop.owner, batch, save_as="Asosiy prays")
    assert batch["status"] == "MAPPED" and batch["has_stock_rows"]
    batch = _ok(_act(world, shop.owner, batch, "dry-run"), 202)
    assert batch["status"] == "VALIDATING"
    _drain_now(world)
    batch = _get(world, shop.owner, batch["id"])
    assert batch["status"] == "VALIDATED" and batch["expires_at"]
    rows = _rows(world, shop.owner, batch["id"])
    assert rows[2]["action"] == "CREATE" and rows[2]["values"]["category_code"] == "GPU"
    assert rows[3]["action"] == "UPDATE"
    assert (
        rows[3]["changes"]["price"]["old"] == 100_000_000
        and rows[3]["changes"]["price"]["new"] == 120_000_000
    )
    assert rows[3]["stock"] == {"branch_id": shop.branch, "current": 5, "committed": 0, "new": 8}
    codes = {n: {e["code"] for e in r["errors"]} for n, r in rows.items() if r["action"] == "ERROR"}
    assert codes == {
        4: {"AMBIGUOUS_NUMBER"},
        5: {"DUPLICATE_IN_FILE"},
        6: {"DUPLICATE_IN_FILE"},
        7: {"UNSAFE_VALUE"},
        8: {"INVALID_CHOICE"},
        9: {"NO_EXCHANGE_RATE"},  # dollar narxi, kurs yo'q
    }
    assert batch["stats"]["create"] == 1 and batch["stats"]["update"] == 1 and batch["stats"]["error"] == 6
    # Sinov hech narsa yozmagan (BL-013)
    assert not _admin_sql(
        world, "SELECT 1 FROM catalog.skus WHERE shop_id = $1 AND sku_code = 'NEW-1'", shop.id
    )

    key = _idem()
    headers = _bearer(shop.owner, **key, **{"If-Match": f'"v{batch["version"]}"'})
    committed = _ok(world.client.post(f"{API}/{batch['id']}/commit", headers=headers), 202)
    replay = _ok(world.client.post(f"{API}/{batch['id']}/commit", headers=headers), 202)  # TC-IMP-02
    assert committed["status"] == "COMMITTING" and replay["id"] == committed["id"]
    _drain_now(world)
    _drain_now(world)
    done = _get(world, shop.owner, batch["id"])
    assert done["status"] == "COMPLETED", done
    assert done["stats"]["created"] == 1 and done["stats"]["updated"] == 1 and done["stats"]["errors"] == 6
    assert done["stats"]["stock_applied"] == 2

    created = _admin_sql(
        world,
        "SELECT p.status, pv.amount_minor FROM catalog.skus s JOIN catalog.products p ON p.id = s.product_id "
        "JOIN catalog.current_prices c ON c.sku_id = s.id "
        "JOIN catalog.price_versions pv ON pv.id = c.price_version_id "
        "WHERE s.shop_id = $1 AND s.sku_code = 'NEW-1'",
        shop.id,
    )
    assert created[0]["status"] == "DRAFT" and created[0]["amount_minor"] == 480_000_000  # saytga chiqmaydi
    versions = _admin_sql(
        world, "SELECT count(*) AS n FROM catalog.price_versions WHERE sku_id = $1", UUID(existing)
    )
    assert versions[0]["n"] == 2  # narx — yangi versiya (BL-016)
    assert shop.balance(existing)["on_hand"] == 8  # mavjud SKU — tuzatish (ega importi — darhol)
    new_sku = _admin_sql(
        world, "SELECT id FROM catalog.skus WHERE shop_id = $1 AND sku_code = 'NEW-1'", shop.id
    )
    assert shop.balance(str(new_sku[0]["id"]))["on_hand"] == 3  # yangi SKU — kirim
    adjustments = _admin_sql(
        world,
        "SELECT status, delta FROM commerce.stock_adjustments WHERE import_batch_id = $1",
        UUID(batch["id"]),
    )
    assert [(a["status"], a["delta"]) for a in adjustments] == [("APPROVED", 3)]

    # Takroriy event (TC-IMP-09): qoldiq qayta qo'llanmaydi
    _admin_sql(
        world,
        "UPDATE commerce.outbox_events SET status = 'PENDING', next_attempt_at = now() "
        "WHERE event_type = 'catalog.import.completed' AND shop_id = $1",
        shop.id,
    )
    _admin_sql(world, "DELETE FROM commerce.consumer_receipts WHERE consumer = 'commerce.import_stock'")
    _admin_sql(
        world,
        "UPDATE catalog.outbox_events SET status = 'PENDING', next_attempt_at = now() "
        "WHERE event_type = 'catalog.import.completed' AND shop_id = $1",
        shop.id,
    )
    _drain_now(world)
    assert shop.balance(existing)["on_hand"] == 8 and shop.balance(str(new_sku[0]["id"]))["on_hand"] == 3
    events = {e["type"] for e in _events(world, "catalog", shop.id)}
    assert {"catalog.import.completed", "catalog.import.changed", "catalog.sku.changed"} <= events
    assert "commerce.import_stock.applied" in {e["type"] for e in _events(world, "commerce", shop.id)}

    # Xatolar CSV'si: formula belgisi bilan boshlanadigan katak — "'" prefiksi (TC-IMP-05)
    report = _ok(world.client.post(f"{API}/{batch['id']}/error-report", headers=_bearer(shop.owner)))
    assert report["rows"] == 6 and "sig=" in report["url"]
    path = report["url"].split("/api/v1", 1)[1]
    text = world.client.get(f"/api/v1{path}").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "\n=HYPERLINK" not in text and ";=HYPERLINK" not in text
    assert any(
        m["name"] == "Asosiy prays"
        for m in _ok(world.client.get(f"{API}/mappings", headers=_bearer(shop.owner)))["items"]
    )


def test_warehouse_stock_only_import_sends_differences_to_approval(world: World) -> None:
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 10)
    code = _admin_sql(world, "SELECT sku_code FROM catalog.skus WHERE id = $1", UUID(sku))[0]["sku_code"]
    wh_token, _ = shop.staff("WAREHOUSE")
    data = _csv([["SKU", "Quantity", "Branch"], [code, "7", "Chilonzor"], [code, "4", "Yunusobod"]])
    batch = _open(world, wh_token, data)
    refused = world.client.put(
        f"{API}/{batch['id']}/mapping",
        json={"mapping": {"sku_code": 0, "quantity": 1, "branch": 2}, "conflict_policy": "UPDATE_EXISTING"},
        headers=_bearer(wh_token, **{"If-Match": f'"v{batch["version"]}"'}),
    )
    assert refused.status_code == 422  # omborchi katalogni o'zgartirmaydi
    batch = _map(
        world,
        wh_token,
        batch,
        mapping={"sku_code": 0, "quantity": 1, "branch": 2},
        conflict_policy="STOCK_ONLY",
    )
    assert "STOCK_REQUIRES_APPROVAL" in batch["warnings"]
    batch = _ok(_act(world, wh_token, batch, "dry-run"), 202)
    _drain_now(world)
    batch = _get(world, wh_token, batch["id"])
    assert batch["stats"]["update"] == 2, (batch, _rows(world, wh_token, batch["id"]))
    _ok(_act(world, wh_token, batch, "commit"), 202)
    _drain_now(world)
    _drain_now(world)
    done = _get(world, wh_token, batch["id"])
    assert (
        done["status"] == "COMPLETED"
        and done["stats"]["stock_pending"] == 1
        and done["stats"]["stock_applied"] == 1
    )
    assert shop.balance(sku)["on_hand"] == 10  # tuzatish tasdiq kutmoqda (DEC-134)
    assert shop.balance(sku, shop.branch2)["on_hand"] == 4  # yangi filial — kirim, tasdiqsiz (DEC-136)
    pending = _admin_sql(
        world,
        "SELECT status, delta, target_on_hand FROM commerce.stock_adjustments WHERE import_batch_id = $1",
        UUID(batch["id"]),
    )
    assert [(p["status"], p["delta"], p["target_on_hand"]) for p in pending] == [("PENDING", -3, 7)]


def test_xlsx_import_one_active_import_cancel_and_expiry(world: World) -> None:
    shop = Shop(world)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["SKU", "Name", "Category", "Price"])
    sheet.append(["X-1", "Excel item", "GPU", 250000])
    out = io.BytesIO()
    workbook.save(out)
    first = _open(world, shop.owner, out.getvalue(), "prays.xlsx")
    assert first["file_format"] == "XLSX" and first["total_rows"] == 1
    second = _map(world, shop.owner, _open(world, shop.owner, out.getvalue(), "prays.xlsx"))
    first = _map(world, shop.owner, first)
    first = _ok(_act(world, shop.owner, first, "dry-run"), 202)
    busy = _act(world, shop.owner, second, "dry-run")
    assert busy.status_code == 409 and _code(busy) == "IMPORT_ALREADY_RUNNING"
    _drain_now(world)
    cancelled = _ok(_act(world, shop.owner, _get(world, shop.owner, second["id"]), "cancel", 200))
    assert cancelled["status"] == "CANCELLED"
    validated = _get(world, shop.owner, first["id"])
    assert validated["status"] == "VALIDATED"
    _admin_sql(
        world,
        "UPDATE catalog.import_batches SET expires_at = now() - interval '1 minute' WHERE id = $1",
        UUID(first["id"]),
    )
    _job(world, "catalog_import_maintenance")
    expired = _get(world, shop.owner, first["id"])
    assert expired["status"] == "EXPIRED"
    late = _act(world, shop.owner, expired, "commit")
    assert late.status_code == 409


def test_imports_are_isolated_between_shops_and_need_permission(world: World) -> None:
    shop_a, shop_b = Shop(world), Shop(world)
    batch = _open(world, shop_a.owner, _csv([["SKU", "Name"], ["A-1", "x"]]))
    assert world.client.get(f"{API}/{batch['id']}", headers=_bearer(shop_b.owner)).status_code == 404
    assert world.client.get(f"{API}/{batch['id']}/rows", headers=_bearer(shop_b.owner)).status_code == 404
    foreign_file = _upload(world, shop_a.owner, _csv([["SKU"], ["A"]]))
    response = world.client.post(API, json={"file_id": foreign_file}, headers=_hdr(shop_b.owner))
    assert response.status_code == 422  # boshqa shop fayli — yo'qdek
    sales_token, _ = shop_a.staff("SALES")
    assert world.client.get(API, headers=_bearer(sales_token)).status_code == 403
    bad = world.client.post(
        "/api/v1/shop/files?purpose=IMPORT_FILE&filename=x.csv",
        content=b"\x00\x01\x02binary",
        headers=_bearer(shop_a.owner, **_idem(), **{"Content-Type": "application/octet-stream"}),
    )
    assert bad.status_code == 415
    unreadable = _upload(world, shop_a.owner, b"only-header-line\n")
    rejected = world.client.post(API, json={"file_id": unreadable}, headers=_hdr(shop_a.owner))
    assert rejected.status_code == 422 and _code(rejected) == "IMPORT_FILE_INVALID"
    template = world.client.get(f"{API}/template?format=csv", headers=_bearer(shop_a.owner))
    assert template.status_code == 200 and "Artikul" in template.content.decode("utf-8-sig")
