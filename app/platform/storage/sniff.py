"""Fayl turini ICHIDAN aniqlash (magic bytes + minimal tuzilma) — nomi yoki Content-Type'ga ishonilmaydi.

`.jpg` deb nomlangan dastur yoki HTML fayli rasm sifatida saqlanmaydi. Faqat boshidagi imzo yetarli emas:
3 baytlik "JPEG" yoki PNG sarlavhasi + HTML ham ushlanadi. Tekshiruv dekoder emas (kutubxonasiz), lekin
rasmning asosiy qismlari joyida ekanini ko'radi:
- PNG: imzo → bo'laklar uzunligi bo'yicha yuriladi: birinchisi IHDR (13 bayt, eni va bo'yi 1…MAX_SIDE),
  kamida bitta IDAT, keyin IEND. IEND'dan keyingi baytlar e'tiborsiz (ba'zi dasturlar qo'shadi);
- JPEG: SOI → segmentlar uzunligi bo'yicha yurib, SOS'dan oldin SOFn (eni va bo'yi > 0) topiladi;
- WebP: RIFF hajmi faylga sig'adi → birinchi bo'lak VP8 / VP8L / VP8X va uning hajmi RIFF ichida.
"""

from __future__ import annotations

import struct

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
IMAGE_TYPES = frozenset(EXTENSIONS)
MAX_SIDE = 20_000  # piksel — undan kattasi rasm emas, xotirani to'ldirish urinishi

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# SOF0…SOF15, DHT (C4), JPG (C8), DAC (CC) bundan mustasno
_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_JPEG_STANDALONE = frozenset({0x01, *range(0xD0, 0xD8)})  # TEM, RST0…RST7 — uzunliksiz
_JPEG_SOS = 0xDA
_WEBP_CHUNKS = frozenset({b"VP8 ", b"VP8L", b"VP8X"})


def _sane(width: int, height: int) -> bool:
    return 0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE


def _is_png(data: bytes) -> bool:
    if len(data) < 8 + 25 + 12 or not data.startswith(_PNG_SIGNATURE):
        return False
    length, kind = struct.unpack(">I4s", data[8:16])
    if length != 13 or kind != b"IHDR":
        return False
    width, height = struct.unpack(">II", data[16:24])
    if not _sane(width, height):
        return False
    pos, seen_idat = 8 + 25, False  # imzo + IHDR (uzunlik, tur, 13 bayt, CRC)
    while pos + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if pos + 12 + length > len(data):
            return False  # kesilgan bo'lak
        if kind == b"IEND":
            return seen_idat
        seen_idat = seen_idat or kind == b"IDAT"
        pos += 12 + length
    return False


def _is_jpeg(data: bytes) -> bool:
    if not data.startswith(b"\xff\xd8"):
        return False
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return False
        marker = data[pos + 1]
        if marker == 0xFF:  # to'ldiruvchi bayt
            pos += 1
            continue
        if marker in _JPEG_STANDALONE:
            pos += 2
            continue
        if marker == _JPEG_SOS or marker == 0xD9:  # rasm ma'lumoti yoki oxiri — SOF topilmadi
            return False
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        if length < 2 or pos + 2 + length > len(data):
            return False
        if marker in _JPEG_SOF:
            if length < 8:
                return False
            height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return _sane(width, height)
        pos += 2 + length
    return False


def _is_webp(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    (riff_size,) = struct.unpack("<I", data[4:8])
    chunk, chunk_size = data[12:16], struct.unpack("<I", data[16:20])[0]
    return (
        chunk in _WEBP_CHUNKS
        and chunk_size > 0
        and riff_size + 8 <= len(data)
        and 4 + 8 + chunk_size <= riff_size
    )


def sniff_mime(data: bytes) -> str | None:
    if _is_jpeg(data):
        return "image/jpeg"
    if _is_png(data):
        return "image/png"
    if _is_webp(data):
        return "image/webp"
    return None
