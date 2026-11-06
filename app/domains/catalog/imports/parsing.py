"""Import faylini o'qish va qiymatlarni tozalash (18 §4–§5) — bazasiz, sof funksiyalar.

- Tur faylning ICHIDAN aniqlanadi: ZIP imzosi + `xl/workbook.xml` — XLSX, aks holda matn — CSV.
- XLSX: faqat qiymatlar (formula natijasi), tashqi havolalarsiz, makrosli fayl rad etiladi; ochishdan oldin
  ZIP ichi tekshiriladi (zip-bomba: ochilgandagi hajm va siqish nisbati chegarasi).
- CSV: UTF-8 (BOM bilan ham), UTF-16 (BOM bilan — Excel "Unicode text"); bo'lmasa Windows-1251 —
  konvertatsiya va ogohlantirish; ajratgich `;`, `,` yoki tab — sarlavha qatoridan aniqlanadi; qator oxiri
  `\n`, `\r\n` yoki faqat `\r`.
- Ikki bosqich (QA F1): `precheck` — arzon, so'rov ichida (ZIP katalogi, varaq o'lchami `<dimension>`,
  sharedStrings hajmi, CSV kodirovkasi va sarlavha); `parse_file` — og'ir o'qish, faqat worker'da, alohida
  thread'da, vaqt chegarasi bilan. Fayl bir marta o'qiladi, qatorlar `import_source_rows` ga yoziladi.
- `=`, `+`, `-`, `@` bilan boshlanadigan matn — `UNSAFE_VALUE` (CSV injection, TC-IMP-05).
- Narx: mingliklar ajratgichi aniqlanadi; `1.250` / `1,250` — noaniq, xato (TC-IMP-04). Miqdor va kafolat —
  faqat butun son: `1,000` / `2.000` — noaniq (QA F2), `10.5` — xato, `10.0` — 10.
"""

from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.shared.text import strip_invisible

MAX_FILE_BYTES = 10 * 1024 * 1024  # 18 §4
MAX_ROWS = 20_000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 5_000
# zip-bomba: ochilgandagi umumiy hajm va bitta bo'lakning siqish nisbati chegarasi
MAX_UNZIPPED_BYTES = 150 * 1024 * 1024
MAX_ZIP_RATIO = 200
MAX_ZIP_ENTRIES = 2_000
# QA F1: openpyxl sharedStrings'ni to'liq xotiraga oladi, varaq XML'ini esa ketma-ket o'qiydi — ikkalasiga
# alohida chegara; varaq o'lchami (`<dimension>`) qatorlar limitidan katta — darhol rad
MAX_SST_BYTES = 30 * 1024 * 1024
MAX_SST_STRINGS = 300_000
MAX_SHEET_XML_BYTES = 100 * 1024 * 1024
MAX_WORKBOOK_XML_BYTES = 2 * 1024 * 1024
PARSE_SECONDS = 60.0  # worker'dagi o'qish vaqti chegarasi

FileFormat = Literal["XLSX", "CSV"]

# Import qila oladigan maydonlar (18 §5). `image_urls` saqlanadi, rasm yuklash keyin (M05c, keyinga).
FIELDS = (
    "sku_code",
    "title",
    "category",
    "brand",
    "model",
    "mpn",
    "variant_name",
    "condition",
    "price",
    "currency",
    "quantity",
    "branch",
    "warranty_months",
    "description",
    "attributes",
    "image_urls",
    "barcode",
)

