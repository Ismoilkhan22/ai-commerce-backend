"""Ustun darajasida shifrlash — xaridor telefoni va manzili (engineering/26 §4, §9).

- **AES-256-GCM**: shifrlangan matn o'zgartirilsa, o'qishda xato beradi (soxtalashtirib bo'lmaydi).
- **Kalit identifikatori bilan**: `v1.<kalit>.<nonce+shifr>`. Kalit almashtirilganda (rotatsiya) eski yozuvlar
  eski kalit bilan o'qiladi, yangilari faol kalit bilan yoziladi — hammasini qayta shifrlash shart emas.
- **Telefon bo'yicha qidirish** — alohida kalitli HMAC-SHA256: raqamni xeshdan tiklab bo'lmaydi.

Kalitlar `Settings` dan ilova ishga tushganda bir marta beriladi (`configure_pii`). `shared` sozlamalarni
import qilmaydi (prinsip 1), shuning uchun kalitlar shu modulga tashqaridan uzatiladi. Kalit qiymati hech
qachon logga, xato matniga yoki javobga tushmaydi.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

CIPHER_FORMAT = "v1"
KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12
_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


class PiiConfigError(ValueError):
    """Kalitlar berilmagan yoki noto'g'ri — ilova ishga tushmasligi kerak."""


class PiiDecryptError(ValueError):
    """Shifrlangan qiymat buzilgan, kaliti yo'q yoki formati noto'g'ri."""


@dataclass(frozen=True)
class PiiKeyring:
    keys: dict[str, bytes]  # kalit identifikatori → 32 bayt
    active_key_id: str
    hmac_key: bytes

    def __post_init__(self) -> None:
        if not self.keys:
            raise PiiConfigError("PII kalitlari berilmagan")
        for key_id, key in self.keys.items():
            if not _KEY_ID.match(key_id):
                raise PiiConfigError(f"Kalit identifikatori noto'g'ri: {key_id!r}")
            if len(key) != KEY_BYTES:
                raise PiiConfigError(f"{key_id} kaliti {KEY_BYTES} bayt bo'lishi kerak")
        if self.active_key_id not in self.keys:
            raise PiiConfigError(f"Faol kalit {self.active_key_id!r} ro'yxatda yo'q")
        if len(self.hmac_key) < KEY_BYTES:
            raise PiiConfigError(f"HMAC kaliti kamida {KEY_BYTES} bayt bo'lishi kerak")


def parse_keys(raw: str) -> dict[str, bytes]:
    """`"k1:<base64>,k2:<base64>"` → {"k1": b"...", "k2": b"..."} (sozlamadagi ko'rinish)."""
    keys: dict[str, bytes] = {}
    for part in (item.strip() for item in raw.split(",")):
        if not part:
            continue
        key_id, sep, encoded = part.partition(":")
        if not sep:
            raise PiiConfigError("PII kaliti formati: <id>:<base64>")
        try:
            keys[key_id.strip()] = base64.b64decode(encoded.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PiiConfigError(f"{key_id.strip()} kaliti base64 emas") from exc
    return keys


_keyring: PiiKeyring | None = None


def configure_pii(keyring: PiiKeyring) -> None:
    global _keyring
    _keyring = keyring


def _ring() -> PiiKeyring:
    if _keyring is None:
        raise PiiConfigError("PII kalitlari sozlanmagan (configure_pii chaqirilmagan)")
    return _keyring


def _aad(key_id: str) -> bytes:
    return f"cos-pii:{CIPHER_FORMAT}:{key_id}".encode()


def encrypt(plaintext: str) -> str:
    ring = _ring()
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(ring.keys[ring.active_key_id]).encrypt(
        nonce, plaintext.encode(), _aad(ring.active_key_id)
    )
    payload = base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")
    return f"{CIPHER_FORMAT}.{ring.active_key_id}.{payload}"


def decrypt(token: str) -> str:
    ring = _ring()
    version, _, rest = token.partition(".")
    key_id, _, payload = rest.partition(".")
    key = ring.keys.get(key_id)
    if version != CIPHER_FORMAT or key is None or not payload:
        raise PiiDecryptError("Unknown encrypted value format or key")
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        return AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], _aad(key_id)).decode()
    except (InvalidTag, binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise PiiDecryptError("Encrypted value is corrupted") from exc


def search_hmac(value: str) -> str:
    """Qidirish uchun barqaror kalitli xesh (hex). Qiymat oldindan normallashtirilgan bo'lishi kerak."""
    return hmac.new(_ring().hmac_key, value.encode(), hashlib.sha256).hexdigest()


class EncryptedString(TypeDecorator[str]):
    """Bazada — shifrlangan matn (TEXT), Python'da — oddiy satr. NULL shifrlanmaydi."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: Any | None, dialect: Dialect) -> str | None:
        return None if value is None else decrypt(str(value))
