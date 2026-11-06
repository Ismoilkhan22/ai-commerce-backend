"""QA7 tuzatishlari: validator (F4, F5) va PII redaction (F6) — tarmoqsiz birlik testlari."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.domains.sales_ai.validator import TurnFacts, validate_reply
from app.platform.llm.redaction import MemoryPiiStore, find_pii, redact

FACTS = TurnFacts(
    prices={Decimal(3_500_000)},
    prices_usd={Decimal(350)},
    titles={"RTX 4060 Dual 8GB"},
    queries={"rtx 4060"},
    availability={"RTX 4060 Dual 8GB": "IN_STOCK"},
    warranty_months={12},
    stock_checked=True,
    compat_decisions={"PASS"},
)


# ------------------------------------------------------------------ F4: kafolat / buyurtma / chegirma
@pytest.mark.parametrize(
    "text",
    [
        "garantiya",
        "2 yil garantiya",
        "100% kafolat",
        "kafolat 100%",
        "гарантия 100%",
        "lifetime warranty",
        "umrbod kafolat",
        "пожизненная гарантия",
        "30 kunlik qaytarish kafolati",
        "кафолат беряпмиз",
        "заказ создан",
        "заказ №1 создан",
        "buyurtma yaratildi",
        "buyurtma berildi",
        "buyurtmani rasmiylashtirdim",
        "to'lovni qabul qildik",
        "деньги получили",
        "payment received",
        "дисконт 10%",
        "promo kod",
        "promokod",
    ],
)
def test_forbidden_phrases_are_blocked(text: str) -> None:
    assert validate_reply(text, FACTS), text


@pytest.mark.parametrize(
    "text",
    [
        "kafolat muddati 12 oy",
        "Kafolat: 12 oy",
        "12 oy kafolat",
        "1 yil kafolat",
        "12 oy garantiya",
        "Gwarantiya 12 oy",
        "buyurtma berish uchun operatorga ulayman",
        "buyurtma bermoqchimisiz?",
        "Salom! Sizga qanday yordam bera olaman?",
    ],
)
def test_allowed_phrases_stay_allowed(text: str) -> None:
    assert validate_reply(text, FACTS) == [], text


# ------------------------------------------------------------------ F5: pul bo'lmagan sonlar
@pytest.mark.parametrize(
    "text",
    [
        "Telefon: +998 90 123 45 67",
        "Tel 90 123 45 67",
        "10 000 mAh batareya",
        "12 000 mAh",
        "2 000 soat resurs",
        "1 000 GB",
        "2 TB xotira, 1 000 W quvvat",
        "3 200 MHz, 144 Hz",
        "Model 12345",
        "Indeks 100000",
        "Artikul: 55555",
        "RTX 4060 Dual 8GB, 12345 model",
    ],
)
def test_non_money_numbers_are_not_prices(text: str) -> None:
    assert "PRICE_MISMATCH" not in validate_reply(text, FACTS), text


@pytest.mark.parametrize(
    "text",
    [
        "narxi 3 400 000 so'm",
        "so'm 3 400 000",
        "Telefon +998 90 123 45 67, narxi 3 400 000 so'm",
        "Model 12345, narxi 3 400 000 so'm",
        "narxi 3 400 000",
        "10 000 mAh va narxi 3 400 000 so'm",
    ],
)
def test_invented_amount_is_still_caught(text: str) -> None:
    assert "PRICE_MISMATCH" in validate_reply(text, FACTS), text


# ------------------------------------------------------------------ F6: redaction
def _redacted(text: str) -> str:
    return asyncio.run(redact(MemoryPiiStore(), text))


@pytest.mark.parametrize(
    "text",
    [
        "3500000 so'm",
        "1234567 so'm",
        "1 200 000 - 3 500 000 so'm",
        "8 000 000 - 9 000 000 so'm",
        "narxi 3 500 000 so'm",
        "$3500000",
        "12 345 678 сум",
        "RTX 4060 12345",
    ],
)
def test_amounts_are_not_redacted_as_phones(text: str) -> None:
    assert _redacted(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "+998901234567",
        "998901234567",
        "90 123 45 67",
        "901234567",
        "(90)1234567",
        "8 901 234 56 78",
        "tel: 1234567",
        "+7 912 345-67-89",
    ],
)
def test_phones_are_still_redacted(text: str) -> None:
    out = _redacted(f"Menga yozing: {text} rahmat")
    assert "[PHONE_1]" in out and text not in out


@pytest.mark.parametrize(
    "text",
    [
        "lat 41.3110 lon 69.2405",
        "41.311081, 69.240562",
        "41°18'39.9\"N 69°14'26.0\"E",
        "41.3110° N",
    ],
)
def test_coordinates_are_redacted(text: str) -> None:
    out = _redacted(f"Men shu yerdaman {text} keling")
    assert "[LOCATION_" in out and "41." not in out and "41°" not in out
    assert all(m.kind == "LOCATION" for m in find_pii(text))