# Sarlavha nomlari (kichik harf, apostrof bir xil) → maydon. Moslash taklifi shu lug'atdan.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "sku_code": (
        "sku",
        "sku code",
        "sku_code",
        "артикул",
        "код",
        "код товара",
        "artikul",
        "kod",
        "mahsulot kodi",
    ),
    "title": (
        "title",
        "name",
        "product",
        "наименование",
        "название",
        "товар",
        "nomi",
        "nom",
        "mahsulot",
        "mahsulot nomi",
    ),
    "category": ("category", "категория", "kategoriya", "toifa", "turi", "тип"),
    "brand": ("brand", "бренд", "производитель", "brend", "ishlab chiqaruvchi"),
    "model": ("model", "модель", "model nomi"),
    "mpn": ("mpn", "part number", "p/n", "партномер", "парт номер"),
    "variant_name": ("variant", "вариант", "variant nomi", "modifikatsiya", "модификация"),
    "condition": ("condition", "состояние", "holati", "holat"),
    "price": ("price", "цена", "narx", "narxi", "стоимость", "price uzs", "narx (so'm)"),
    "currency": ("currency", "валюта", "valyuta"),
    "quantity": ("quantity", "qty", "количество", "кол-во", "остаток", "miqdor", "soni", "qoldiq"),
    "branch": ("branch", "филиал", "склад", "filial", "ombor"),
    "warranty_months": (
        "warranty",
        "warranty months",
        "гарантия",
        "гарантия (мес)",
        "kafolat",
        "kafolat (oy)",
    ),
    "description": ("description", "описание", "tavsif", "tavsifi"),
    "attributes": ("attributes", "характеристики", "xususiyatlar", "atributlar"),
    "image_urls": ("images", "image", "image urls", "фото", "изображения", "rasm", "rasmlar"),
    "barcode": ("barcode", "ean", "штрихкод", "штрих-код", "shtrix kod", "shtrixkod"),
}

# Toifa sinonimlari (bazadagi kod va uch tildagi nomdan tashqari) — 18 §5
CATEGORY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "GPU": ("видеокарта", "videokarta", "graphics card", "video card", "gpu"),
    "CPU": ("процессор", "protsessor", "processor", "cpu"),
    "MOTHERBOARD": ("материнская плата", "мат. плата", "ona plata", "motherboard", "mb"),
    "RAM": ("оперативная память", "озу", "оперативка", "operativ xotira", "ram", "memory"),
    "STORAGE": ("ssd", "hdd", "накопитель", "жесткий диск", "жёсткий диск", "disk", "nvme"),
    "PSU": ("блок питания", "бп", "quvvat bloki", "power supply", "psu"),
    "CASE": ("корпус", "korpus", "case"),
    "CPU_COOLER": ("кулер", "кулер для процессора", "sovutgich", "cooler", "cpu cooler"),
    "CASE_FAN": ("вентилятор", "ventilyator", "fan", "case fan"),
    "MONITOR": ("монитор", "monitor"),
    "LAPTOP": ("ноутбук", "noutbuk", "laptop", "notebook"),
    "READY_PC": ("готовый пк", "готовый компьютер", "tayyor kompyuter", "desktop", "desktop pc", "pc"),
    "KEYBOARD": ("клавиатура", "klaviatura", "keyboard"),
    "MOUSE": ("мышь", "мышка", "sichqoncha", "mouse"),
    "HEADSET": ("наушники", "гарнитура", "quloqchin", "headset", "headphones"),
    "NETWORK": ("роутер", "router", "сетевое оборудование", "tarmoq"),
    "ACCESSORIES": ("аксессуары", "aksessuar", "accessory", "accessories"),
}

CURRENCY_SYNONYMS = {
    "uzs": "UZS", "so'm": "UZS", "som": "UZS", "сум": "UZS", "sum": "UZS", "сўм": "UZS",
    "usd": "USD", "$": "USD", "dollar": "USD", "доллар": "USD", "у.е.": "USD", "y.e.": "USD",
}  # fmt: skip
CONDITION_SYNONYMS = {
    "new": "NEW", "новый": "NEW", "новое": "NEW", "yangi": "NEW",
    "used": "USED", "б/у": "USED", "бу": "USED", "ishlatilgan": "USED", "b/u": "USED",
    "refurbished": "REFURBISHED", "восстановленный": "REFURBISHED", "qayta tiklangan": "REFURBISHED",
}  # fmt: skip

