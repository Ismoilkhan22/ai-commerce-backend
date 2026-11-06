"""5c QA tuzatishlari (katalog importi): DoS himoyasi, absolyut qoldiq, NOWAIT, qatorlar bo'yicha natija,
hisobot sarlavhasi, shablon tanlash, qo'lda tanlangan model, o'chirilgan import egasi, dublikatlar."""

from __future__ import annotations

import asyncio
import io
import threading
import time
import zipfile
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.domains.catalog.imports.models.orm import ImportBatch
from tests.integration.helpers import World, _bearer, _code
from tests.integration.test_catalog import _approved_spec, _platform_member
from tests.integration.test_catalog_import import API, _act, _csv, _get, _map, _open, _rows, _upload
from tests.integration.test_commerce import Shop, _admin_sql, _hdr, _ok
from tests.integration.test_jobs_events import _drain_now, _run

pytestmark = pytest.mark.integration


def _xlsx(rows: list[list[Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _patch_sheet(data: bytes, patch: Any) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info)
            if info.filename == "xl/worksheets/sheet1.xml":
                content = patch(content)
            target.writestr(info, content)
    return out.getvalue()


def _code_of(world: World, sku: str) -> str:
    return str(_admin_sql(world, "SELECT sku_code FROM catalog.skus WHERE id = $1", UUID(sku))[0]["sku_code"])


def _stock_only(world: World, token: str, data: bytes) -> dict[str, Any]:
    batch = _open(world, token, data)
    batch = _map(
        world, token, batch, mapping={"sku_code": 0, "quantity": 1, "branch": 2}, conflict_policy="STOCK_ONLY"
    )
    batch = _ok(_act(world, token, batch, "dry-run"), 202)
    _drain_now(world)
    return _get(world, token, batch["id"])


def _commit(world: World, token: str, batch: dict[str, Any]) -> dict[str, Any]:
    _ok(_act(world, token, batch, "commit"), 202)
    _drain_now(world)
    _drain_now(world)
    return _get(world, token, batch["id"])


def test_dimension_bomb_is_rejected_cheaply_and_far_rows_do_not_block(world: World) -> None:  # F1
    shop = Shop(world)
    base = _xlsx([["SKU", "Name"], ["A-1", "x"]])
    bomb = _patch_sheet(
        base, lambda xml: xml.replace(b'<dimension ref="A1:B2" />', b'<dimension ref="A1:XFD1048576"/>')
    )
    file_id = _upload(world, shop.owner, bomb, "bomb.xlsx")
    started = time.monotonic()
    rejected = world.client.post(API, json={"file_id": file_id}, headers=_hdr(shop.owner))
    assert time.monotonic() - started < 1.0
    assert rejected.status_code == 422 and _code(rejected) == "IMPORT_FILE_INVALID"
    assert rejected.json()["error"]["details"]["reason"] == "TOO_MANY_ROWS"

    # O'lchamsiz varaq, uzoq qator (1 048 576) — o'qish chegaralangan (20 001 qatordan keyin to'xtaydi)
    far = _patch_sheet(
        base,
        lambda xml: xml.replace(b'<dimension ref="A1:B2" />', b"").replace(
            b"</sheetData>",
            b'<row r="1048576"><c r="A1048576" t="inlineStr"><is><t>far</t></is></c></row></sheetData>',
        ),
    )
    started = time.monotonic()
    batch = _open(world, shop.owner, far, "far.xlsx")
    assert time.monotonic() - started < 10
    assert batch["status"] == "UPLOADED" and batch["total_rows"] == 1
    assert world.client.get(f"{API}/{batch['id']}", headers=_bearer(shop.owner)).status_code == 200


def test_hidden_first_sheet_and_utf16_cr_only_files(world: World) -> None:  # F14, F15, F17
    shop = Shop(world)
    workbook = Workbook()
    hidden = workbook.active
    assert hidden is not None
    hidden.title, hidden.sheet_state = "Hidden", "hidden"
    hidden.append(["junk"])
    visible = workbook.create_sheet("Prays")
    visible.append(["SKU", "Name", "Category"])
    visible.append(["V-1", "Visible", "GPU"])
    out = io.BytesIO()
    workbook.save(out)
    batch = _open(world, shop.owner, out.getvalue(), "hidden.xlsx")
    assert batch["sheet_name"] == "Prays" and [c["header"] for c in batch["detected_columns"]][:1] == ["SKU"]

    utf16 = "SKU;Name;Category\r\nU-1;Юникод;GPU\r\n".encode("utf-16")
    batch = _open(world, shop.owner, utf16, "unicode.csv")
    assert batch["status"] == "UPLOADED" and batch["total_rows"] == 1

    cr_only = b"SKU;Name;Category\rCR-1;cr;GPU\r"
    batch = _open(world, shop.owner, cr_only, "mac.csv")
    assert batch["status"] == "UPLOADED" and batch["total_rows"] == 1


def test_repeated_warehouse_import_supersedes_and_approval_hits_absolute_target(world: World) -> None:  # F3
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 8)
    code = _code_of(world, sku)
    wh_token, _ = shop.staff("WAREHOUSE")
    first = _commit(
        world,
        wh_token,
        _stock_only(world, wh_token, _csv([["SKU", "Qty", "Branch"], [code, "10", "Chilonzor"]])),
    )
    second = _commit(
        world,
        wh_token,
        _stock_only(world, wh_token, _csv([["SKU", "Qty", "Branch"], [code, "10", "Chilonzor"]])),
    )
    rows = _admin_sql(
        world,
        "SELECT import_batch_id, status, target_on_hand FROM commerce.stock_adjustments "
        "WHERE sku_id = $1 ORDER BY requested_at",
        UUID(sku),
    )
    by_batch = {str(r["import_batch_id"]): (r["status"], r["target_on_hand"]) for r in rows}
    assert by_batch[first["id"]] == ("REJECTED", 10)  # yangi import eskisini almashtirdi
    assert by_batch[second["id"]] == ("PENDING", 10)
    shop.receive(sku, 1)  # tasdiqgacha qoldiq o'zgardi: 9
    pending = _ok(
        world.client.get("/api/v1/shop/stock/adjustments?status=PENDING", headers=_bearer(shop.owner))
    )["items"]
    [item] = [p for p in pending if p["sku_id"] == sku]
    assert item["target_on_hand"] == 10 and item["current_on_hand"] == 9
    approved = world.client.post(
        f"/api/v1/shop/stock/adjustments/{item['id']}/approve", headers=_hdr(shop.owner, item["version"])
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["delta"] == 1 and shop.balance(sku)["on_hand"] == 10  # absolyut maqsad


def test_per_branch_stock_results_unchanged_rows_and_committed_warning(world: World) -> None:  # F8 F9 F10
    shop = Shop(world)
    sku = shop.sku()
    shop.receive(sku, 5)
    shop.receive(sku, 3, branch=shop.branch2)
    reserved = shop.sku()
    shop.receive(reserved, 5)
    shop.step(shop.pending({reserved: 3}), "confirm")  # 3 tasi band
    code, reserved_code = _code_of(world, sku), _code_of(world, reserved)
    data = _csv(
        [
            ["SKU", "Qty", "Branch"],
            [code, "5", "Chilonzor"],
            [code, "7", "Yunusobod"],
            [reserved_code, "1", "Chilonzor"],
        ]
    )
    batch = _stock_only(world, shop.owner, data)
    rows = _rows(world, shop.owner, batch["id"])
    assert rows[2]["action"] == "SKIP" and rows[3]["action"] == "UPDATE"
    assert {e["code"] for e in rows[4]["errors"]} == {"STOCK_BELOW_COMMITTED"}
    assert batch["stats"]["skip"] == 1 and batch["stats"]["update"] == 1 and batch["stats"]["error"] == 1
    done = _commit(world, shop.owner, batch)
    rows = _rows(world, shop.owner, done["id"])
    assert (rows[2]["result"], rows[2]["stock_result"]) == ("SKIPPED", "NO_CHANGE")
    assert (rows[3]["result"], rows[3]["stock_result"]) == ("UPDATED", "APPLIED")
    assert shop.balance(sku, shop.branch2)["on_hand"] == 7 and shop.balance(reserved)["on_hand"] == 5


def test_error_report_sanitises_headers_and_keeps_duplicate_columns(world: World) -> None:  # F4 F12 F18
    shop = Shop(world)
    data = _csv(
        [
            ['=HYPERLINK("http://evil","x")', "Narx", "Narx", "Nomi", "Toifa"],
            ["R-1", "1.250", "333", "Item", "GPU"],
        ]
    )
    batch = _open(world, shop.owner, data)
    batch = _map(world, shop.owner, batch, mapping={"sku_code": 0, "price": 1, "title": 3, "category": 4})
    batch = _ok(_act(world, shop.owner, batch, "dry-run"), 202)
    _drain_now(world)
    report = _ok(world.client.post(f"{API}/{batch['id']}/error-report", headers=_bearer(shop.owner)))
    path = report["url"].split("/api/v1", 1)[1]
    text = world.client.get(f"/api/v1{path}").content.decode("utf-8-sig")
    header, line = text.splitlines()[:2]
    assert header.startswith("Qator,") and "'=HYPERLINK" in header  # sarlavha ham himoyalangan
    assert "1.250" in line and "333" in line and "Son noaniq" in line


def test_busy_import_returns_409_immediately_and_bad_cursor_is_422(world: World) -> None:  # F5 F6
    shop = Shop(world)
    batch = _open(world, shop.owner, _csv([["SKU", "Name", "Category"], ["B-1", "x", "GPU"]]))
    locked, release = threading.Event(), threading.Event()

    def hold() -> None:
        async def go() -> None:
            conn = await asyncpg.connect(world.urls.admin)
            try:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT 1 FROM catalog.import_batches WHERE id = $1 FOR UPDATE", UUID(batch["id"])
                    )
                    locked.set()
                    await asyncio.to_thread(release.wait, 10)
            finally:
                await conn.close()

        asyncio.run(go())

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert locked.wait(10)
        started = time.monotonic()
        busy = _act(world, shop.owner, batch, "cancel", 200)
        assert time.monotonic() - started < 2.0
        assert busy.status_code == 409 and _code(busy) == "IMPORT_BUSY"
    finally:
        release.set()
        thread.join()
    import base64
    import json

    for raw in ({"r": True}, {"r": 2**40}, {"r": -(2**63)}):
        cursor = base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")
        response = world.client.get(f"{API}/{batch['id']}/rows?cursor={cursor}", headers=_bearer(shop.owner))
        assert response.status_code == 422, (raw, response.text)
    for number in ("2147483648", "99999999999999999999", "0"):
        response = world.client.patch(
            f"{API}/{batch['id']}/rows/{number}", json={"selected": False}, headers=_bearer(shop.owner)
        )
        assert response.status_code == 422, (number, response.text)


def test_best_matching_template_and_explicit_mapping_id(world: World) -> None:  # F13
    shop = Shop(world)
    first = _open(world, shop.owner, _csv([["Kod A", "Nom A", "Tur A"], ["T-1", "x", "GPU"]]))
    _map(world, shop.owner, first, mapping={"sku_code": 0, "title": 1, "category": 2}, save_as="Shablon X")
    second = _open(world, shop.owner, _csv([["Kod B", "Nom B", "Tur B"], ["T-2", "y", "GPU"]]))
    _map(world, shop.owner, second, mapping={"sku_code": 0, "title": 1, "category": 2}, save_as="Shablon Y")
    templates = {
        m["name"]: m["id"]
        for m in _ok(world.client.get(f"{API}/mappings", headers=_bearer(shop.owner)))["items"]
    }
    third = _open(world, shop.owner, _csv([["Tur A", "Kod A", "Nom A"], ["GPU", "T-3", "z"]]))
    assert third["mapping"] == {"category": 0, "sku_code": 1, "title": 2}  # X — eng ko'p mos kelgan
    fourth = _open(world, shop.owner, _csv([["Nom A", "Kod A", "Tur A"], ["w", "T-4", "GPU"]]))
    applied = world.client.put(
        f"{API}/{fourth['id']}/mapping",
        json={"mapping_id": templates["Shablon X"], "conflict_policy": "CREATE_ONLY"},
        headers=_bearer(shop.owner, **{"If-Match": f'"v{fourth["version"]}"'}),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["mapping"] == {"title": 0, "sku_code": 1, "category": 2}
    mismatch = world.client.put(
        f"{API}/{third['id']}/mapping",
        json={"mapping_id": templates["Shablon Y"]},
        headers=_bearer(shop.owner, **{"If-Match": f'"v{third["version"]}"'}),
    )
    assert mismatch.status_code == 422


def test_manual_spec_choice_creates_manual_link(world: World) -> None:  # F7
    shop = Shop(world)
    editor = _platform_member(world)
    spec = _approved_spec(world, editor, brand="QAImport", model_name="Manual Pick 9000")
    batch = _open(
        world,
        shop.owner,
        _csv([["SKU", "Name", "Category", "Brand"], ["MAN-1", "Some card", "GPU", "Other"]]),
    )
    batch = _map(world, shop.owner, batch, mapping={"sku_code": 0, "title": 1, "category": 2, "brand": 3})
    batch = _ok(_act(world, shop.owner, batch, "dry-run"), 202)
    _drain_now(world)
    rows = _rows(world, shop.owner, batch["id"])
    assert rows[2]["spec_match"] == "NONE"
    chosen = world.client.patch(
        f"{API}/{batch['id']}/rows/2", json={"spec_id": spec["id"]}, headers=_bearer(shop.owner)
    )
    assert chosen.status_code == 200, chosen.text
    _commit(world, shop.owner, _get(world, shop.owner, batch["id"]))
    link = _admin_sql(
        world,
        "SELECT l.method, l.spec_id FROM catalog.sku_spec_links l JOIN catalog.skus s ON s.id = l.sku_id "
        "WHERE s.shop_id = $1 AND s.sku_code = 'MAN-1'",
        shop.id,
    )
    assert [(r["method"], str(r["spec_id"])) for r in link] == [("MANUAL", spec["id"])]


def test_inactive_importer_failure_notifies_owner(world: World) -> None:  # F16
    shop = Shop(world)
    sku = shop.sku()
    wh_token, _ = shop.staff("WAREHOUSE")
    batch = _open(world, wh_token, _csv([["SKU", "Qty", "Branch"], [_code_of(world, sku), "3", "Chilonzor"]]))
    batch = _map(
        world,
        wh_token,
        batch,
        mapping={"sku_code": 0, "quantity": 1, "branch": 2},
        conflict_policy="STOCK_ONLY",
    )
    batch = _ok(_act(world, wh_token, batch, "dry-run"), 202)
    creator = _admin_sql(
        world, "SELECT created_by FROM catalog.import_batches WHERE id = $1", UUID(batch["id"])
    )
    _admin_sql(
        world, "UPDATE platform.memberships SET status = 'DISABLED' WHERE id = $1", creator[0]["created_by"]
    )
    _drain_now(world)
    failed = _get(world, shop.owner, batch["id"])
    assert failed["status"] == "FAILED" and failed["error_code"] == "IMPORTER_INACTIVE"
    owner = _admin_sql(
        world, "SELECT id FROM platform.memberships WHERE shop_id = $1 AND role = 'OWNER'", shop.id
    )[0]["id"]
    notes = _admin_sql(
        world,
        "SELECT template_key FROM platform.notifications WHERE recipient_membership_id = $1 "
        "AND aggregate_id = $2",
        owner,
        UUID(batch["id"]),
    )
    assert [n["template_key"] for n in notes] == ["staff.import_failed"]


def test_mark_duplicates_is_fast_on_fresh_20k_rows(world: World) -> None:  # O1
    shop = Shop(world)
    batch = _open(world, shop.owner, _csv([["SKU", "Name", "Category"], ["D-1", "x", "GPU"]]))
    _admin_sql(
        world,
        "INSERT INTO catalog.import_rows "
        "(shop_id, batch_id, row_number, sku_code_normalized, row_values, action) "
        "SELECT $1, $2, g, 'sku-' || (g % 19000), '{}'::jsonb, 'CREATE' FROM generate_series(2, 20001) g",
        shop.id,
        UUID(batch["id"]),
    )

    async def go(rt: Any) -> float:
        async with rt.database.transaction(shop.id) as db:
            row = (
                await db.execute(select(ImportBatch).where(ImportBatch.id == UUID(batch["id"])))
            ).scalar_one()
            started = time.monotonic()
            await rt.services.catalog.imports._mark_duplicates(db, row)
            return time.monotonic() - started

    from app.workers.queue import RecordingQueue

    elapsed = _run(world, RecordingQueue(), go)
    assert elapsed < 3.0
    marked = _admin_sql(
        world,
        "SELECT count(*) AS n FROM catalog.import_rows WHERE batch_id = $1 AND action = 'ERROR' "
        'AND errors @> \'[{"code": "DUPLICATE_IN_FILE"}]\'',
        UUID(batch["id"]),
    )
    assert marked[0]["n"] == 2000  # 1000 ta artikul ikki martadan
