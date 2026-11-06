"""Fayllar API kontrakti (S0-08)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

UploadPurpose = Literal["PRODUCT_IMAGE", "STOCK_EVIDENCE", "SITE_LOGO", "CHAT_ATTACHMENT", "IMPORT_FILE"]


class StoredFileOut(BaseModel):
    id: UUID
    purpose: str
    mime_type: str
    size_bytes: int
    sha256: str
    original_name: str | None
    is_public: bool
    # Ochiq fayl — doimiy manzil; yopiq fayl — vaqtinchalik imzoli havola (url_expires_at gacha)
    url: str
    url_expires_at: datetime | None
    created_at: datetime
