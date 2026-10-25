"""FileStorage porti — fayl baytlari qayerda turishi servisdan yashirin (ADR-014).

Ikki adapter: lokal disk (`local.py`, dev va test) va S3-mos ombor (production, deploy bilan — S0-10, TD-03).
Bazada blob saqlanmaydi; `platform.stored_files` faqat yozuv (kim, nima, qayerda).
"""

from __future__ import annotations

from typing import Protocol


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Faylni `key` yo'liga yozadi (bor bo'lsa — almashtiradi)."""

    async def get(self, key: str) -> bytes | None:
        """Fayl baytlari; yo'q bo'lsa — None."""

    async def delete(self, key: str) -> None:
        """Faylni o'chiradi; yo'q bo'lsa — xato emas."""
