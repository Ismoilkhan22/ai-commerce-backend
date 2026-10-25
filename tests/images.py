"""Testlar uchun kichik, tuzilmasi to'g'ri rasmlar (PNG, JPEG, WebP) — kutubxonasiz.

Fayl turi ichidan tekshiriladi (`app.platform.storage.sniff`): shunchaki imzo yetarli emas.
"""

from __future__ import annotations

import struct
import zlib


def png(width: int = 2, height: int = 2, rgb: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    row = b"\x00" + bytes(rgb) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def jpeg(width: int = 2, height: int = 2) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = (
        b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    sos = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    return b"\xff\xd8" + app0 + sof0 + sos + b"\x00" * 8 + b"\xff\xd9"


def webp() -> bytes:
    payload = b"\x2f\x00\x00\x00\x00\x07\x10\x11\x11\x88\x88\xfe\x07"  # VP8L, 1×1
    chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload + b"\x00"  # juft uzunlikka to'ldirish
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
