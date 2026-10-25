"""Buyurtma qatori narxi: katalog nusxasi (snapshot) va qator summasi (db/commerce.md §8, DEC-133).

Qator summasi = miqdor × so'mdagi narx × (1 − tasdiqlangan chegirma), eng yaqin butun so'mgacha
(0.5 yuqoriga).
Tasdiqlanmagan chegirma summaga kirmaydi — tasdiqlanguncha xaridorga va'da qilinmaydi (DEC-110).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.domains.commerce.orders.models.orm import OrderLine
from app.shared.contracts.catalog import SkuSnapshot
from app.shared.money import MINOR_PER_UNIT

HUNDRED = Decimal(100)


def effective_discount(line: OrderLine) -> Decimal:
    return line.discount_pct if line.discount_approved_by is not None else Decimal(0)


def discount_status(line: OrderLine) -> str:
    if line.discount_pct <= 0:
        return "NONE"
    return "APPROVED" if line.discount_approved_by is not None else "PENDING"


def line_total(qty: int, unit_uzs_minor: int, discount_pct: Decimal) -> int:
    net_tiyin = Decimal(qty) * Decimal(unit_uzs_minor) * (HUNDRED - discount_pct) / HUNDRED
    som = (net_tiyin / MINOR_PER_UNIT).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(som) * MINOR_PER_UNIT


def recompute(line: OrderLine) -> None:
    line.line_total_minor = line_total(line.qty, line.unit_price_uzs_minor, effective_discount(line))


def apply_snapshot(line: OrderLine, snap: SkuSnapshot) -> None:
    """Nom, kod, narx, valyuta, kurs va kafolat — nusxa: katalog keyin o'zgarsa ham qator o'zgarmaydi."""
    assert snap.price_version_id and snap.amount_minor and snap.currency and snap.uzs_amount_minor
    usd = snap.currency == "USD"
    line.product_id = snap.product_id
    line.title_snapshot = snap.title
    line.sku_code_snapshot = snap.sku_code
    line.price_version_id = snap.price_version_id
    line.unit_price_minor = snap.amount_minor
    line.currency = snap.currency
    line.exchange_rate_id = snap.exchange_rate_id if usd else None
    line.exchange_rate_snapshot = snap.exchange_rate if usd else None
    line.unit_price_uzs_minor = snap.uzs_amount_minor
    line.warranty_months = snap.warranty_months  # BL-057, DEC-114
    recompute(line)


def usable(snap: SkuSnapshot | None) -> bool:
    """Buyurtmaga qo'shsa bo'ladi: saytda chiqarilgan, faol, narxi bor (dollar bo'lsa — kurs ham)."""
    return (
        snap is not None
        and snap.sellable
        and snap.price_version_id is not None
        and snap.uzs_amount_minor is not None
    )
