"""5c QA tuzatishlari — bazasiz: o'qish chegaralari, sonlar, valyuta ziddiyati, kodirovka, xato kodlari."""

from __future__ import annotations

import io
import time
import zipfile

import pytest
from openpyxl import Workbook

from app.domains.catalog.imports.parsing import (
    MAX_SST_STRINGS,
    ImportFileError,
    csv_safe,
    normalize_row,
    parse_file,
    parse_int,
    precheck,
)
from app.domains.catalog.imports.services.import_service import ImportService, _row_error_text
from app.shared.errors.base import ImportBusyError, ValidationError
from app.shared.i18n.translator import t


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _patch(data: bytes, name: str, patch: object) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info)
            if info.filename == name:
                content = patch(content)  # type: ignore[operator]
            target.writestr(info, content)
    return out.getvalue()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5", (5, None)),
        ("1 000", (1000, None)),
        ("1 000", (1000, None)),
        ("10.0", (10, None)),
        ("10,00", (10, None)),
        ("1,000", (None, "AMBIGUOUS_NUMBER")),
        ("2.000", (None, "AMBIGUOUS_NUMBER")),
        ("12.000", (None, "AMBIGUOUS_NUMBER")),
        ("10.5", (None, "INVALID_NUMBER")),
        ("1,500", (None, "AMBIGUOUS_NUMBER")),
        ("-1", (None, "INVALID_NUMBER")),
        ("abc", (None, "INVALID_NUMBER")),
    ],
)
def test_parse_int_rejects_ambiguous_separators(value: str, expected: tuple[int | None, str | None]) -> None:
    assert parse_int(value, maximum=1_000_000) == expected  # QA F2


def test_currency_marker_conflicting_with_column_is_an_error() -> None:  # F11
    row = normalize_row(
        ["A-1", "$250", "UZS"], ["SKU", "Price", "Currency"], {"sku_code": 0, "price": 1, "currency": 2}
    )
    assert {"field": "currency", "code": "CURRENCY_CONFLICT"} in row.errors
    ok = normalize_row(
        ["A-1", "$250", "USD"], ["SKU", "Price", "Currency"], {"sku_code": 0, "price": 1, "currency": 2}
    )
    assert not ok.errors and ok.values["currency"] == "USD"


def test_raw_values_are_kept_by_column_index() -> None:  # F12
    row = normalize_row(["a", "1", "2"], ["SKU", "Narx", "Narx"], {"sku_code": 0})
    assert row.raw == ["a", "1", "2"]


def test_dimension_bomb_rejected_by_precheck_in_milliseconds() -> None:  # F1
    bomb = _patch(
        _xlsx([["SKU"], ["A"]]),
        "xl/worksheets/sheet1.xml",
        lambda xml: xml.replace(b'<dimension ref="A1:A2" />', b'<dimension ref="A1:XFD1048576"/>'),
    )
    started = time.monotonic()
    with pytest.raises(ImportFileError) as exc:
        precheck(bomb)
    assert exc.value.reason == "TOO_MANY_ROWS" and time.monotonic() - started < 0.5


def test_shared_strings_count_cap() -> None:  # F1
    data = io.BytesIO()
    with zipfile.ZipFile(data, "a") as target, zipfile.ZipFile(io.BytesIO(_xlsx([["SKU"], ["A"]]))) as src:
        for info in src.infolist():
            target.writestr(info, src.read(info))
        target.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="x" count="1" uniqueCount="{MAX_SST_STRINGS + 1}"><si><t>a</t></si></sst>',
        )
    with pytest.raises(ImportFileError) as exc:
        precheck(data.getvalue())
    assert exc.value.reason == "ZIP_BOMB"


def test_first_visible_sheet_is_used() -> None:  # F15
    workbook = Workbook()
    hidden = workbook.active
    assert hidden is not None
    hidden.title, hidden.sheet_state = "Hidden", "hidden"
    hidden.append(["junk"])
    visible = workbook.create_sheet("Prays")
    visible.append(["SKU", "Name"])
    visible.append(["A", "x"])
    out = io.BytesIO()
    workbook.save(out)
    parsed = parse_file(out.getvalue())
    assert parsed.table.sheet_name == "Prays" and parsed.table.headers == ("SKU", "Name")


def test_csv_cr_only_and_utf16_bom() -> None:  # F14, F17
    assert parse_file(b"SKU;Name\rA;x\rB;y\r").table.total_rows == 2
    utf16 = "SKU;Name\r\nA;Юникод\r\n".encode("utf-16")
    parsed = parse_file(utf16)
    assert parsed.rows[0].cells == ("A", "Юникод")
    with pytest.raises(ImportFileError) as exc:
        precheck("SKU;Name\r\nA;x\r\n".encode("utf-16-le"))  # BOM'siz UTF-16
    assert exc.value.reason == "UNSUPPORTED_ENCODING"


def test_precheck_rejects_header_only_csv() -> None:
    with pytest.raises(ImportFileError) as exc:
        precheck(b"only-header-line\n")
    assert exc.value.reason == "EMPTY"


def test_parse_timeout_is_enforced() -> None:
    data = ("SKU;Name\n" + "".join(f"S{i};x\n" for i in range(1000))).encode()
    with pytest.raises(ImportFileError) as exc:
        parse_file(data, seconds=-1)
    assert exc.value.reason == "TIMEOUT"


def test_csv_safe_covers_header_like_values() -> None:  # F4
    assert csv_safe('=HYPERLINK("x")') == '\'=HYPERLINK("x")'
    assert csv_safe("\t=1+1").startswith("'")


def test_failure_codes_are_product_codes() -> None:  # F16
    assert ImportService._failure_code(ImportFileError("TIMEOUT")) == "TIMEOUT"
    assert ImportService._failure_code(ValidationError("x")) == "VALIDATION_FAILED"
    assert ImportService._failure_code(RuntimeError("boom")) == "IMPORT_FAILED"
    assert ImportBusyError("x").code == "IMPORT_BUSY"


def test_report_texts_are_localised() -> None:  # F18
    assert t("import.report.row_number", "ru") == "Строка"
    assert _row_error_text("AMBIGUOUS_NUMBER", "en").startswith("Ambiguous number")
    assert _row_error_text("SOME_NEW_CODE", "uz") == "SOME_NEW_CODE"
    for reason in (
        "EMPTY",
        "NO_HEADER",
        "NOT_TABLE",
        "MACRO",
        "ZIP_BOMB",
        "TOO_MANY_ROWS",
        "UNSUPPORTED_ENCODING",
    ):
        for locale in ("uz", "ru", "en"):
            assert t(f"import.file_reasons.{reason}", locale) != f"import.file_reasons.{reason}"  # type: ignore[arg-type]