_APOSTROPHES = re.compile(r"[ʻʼ’‘`´]")
_SPACES = re.compile(r"\s+")
_HTML_TAG = re.compile(r"<[^>]{0,500}>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UNSAFE_START = ("=", "+", "-", "@", "\t", "\r")
_CURRENCY_MARKS = re.compile(r"(so['ʻ’]?m|сум|сўм|uzs|usd|\$|у\.е\.|y\.e\.)", re.IGNORECASE)
_INT = re.compile(r"^\d+$")
_INT_SPACED = re.compile(r"^\d{1,3}(?: \d{3})+$")  # 1 000 000 — bo'shliq bilan mingliklar noaniq emas
_DECIMAL = re.compile(r"^(\d+)[.,](\d+)$")
_DIMENSION = re.compile(rb"<(?:\w+:)?dimension\s+ref=\"([A-Z]{1,3})?(\d+)(?::([A-Z]{1,3})(\d+))?\"")
_SST_COUNT = re.compile(rb"uniqueCount=\"(\d+)\"")
_NEWLINE = re.compile(r"\r\n|\r|\n")


class ImportFileError(Exception):
    """Faylni o'qib bo'lmadi: `reason` — matnsiz kod (EMPTY, NOT_TABLE, MACRO, ZIP_BOMB, TOO_MANY_ROWS …)."""

    def __init__(self, reason: str, **details: object) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


def normalize_header(value: str) -> str:
    text = _APOSTROPHES.sub("'", value).lower().strip().strip(":*").strip()
    return _SPACES.sub(" ", text)


# ------------------------------------------------------------------ fayl
@dataclass(frozen=True)
class SheetRow:
    row_number: int  # fayldagi qator raqami (sarlavha — 1)
    cells: tuple[str | None, ...]


@dataclass(frozen=True)
class Table:
    file_format: FileFormat
    headers: tuple[str, ...]
    total_rows: int  # bo'sh bo'lmagan ma'lumot qatorlari
    sheet_name: str | None = None
    encoding: str | None = None  # CSV: "utf-8" yoki "cp1251" (ogohlantirish)
    warnings: tuple[str, ...] = ()


def detect_format(data: bytes) -> FileFormat:
    if not data:
        raise ImportFileError("EMPTY")
    return "XLSX" if data[:4] == b"PK\x03\x04" else "CSV"


_SHEET_TAG = re.compile(rb"<(?:\w+:)?sheet\b([^>]*)/?>")
_ATTR = re.compile(rb"([\w:]+)=\"([^\"]*)\"")
_REL_TAG = re.compile(rb"<(?:\w+:)?Relationship\b([^>]*)/?>")


def _attrs(raw: bytes) -> dict[str, str]:
    return {k.decode().split(":")[-1]: v.decode("utf-8", "replace") for k, v in _ATTR.findall(raw)}


def _read_small(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ImportFileError("ZIP_BOMB")
    with archive.open(info) as stream:
        return stream.read(limit + 1)[:limit]


def _first_visible_sheet(archive: zipfile.ZipFile, infos: dict[str, zipfile.ZipInfo]) -> tuple[str, str]:
    """(varaq nomi, XML yo'li): birinchi KO'RINADIGAN varaq (QA F15) — yashirin varaq o'tkazib yuboriladi."""
    workbook = _read_small(archive, infos["xl/workbook.xml"], MAX_WORKBOOK_XML_BYTES)
    rels_info = infos.get("xl/_rels/workbook.xml.rels")
    targets: dict[str, str] = {}
    if rels_info is not None:
        for raw in _REL_TAG.findall(_read_small(archive, rels_info, MAX_WORKBOOK_XML_BYTES)):
            attrs = _attrs(raw)
            target = attrs.get("Target", "")
            target = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            targets[attrs.get("Id", "")] = target
    for attrs in (_attrs(raw) for raw in _SHEET_TAG.findall(workbook)):
        if attrs.get("state", "visible") in ("hidden", "veryHidden"):
            continue
        path = targets.get(attrs.get("id", ""), "")
        if path in infos:
            return attrs.get("name", ""), path
    raise ImportFileError("EMPTY")


def _check_zip(data: bytes) -> tuple[str, str]:
    """ZIP katalogi va varaq sarlavhasi bo'yicha arzon tekshiruv. Natija — (varaq nomi, XML yo'li)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportFileError("NOT_TABLE") from exc
    with archive:
        infos_list = archive.infolist()
        if len(infos_list) > MAX_ZIP_ENTRIES:
            raise ImportFileError("ZIP_BOMB")
        infos = {info.filename: info for info in infos_list}
        if "xl/workbook.xml" not in infos:
            raise ImportFileError("NOT_TABLE")
        if any(name.lower().endswith("vbaproject.bin") for name in infos):
            raise ImportFileError("MACRO")  # .xlsm — makrosli fayl qabul qilinmaydi
        if sum(info.file_size for info in infos_list) > MAX_UNZIPPED_BYTES:
            raise ImportFileError("ZIP_BOMB")
        for info in infos_list:
            if info.file_size > 1024 * 1024 and info.file_size > MAX_ZIP_RATIO * max(info.compress_size, 1):
                raise ImportFileError("ZIP_BOMB")
        try:
            sheet_name, path = _first_visible_sheet(archive, infos)
            sheet = infos[path]
            if sheet.file_size > MAX_SHEET_XML_BYTES:
                raise ImportFileError("TOO_MANY_ROWS", max_rows=MAX_ROWS)
            with archive.open(sheet) as stream:
                head = stream.read(65536)
            match = _DIMENSION.search(head)
            if match and match.group(4) and int(match.group(4)) > MAX_ROWS + 1:
                raise ImportFileError("TOO_MANY_ROWS", max_rows=MAX_ROWS)
            sst = infos.get("xl/sharedStrings.xml")
            if sst is not None:
                if sst.file_size > MAX_SST_BYTES:
                    raise ImportFileError("ZIP_BOMB")
                with archive.open(sst) as stream:
                    count = _SST_COUNT.search(stream.read(4096))
                if count and int(count.group(1)) > MAX_SST_STRINGS:
                    raise ImportFileError("ZIP_BOMB")
        except (zipfile.BadZipFile, KeyError, OSError, EOFError) as exc:
            raise ImportFileError("NOT_TABLE") from exc
    return sheet_name, path


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    text = str(value)
    return text if text.strip() else None


def _xlsx_rows(data: bytes) -> tuple[str | None, Iterator[tuple[int, tuple[str | None, ...]]]]:
    from openpyxl import load_workbook

    sheet_name, _ = _check_zip(data)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        sheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else None
    except Exception as exc:  # buzilgan XML, shifrlangan fayl — openpyxl turli xato beradi
        raise ImportFileError("NOT_TABLE") from exc
    if sheet is None:
        raise ImportFileError("EMPTY")

    def rows() -> Iterator[tuple[int, tuple[str | None, ...]]]:
        try:
            # max_row/max_col — bo'sh qatorlar va ustunlar to'ldirilishi chegaralanadi (QA F1)
            source = sheet.iter_rows(values_only=True, max_col=MAX_COLUMNS, max_row=MAX_ROWS + 2)
            for index, values in enumerate(source, start=1):
                cells = [_cell(v) for v in values[:MAX_COLUMNS]]
                while cells and cells[-1] is None:  # max_col to'ldirgan bo'sh ustunlar olib tashlanadi
                    cells.pop()
                yield index, tuple(cells)
        except ImportFileError:
            raise
        except Exception as exc:
            raise ImportFileError("NOT_TABLE") from exc
        finally:
            workbook.close()

    return sheet.title, rows()


def _decode_csv(data: bytes) -> tuple[str, str]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 BOM — Excel "Unicode text" (QA F17)
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as exc:
            raise ImportFileError("UNSUPPORTED_ENCODING") from exc
    if b"\x00" in data:
        raise ImportFileError("UNSUPPORTED_ENCODING")  # BOM'siz UTF-16/32 yoki ikkilik fayl
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="strict"), "utf-8"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="strict"), "cp1251"


def _delimiter(first_line: str) -> str:
    counts = {d: first_line.count(d) for d in (";", ",", "\t")}
    best = max(counts, key=lambda d: (counts[d], d == ","))
    return best if counts[best] else ","


def _csv_rows(data: bytes) -> tuple[str, Iterator[tuple[int, tuple[str | None, ...]]]]:
    try:
        text, encoding = _decode_csv(data)
    except UnicodeDecodeError as exc:
        raise ImportFileError("NOT_TABLE") from exc
    first_line = _NEWLINE.split(text, 1)[0]
    # newline="" — `\r`, `\n`, `\r\n` hammasi qator oxiri (QA F14), qo'shtirnoq ichidagisi saqlanadi
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(first_line))

    def rows() -> Iterator[tuple[int, tuple[str | None, ...]]]:
        try:
            for index, values in enumerate(reader, start=1):
                yield index, tuple((v if v.strip() else None) for v in values[:MAX_COLUMNS])
        except csv.Error as exc:
            raise ImportFileError("NOT_TABLE") from exc

    return encoding, rows()


def _raw_rows(data: bytes, file_format: FileFormat) -> tuple[str | None, str | None, Iterator[SheetRow]]:
    if file_format == "XLSX":
        sheet_name, source = _xlsx_rows(data)
        encoding = None
    else:
        encoding, source = _csv_rows(data)
        sheet_name = None

    def rows() -> Iterator[SheetRow]:
        for number, cells in source:
            if any(c is not None for c in cells):
                yield SheetRow(number, cells)

    return sheet_name, encoding, rows()


def precheck(data: bytes) -> FileFormat:
    """Arzon tekshiruv (so'rov ichida, QA F1): hajm, tur, ZIP katalogi, varaq o'lchami, sharedStrings,
    CSV kodirovkasi va "sarlavha + kamida bitta qator". Og'ir o'qish — `parse_file` (worker)."""
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError("TOO_LARGE", max_bytes=MAX_FILE_BYTES)
    file_format = detect_format(data)
    if file_format == "XLSX":
        _check_zip(data)
        return file_format
    try:
        text, _ = _decode_csv(data)
    except UnicodeDecodeError as exc:
        raise ImportFileError("NOT_TABLE") from exc
    lines = (line for line in _NEWLINE.split(text) if line.strip(" \t,;"))
    if next(lines, None) is None or next(lines, None) is None:
        raise ImportFileError("EMPTY")
    return file_format


@dataclass(frozen=True)
class ParsedFile:
    table: Table
    rows: list[SheetRow]


def parse_file(data: bytes, *, seconds: float = PARSE_SECONDS) -> ParsedFile:
    """Faylni bir marta to'liq o'qish (worker, alohida thread). Vaqt chegarasi har 200 qatorda
    tekshiriladi."""
    deadline = time.monotonic() + seconds
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError("TOO_LARGE", max_bytes=MAX_FILE_BYTES)
    file_format = detect_format(data)
    sheet_name, encoding, source = _raw_rows(data, file_format)
    header = next(source, None)
    if header is None:
        raise ImportFileError("EMPTY")
    headers = tuple((c or "").strip()[:200] for c in header.cells)
    if not any(headers):
        raise ImportFileError("NO_HEADER")
    rows: list[SheetRow] = []
    for row in source:
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ImportFileError("TOO_MANY_ROWS", max_rows=MAX_ROWS)
        if len(rows) % 200 == 0 and time.monotonic() > deadline:
            raise ImportFileError("TIMEOUT")
    if not rows:
        raise ImportFileError("EMPTY")
    warnings = ("CSV_CP1251",) if encoding == "cp1251" else ()
    return ParsedFile(Table(file_format, headers, len(rows), sheet_name, encoding, warnings), rows)


def read_table(data: bytes) -> Table:
    """Sarlavha va qatorlar soni — testlar va kichik fayllar uchun (`parse_file` ustida)."""
    return parse_file(data).table


def suggest_mapping(headers: Sequence[str], saved: Mapping[str, Any] | None = None) -> dict[str, int]:
    """Maydon → ustun indeksi. Saqlangan shablon (sarlavha nomi bo'yicha) birinchi, keyin lug'at."""
    normalized = [normalize_header(h) for h in headers]
    mapping: dict[str, int] = {}
    if saved:
        for name, header in saved.items():
            if name in FIELDS and isinstance(header, str) and normalize_header(header) in normalized:
                mapping[name] = normalized.index(normalize_header(header))
    taken = set(mapping.values())
    for name, synonyms in HEADER_SYNONYMS.items():
        if name in mapping:
            continue
        for index, header in enumerate(normalized):
            if index not in taken and (header == name or header in synonyms):
                mapping[name] = index
                taken.add(index)
                break
    return mapping


# ------------------------------------------------------------------ qiymatlar
@dataclass
class RowValues:
    raw: list[str | None] = field(default_factory=list)  # ustun indeksi → asl qiymat (xatolar CSV'si)
    values: dict[str, Any] = field(default_factory=dict)  # tozalangan maydonlar
    errors: list[dict[str, str]] = field(default_factory=list)

    def error(self, name: str, code: str) -> None:
        if not any(e["field"] == name for e in self.errors):
            self.errors.append({"field": name, "code": code})


def clean_text(value: str | None, max_length: int) -> tuple[str | None, str | None]:
    """(qiymat, xato kodi). Boshqaruv va ko'rinmas belgilar olib tashlanadi; formula belgisi — xato."""
    if value is None:
        return None, None
    if value.startswith(_UNSAFE_START):
        return None, "UNSAFE_VALUE"
    text = str(strip_invisible(_CONTROL.sub("", value))).strip()
    if not text:
        return None, None
    if text.startswith(_UNSAFE_START):
        return None, "UNSAFE_VALUE"
    if len(text) > max_length:
        return None, "TOO_LONG"
    return text, None


def parse_int(value: str | None, *, maximum: int) -> tuple[int | None, str | None]:
    """Miqdor va kafolat (QA F2): `5`, `1 000` (bo'shliq — mingliklar) — to'g'ri; `1,000` / `2.000` —
    noaniq (narxdagi qoida bilan bir xil); `10.5` — xato; `10.0` / `10,00` — 10 (kasr qismi nol, 3 xonali
    emas)."""
    if value is None:
        return None, None
    text = value.replace("\u00a0", " ").replace("\u202f", " ").strip()
    if _INT_SPACED.match(text):
        text = text.replace(" ", "")
    if _INT.match(text):
        number = int(text)
    else:
        match = _DECIMAL.match(text)
        if match is None:
            return None, "INVALID_NUMBER"
        integer, fraction = match.groups()
        if len(fraction) == 3:
            return None, "AMBIGUOUS_NUMBER"  # 1,000 — 1000 yoki 1,0?
        if set(fraction) != {"0"}:
            return None, "INVALID_NUMBER"
        number = int(integer)
    if number > maximum:
        return None, "INVALID_NUMBER"
    return number, None


def parse_price(value: str | None) -> tuple[Decimal | None, str | None, str | None]:
    """(summa, valyuta belgisi, xato). `1 250 000`, `1,250,000`, `1.250.000,50`, `$300.00` — to'g'ri;
    `1.250` / `1,250` — noaniq (1250 yoki 1,25?) — xato."""
    if value is None:
        return None, None, None
    text = value.strip()
    currency = None
    marks = _CURRENCY_MARKS.findall(text)
    if marks:
        currency = CURRENCY_SYNONYMS.get(normalize_header(marks[0]))
        text = _CURRENCY_MARKS.sub("", text)
    text = text.replace(" ", " ").replace(" ", " ").strip()
    if not text or not re.fullmatch(r"[\d\s.,]+", text):
        return None, currency, "INVALID_NUMBER"
    text = re.sub(r"\s+", "", text)
    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        thousand_sep = "," if decimal_sep == "." else "."
        if text.count(decimal_sep) > 1:
            return None, currency, "INVALID_NUMBER"
        integer, fraction = text.split(decimal_sep)
        groups = integer.split(thousand_sep)
        if any(len(g) != 3 for g in groups[1:]) or not groups[0]:
            return None, currency, "INVALID_NUMBER"
        number = "".join(groups) + "." + fraction
    elif dots + commas == 0:
        number = text
    else:
        sep = "." if dots else ","
        parts = text.split(sep)
        if len(parts) > 2:  # 1.250.000 — faqat mingliklar
            if any(len(p) != 3 for p in parts[1:]) or not parts[0]:
                return None, currency, "INVALID_NUMBER"
            number = "".join(parts)
        elif len(parts[1]) == 3 and parts[0] not in ("", "0"):
            return None, currency, "AMBIGUOUS_NUMBER"  # 1.250 — 1250 yoki 1,25?
        elif parts[0] in ("", "0"):
            number = "0." + parts[1]  # 0.001 — o'nlik (mingliklar 0 bilan boshlanmaydi)
        elif 1 <= len(parts[1]) <= 2 and parts[0]:
            number = parts[0] + "." + parts[1]
        else:
            return None, currency, "INVALID_NUMBER"
    try:
        amount = Decimal(number)
    except InvalidOperation:
        return None, currency, "INVALID_NUMBER"
    if amount != amount.quantize(Decimal("0.01")):
        return None, currency, "INVALID_NUMBER"  # tiyin yoki sentdan mayda
    return amount, currency, None


def parse_attributes(value: str | None) -> tuple[dict[str, str | int | float | bool] | None, str | None]:
    """`xotira: 16; rang = qora` → {"xotira": 16, "rang": "qora"}."""
    if value is None:
        return None, None
    out: dict[str, str | int | float | bool] = {}
    for part in re.split(r"[;\n]", value):
        if not part.strip():
            continue
        match = re.match(r"^\s*([^:=]{1,40}?)\s*[:=]\s*(.{0,200}?)\s*$", part)
        if not match or not match.group(2):
            return None, "INVALID_FORMAT"
        key = re.sub(r"[^a-z0-9_]+", "_", normalize_header(match.group(1))).strip("_")
        raw = match.group(2)
        if not key or raw.startswith(_UNSAFE_START):
            return None, "INVALID_FORMAT" if not key else "UNSAFE_VALUE"
        parsed: str | int | float | bool = raw
        if re.fullmatch(r"\d{1,9}", raw):
            parsed = int(raw)
        elif re.fullmatch(r"\d{1,9}[.,]\d{1,4}", raw):
            parsed = float(raw.replace(",", "."))
        elif raw.lower() in ("true", "false", "ha", "yo'q", "да", "нет"):
            parsed = raw.lower() in ("true", "ha", "да")
        out[key] = parsed
    if len(out) > 30:
        return None, "INVALID_FORMAT"
    return out, None


def parse_choice(value: str | None, synonyms: Mapping[str, str]) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    key = normalize_header(value)
    if key in synonyms:
        return synonyms[key], None
    upper = value.strip().upper()
    if upper in set(synonyms.values()):
        return upper, None
    return None, "INVALID_CHOICE"


def category_lookup(categories: Sequence[tuple[str, str, str, str]]) -> dict[str, str]:
    """(code, name_uz, name_ru, name_en) → sinonim → kod."""
    lookup: dict[str, str] = {}
    for code, *names in categories:
        lookup[code.lower()] = code
        for name in names:
            lookup.setdefault(normalize_header(name), code)
    known = {code for code, *_ in categories}
    for code, synonyms in CATEGORY_SYNONYMS.items():
        if code in known:
            for synonym in synonyms:
                lookup.setdefault(synonym, code)
    return lookup


def normalize_row(
    cells: Sequence[str | None], headers: Sequence[str], mapping: Mapping[str, int]
) -> RowValues:
    """Bitta qator: asl qiymatlar va maydonlar bo'yicha tozalangan qiymatlar (bazaga bog'liq tekshiruvlar —
    toifa, filial, mavjud SKU, kurs — service'da)."""
    row = RowValues()
    # Indeks bo'yicha: bir xil nomli ikki ustun ham saqlanadi (QA F12)
    for index in range(len(headers)):
        cell = cells[index] if index < len(cells) else None
        row.raw.append(cell[:MAX_CELL_CHARS] if cell else None)

    def get(name: str) -> str | None:
        index = mapping.get(name)
        if index is None or index >= len(cells):
            return None
        return cells[index]

    for name, limit in (
        ("sku_code", 64),
        ("title", 300),
        ("brand", 100),
        ("model", 200),
        ("mpn", 64),
        ("variant_name", 120),
        ("branch", 200),
    ):
        value, error = clean_text(get(name), limit)
        if error:
            row.error(name, error)
        elif value is not None:
            row.values[name] = value
    description = get("description")
    if description is not None:
        text, error = clean_text(_HTML_TAG.sub(" ", description), MAX_CELL_CHARS)
        if error:
            row.error("description", error)
        elif text:
            row.values["description"] = _SPACES.sub(" ", text)
    category = get("category")
    if category is not None:
        text, error = clean_text(category, 100)
        if error:
            row.error("category", error)
        elif text:
            row.values["category"] = text
    amount, marked_currency, error = parse_price(get("price"))
    if error:
        row.error("price", error)
    elif amount is not None:
        if amount <= 0:
            row.error("price", "INVALID_NUMBER")
        else:
            row.values["price"] = str(amount)
    currency, error = parse_choice(get("currency"), CURRENCY_SYNONYMS)
    if error:
        row.error("currency", error)
    elif currency and marked_currency and currency != marked_currency:
        row.error("currency", "CURRENCY_CONFLICT")  # "$250" + "UZS" — qaysi biri to'g'ri? (QA F11)
    else:
        chosen = currency or marked_currency
        if chosen:
            row.values["currency"] = chosen
    condition, error = parse_choice(get("condition"), CONDITION_SYNONYMS)
    if error:
        row.error("condition", error)
    elif condition:
        row.values["condition"] = condition
    for name, maximum in (("quantity", 1_000_000), ("warranty_months", 120)):
        number, error = parse_int(get(name), maximum=maximum)
        if error:
            row.error(name, error)
        elif number is not None:
            row.values[name] = number
    attributes, error = parse_attributes(get("attributes"))
    if error:
        row.error("attributes", error)
    elif attributes:
        row.values["attributes"] = attributes
    barcode = get("barcode")
    if barcode is not None:
        digits = re.sub(r"\s", "", barcode)
        if not re.fullmatch(r"\d{8,14}", digits):
            row.error("barcode", "INVALID_FORMAT")
        else:
            row.values["barcode"] = digits
    images = get("image_urls")
    if images:
        urls = [u for u in re.split(r"[;\s]+", images) if u]
        row.values["image_urls"] = [u for u in urls if u.lower().startswith("https://")][:10]
    return row


def csv_safe(value: object) -> str:
    """Eksport qilinadigan katak: formula sifatida o'qilmasin (`'` prefiksi, 18 §11)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_UNSAFE_START) else text
