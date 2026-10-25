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

# Eng ko'p ishlatiladigan parollar: xalqaro ro'yxatlarning boshi + mahalliy (shahar, ism, "parol").
# Taqqoslash kichik harfda; 8 belgidan qisqalari uzunlik qoidasida to'xtaydi
_COMMON = frozenset(
    {
        "00000000", "000000000", "0123456789", "11111111", "111111111", "1111111111", "11223344",
        "112233445566", "12121212", "123123123", "123321123", "12341234", "1234512345", "12345678",
        "123456789", "1234567890", "12345678910", "123456789a", "123456789q", "12345678a", "1234567a",
        "1234qwer", "123qweasd", "147258369", "159753456", "1password", "1q2w3e4r", "1q2w3e4r5t",
        "1q2w3e4r5t6y", "1qaz2wsx", "1qazxsw2", "22222222", "33333333", "44444444", "55555555",
        "66666666", "741852963", "77777777", "7777777a", "789456123", "87654321", "88888888", "901234567",
        "987654321", "9876543210", "998901234567", "99999999", "a1234567", "a12345678", "a123456789",
        "aaaaaaa1", "aaaaaaaa", "abc12345", "abc123456", "abcd1234", "abcdefg1", "abcdefgh", "abdulloh",
        "admin123", "admin1234", "admin2025", "admin2026", "adminadmin", "administrator", "alloh123",
        "andijon1", "andijon123", "arsenal1", "asdf1234", "asdfghjk", "asdfghjkl", "assalom1", "assalomu",
        "aziz1234", "barcelona", "baseball", "bekzod123", "bismillah", "bismillah1", "bozor123",
        "bukhara1", "buxoro123", "changeme", "changeme123", "charlie1", "chelsea1", "computer",
        "default1", "demo1234", "dilshod1", "dokon123", "dollar123", "dragon12", "facebook", "fargona1",
        "ferghana", "football", "freedom1", "google123", "guest123", "iloveyou", "iloveyou1", "iloveyou2",
        "inshaalloh", "instagram", "internet", "iphone12", "jahongir", "jasur123", "jennifer", "jordan23",
        "kalit123", "kamola123", "killer12", "kompyuter", "letmein1", "liverpool", "login123", "magazin1",
        "malika123", "master12", "meningparolim", "messi123", "michael1", "money123", "monkey12",
        "muhammad", "muhammad1", "mustang1", "namangan", "namangan1", "navoiy123", "oybek123",
        "ozbekiston", "ozbekiston1", "p@ssw0rd", "p@ssword", "pa$$word", "parol123", "parol1234",
        "parol2025", "parol2026", "parolim1", "parolparol", "passpass", "passw0rd", "password",
        "password1", "password12", "password123", "password1234", "password2024", "password2025",
        "password2026", "princess", "privet123", "privetik", "pul12345", "q1234567", "qashqadaryo",
        "qazwsx123", "qazwsxedc", "qweasd123", "qweasdzxc", "qwer1234", "qwerty007", "qwerty12",
        "qwerty123", "qwerty1234", "qwerty12345", "qwerty123456", "qwerty2025", "qwerty2026", "qwertyu1",
        "qwertyui", "qwertyuiop", "realmadrid", "ronaldo7", "root1234", "rustam123", "salom123",
        "salomsalom", "samarkand", "samarqand", "samarqand1", "samsung1", "samsung123", "sardor123",
        "secret12", "secret123", "shadow12", "shahzod1", "starwars", "summer2025", "sunshine", "superman",
        "tashkent", "tashkent1", "tashkent123", "telegram", "test1234", "testtest", "toshkent",
        "toshkent1", "toshkent123", "trustno1", "user1234", "uzb12345", "uzbek123", "uzbekistan",
        "uzbekistan1", "uzbekistan123", "uzbekiston", "welcome1", "welcome123", "whatever", "whatsapp",
        "winter2025", "xorazm123", "ytrewq123", "zaq12wsx", "zaq1xsw2", "zaq1zaq1", "zxcasdqwe",
        "zxcvbnm1", "zxcvbnm123",
    }
)  # fmt: skip


def validate_new_password(password: str, phone: str | None = None, field: str = "password") -> None:
    def fail(code: str, **params: object) -> ValidationError:
        return ValidationError("Weak password", fields=[{"field": field, "code": code, "params": params}])

    if len(password) < MIN_LENGTH:
        raise fail("min_length", min=MIN_LENGTH)
    if len(password) > MAX_LENGTH:
        raise fail("max_length", max=MAX_LENGTH)
    if password.lower() in _COMMON or _contains_phone(password, phone):
        raise fail("too_weak")


def _contains_phone(password: str, phone: str | None) -> bool:
    """Parolda telefonning oxirgi 7 raqami (demak to'liq raqami ham) bo'lsa — taxmin qilish oson.
    Ajratgichlar hisobga olinmaydi: "90-123-45-67" ham ushlanadi."""
    phone_digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if len(phone_digits) < 7:
        return False
    digits = "".join(ch for ch in password if ch.isdigit())
    return phone_digits[-7:] in digits


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
