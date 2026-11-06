"""Katalog importi: faylni o'qish va qiymatlarni tozalash (18 §4–§5) — bazasiz."""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.domains.catalog.imports.parsing import (
    ImportFileError,
    category_lookup,
    csv_safe,
    normalize_row,
    parse_file,
    parse_price,
    read_table,
    suggest_mapping,
)


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


@pytest.mark.parametrize(
    ("text", "amount", "currency", "error"),
    [
        ("1 250 000", Decimal("1250000"), None, None),
        ("1,250,000", Decimal("1250000"), None, None),
        ("1.250.000,50", Decimal("1250000.50"), None, None),
        ("1,250,000.50", Decimal("1250000.50"), None, None),
        ("$300.00", Decimal("300.00"), "USD", None),
        ("4 800 000 so'm", Decimal("4800000"), "UZS", None),
        ("12,5", Decimal("12.5"), None, None),
        ("1.250", None, None, "AMBIGUOUS_NUMBER"),  # TC-IMP-04: 1250 yoki 1,25?
        ("1,250", None, None, "AMBIGUOUS_NUMBER"),
        ("abc", None, None, "INVALID_NUMBER"),
        ("1.2.3,4.5", None, None, "INVALID_NUMBER"),
        ("0.001", None, None, "INVALID_NUMBER"),
    ],
)
def test_price_parsing(text: str, amount: Decimal | None, currency: str | None, error: str | None) -> None:
    assert parse_price(text) == (amount, currency, error)


def test_csv_utf8_bom_and_semicolon_delimiter() -> None:
    data = "﻿Артикул;Наименование;Цена\nA-1;Видеокарта;1 250 000\n\nA-2;CPU;500\n".encode()
    table = read_table(data)
    assert table.file_format == "CSV" and table.headers == ("Артикул", "Наименование", "Цена")
    assert table.total_rows == 2 and table.warnings == ()
    rows = parse_file(data).rows
    assert [r.row_number for r in rows] == [2, 4]  # bo'sh qator o'tkazib yuboriladi, raqam saqlanadi
    assert suggest_mapping(table.headers) == {"sku_code": 0, "title": 1, "price": 2}


def test_csv_cp1251_is_converted_with_warning() -> None:
    data = "Артикул,Цена\nA-1,100\n".encode("cp1251")
    table = read_table(data)
    assert table.encoding == "cp1251" and table.warnings == ("CSV_CP1251",)
    assert parse_file(data).rows[0].cells == ("A-1", "100")


def test_xlsx_values_only_parsed_once() -> None:
    data = _xlsx([["SKU", "Name", "Price"], *[[f"S-{i}", f"Item {i}", 1000 + i] for i in range(5)]])
    table = read_table(data)
    assert table.file_format == "XLSX" and table.total_rows == 5
    window = parse_file(data).rows[2:4]
    assert [r.cells[0] for r in window] == ["S-2", "S-3"] and window[0].cells[2] == "1002"


def test_xlsx_with_macro_or_zip_bomb_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/vbaProject.bin", b"x")
    with pytest.raises(ImportFileError) as macro:
        read_table(buffer.getvalue())
    assert macro.value.reason == "MACRO"
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (20 * 1024 * 1024))  # ~20 MB → bir necha KB
    with pytest.raises(ImportFileError) as zipped:
        read_table(bomb.getvalue())
    assert zipped.value.reason == "ZIP_BOMB"


def test_limits_and_empty_files() -> None:
    with pytest.raises(ImportFileError) as empty:
        read_table(b"")
    assert empty.value.reason == "EMPTY"
    with pytest.raises(ImportFileError) as header_only:
        read_table(b"SKU,Name\n")
    assert header_only.value.reason == "EMPTY"
    many = ("SKU\n" + "\n".join(f"S{i}" for i in range(20_001))).encode()
    with pytest.raises(ImportFileError) as too_many:
        read_table(many)
    assert too_many.value.reason == "TOO_MANY_ROWS"
    with pytest.raises(ImportFileError) as binary:
        read_table(b"\x00\x01binary")
    assert binary.value.reason == "UNSUPPORTED_ENCODING"  # BOM'siz UTF-16 yoki ikkilik fayl (QA F17)


def test_normalize_row_flags_unsafe_values_and_cleans_text() -> None:
    headers = ["SKU", "Name", "Price", "Qty", "Desc", "Attrs", "Currency"]
    mapping = {
        "sku_code": 0,
        "title": 1,
        "price": 2,
        "quantity": 3,
        "description": 4,
        "attributes": 5,
        "currency": 6,
    }
    row = normalize_row(
        ["A-1", '=HYPERLINK("http://x")', "1,250", "5.0", "<b>Zo'r</b> karta", "xotira: 16; rang=qora", "$"],
        headers,
        mapping,
    )
    codes = {e["field"]: e["code"] for e in row.errors}
    assert codes == {"title": "UNSAFE_VALUE", "price": "AMBIGUOUS_NUMBER"}  # TC-IMP-05, TC-IMP-04
    assert row.values["quantity"] == 5 and row.values["description"] == "Zo'r karta"
    assert row.values["attributes"] == {"xotira": 16, "rang": "qora"} and row.values["currency"] == "USD"
    assert row.raw[1] == '=HYPERLINK("http://x")'  # xatolar CSV'si uchun asl qiymat (ustun indeksi bo'yicha)


def test_category_synonyms_and_csv_safe_export() -> None:
    lookup = category_lookup([("GPU", "Videokartalar", "Видеокарты", "Graphics cards")])
    assert lookup["видеокарта"] == "GPU" and lookup["gpu"] == "GPU" and lookup["videokartalar"] == "GPU"
    assert "монитор" not in lookup  # bazada yo'q toifaning sinonimi qo'shilmaydi
    assert [csv_safe(v) for v in ("=1+1", "+998", "-5", "@x", "ok", None)] == [
        "'=1+1",
        "'+998",
        "'-5",
        "'@x",
        "ok",
        "",
    ]
