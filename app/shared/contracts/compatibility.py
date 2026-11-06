"""PC moslik tekshiruvi kontrakti (engineering/17 §7).

Engine `catalog` domenida (`app/domains/catalog/compatibility`), natija turlari shu yerda.
`commerce/quotes` va `sales_ai` ularni `CatalogQueryPort.check_compatibility` orqali oladi,
`catalog` kodini import qilmasdan (ADR-032).
Natija qiymatlari K-09: PASS / REVIEW_REQUIRED / BLOCK. WARNING va INFO natijaga ta'sir qilmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

Severity = Literal["BLOCK", "REVIEW_REQUIRED", "WARNING", "INFO"]
Decision = Literal["PASS", "REVIEW_REQUIRED", "BLOCK"]


@dataclass(frozen=True)
class BuildLine:
    """Yig'madagi bitta qator: shop SKU'si va soni (masalan, 2 ta bir xil SSD)."""

    sku_id: UUID
    quantity: int = 1


@dataclass(frozen=True)
class Evidence:
    """Natija qaysi spec versiyasidan chiqqani (BL-030)."""

    spec_id: UUID
    version: int
    source_url: str | None = None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    message_key: str  # backend locales: compat.rules.<RULE_ID>[.<reason>]
    explanation: str  # message_key so'ralgan tilda; AI uni ma'nosini o'zgartirmasdan aytadi
    facts: dict[str, Any] = field(default_factory=dict)
    parts: tuple[str, ...] = ()  # qatnashgan qismlar: SKU id yoki "CATEGORY#n"
    evidence: tuple[Evidence, ...] = ()
    hint: dict[str, Any] | None = None  # tuzatish taklifi ma'lumot sifatida: {"code": "PSU_MIN_WATTAGE", ...}
    hint_text: str | None = None


@dataclass(frozen=True)
class CompatibilityResult:
    rule_set_version: str
    decision: Decision
    can_publish_quote: bool
    full_build: bool  # to'liq PC yig'mami yoki faqat qismlar (REQUIRED_PARTS va h.k. faqat to'liqda)
    findings: tuple[Finding, ...]
    estimated_power_w: int | None  # noma'lum quvvat — None, hech qachon 0 emas
    recommended_psu_w: int | None
    checked_sku_ids: tuple[UUID, ...] = ()
    ignored_sku_ids: tuple[
        UUID, ...
    ] = ()  # PC qismi bo'lmagan toifalar (monitor, sichqoncha) — tekshirilmaydi
    spec_versions: dict[UUID, Evidence] = field(default_factory=dict)
