"""Pul: butun son (minor birlik) + valyuta (ADR-025, 11 §3).

UZS va USD ikkalasining ham exponent'i 2: 1 so'm = 100 tiyin, 1 dollar = 100 sent. Float ishlatilmaydi.

Chegara: har qanday summa (so'mga o'girilgani ham) `MAX_SAFE_MINOR` dan oshmaydi — brauzer (JavaScript)
2^53 dan katta butun sonni aniq o'qiy olmaydi, PostgreSQL bigint esa 9.2e18 da tugaydi.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Currency = Literal["UZS", "USD"]
CURRENCIES: tuple[Currency, ...] = ("UZS", "USD")
MINOR_PER_UNIT = 100  # ikkala valyuta uchun (exponent 2)

MAX_SAFE_MINOR = 2**53 - 1  # JavaScript Number.MAX_SAFE_INTEGER
MAX_RATE = 1_000_000  # 1 dollar ko'pi bilan necha so'm (kurs kiritishdagi chegara)
# Eng katta kursda ham so'mdagi summa MAX_SAFE_MINOR ichida qolishi uchun (~90 mln dollar).
# Yaxlitlash (+50 tiyin) uchun bitta so'm zaxira
MAX_USD_MINOR = (MAX_SAFE_MINOR - MINOR_PER_UNIT) // MAX_RATE


def to_uzs_minor(amount_minor: int, currency: Currency, rate: Decimal | None) -> int | None:
    """Narxni so'mga (tiyinda) o'giradi. Kurs yo'q bo'lsa — None (dollar narxini ko'rsatib bo'lmaydi).

    Natija — eng yaqin butun so'm (0.5 yuqoriga), mingliklarga yaxlitlanmaydi (DEC-133 "aniq so'mgacha"):
    300 $ × 12 800 = 3 840 000 so'm; 300 $ × 12 835 = 3 850 500 so'm; 0.01 $ × 12 850 = 128.5 → 129 so'm.
    Natija `MAX_SAFE_MINOR` dan katta chiqsa (kiritishda bunga yo'l qo'yilmaydi) — None, xuddi kurs
    yo'qdek: noto'g'ri summani ko'rsatgandan ko'ra ko'rsatmagan yaxshi.
    """
    if currency == "UZS":
        return amount_minor if amount_minor <= MAX_SAFE_MINOR else None
    if rate is None:
        return None
    # sent × (so'm/dollar) = tiyin, chunki ikkala exponent bir xil
    tiyin = Decimal(amount_minor) * rate
    sum_units = (tiyin / MINOR_PER_UNIT).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    result = int(sum_units) * MINOR_PER_UNIT
    return result if result <= MAX_SAFE_MINOR else None
