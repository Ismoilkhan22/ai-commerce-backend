"""Parollar: Argon2id (10 §5.1) va parol talablari (1-modul kartasi).

Hash hisoblash sekin (ataylab) — event loop'ni bloklamasligi uchun alohida thread'da.
Telefon topilmasa ham "soxta" tekshiruv qilinadi — javob vaqtidan telefon bor-yo'qligini bilib bo'lmasin.
"""

from __future__ import annotations

import anyio
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError

from app.shared.errors.base import ValidationError

MIN_LENGTH = 8
MAX_LENGTH = 128

# Eng ko'p ishlatiladigan parollar (qisqa ro'yxat; kerak bo'lsa kengaytiriladi)
_COMMON = frozenset(
    {
        "12345678", "123456789", "1234567890", "password", "password1", "qwerty123", "qwertyui",
        "11111111", "00000000", "87654321", "iloveyou", "admin123", "abc12345", "parol123",
        "qwerty12", "1q2w3e4r", "zaq12wsx", "11223344", "123123123", "88888888",
    }
)  # fmt: skip


def validate_new_password(password: str, phone: str | None = None) -> None:
    def fail(code: str, **params: object) -> ValidationError:
        return ValidationError(
            "Weak password", fields=[{"field": "password", "code": code, "params": params}]
        )

    if len(password) < MIN_LENGTH:
        raise fail("min_length", min=MIN_LENGTH)
    if len(password) > MAX_LENGTH:
        raise fail("max_length", max=MAX_LENGTH)
    digits = "".join(ch for ch in password if ch.isdigit())
    if password.lower() in _COMMON or (phone and digits and digits in phone and len(digits) >= 7):
        raise fail("too_weak")


class PasswordHasher:
    def __init__(self, time_cost: int, memory_kib: int, parallelism: int) -> None:
        self._argon = _Argon2(time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism)
        self._dummy_hash = self._argon.hash("dummy-password-for-timing")

    async def hash(self, password: str) -> str:
        return await anyio.to_thread.run_sync(self._argon.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        """Hash yo'q bo'lsa ham bir xil vaqt sarflanadi."""
        target = password_hash or self._dummy_hash

        def check() -> bool:
            try:
                return bool(self._argon.verify(target, password))
            except (VerificationError, InvalidHashError):
                return False

        ok = await anyio.to_thread.run_sync(check)
        return ok and password_hash is not None

    def needs_rehash(self, password_hash: str) -> bool:
        return bool(self._argon.check_needs_rehash(password_hash))
