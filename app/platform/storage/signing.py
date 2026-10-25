"""Yopiq fayl uchun vaqtinchalik havola: `?exp=<unix>&sig=<hmac>` (catalog.md §12 — 5 daqiqa).

Havola faqat shu fayl va shu muddat uchun: kalit yoki muddat o'zgarsa imzo mos kelmaydi.
"""

from __future__ import annotations

import hashlib
import hmac


class UrlSigner:
    def __init__(self, secret: str) -> None:
        # JWT kalitidan alohida maqsadli kalit — bitta sirning ikki joyda bir xil ishlatilishi oldini olinadi
        self._key = hashlib.sha256(b"cos-file-url\x00" + secret.encode()).digest()

    def sign(self, object_key: str, expires_at: int) -> str:
        message = f"{object_key}\n{expires_at}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify(self, object_key: str, expires_at: int, signature: str, now: int) -> bool:
        if expires_at < now:
            return False
        return hmac.compare_digest(self.sign(object_key, expires_at), signature)
