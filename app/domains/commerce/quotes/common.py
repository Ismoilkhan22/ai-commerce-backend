"""Lead va taklif uchun umumiy yordamchilar: raqamlar, havola tokeni, rol, moslik natijasi, narx nusxasi."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.orders.services.pricing import line_total
from app.domains.commerce.quotes.models.orm import QuoteCompatibilitySnapshot, QuoteLine
from app.domains.commerce.quotes.schemas import CompatibilityOut, FindingOut
from app.shared.compat_text import render_explanation, render_hint
from app.shared.contracts.catalog import SkuSnapshot
from app.shared.contracts.compatibility import CompatibilityResult
from app.shared.i18n.locale import Locale, get_display_locale

PUBLIC_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,64}")  # fullmatch bilan
LEAD_FOLLOWUP_DAYS = 30  # DEC-142 Q2: avtomatik yopilmaydi — vazifa
# Roli PC qismi bo'lmagan toifalar (monitor, sichqoncha, xizmat) — moslik tekshirilmaydi
PC_ROLES = frozenset({"CPU", "MOTHERBOARD", "RAM", "GPU", "STORAGE", "PSU", "CASE", "CPU_COOLER"})


async def next_number(db: AsyncSession, table: str, shop_id: UUID) -> int:
    """Shop ichida ketma-ket raqam (`lead_counters`, `quote_counters`) — shu tranzaksiyada +1."""
    assert table in ("lead_counters", "quote_counters")
    number = (
        await db.execute(
            text(
                f"INSERT INTO commerce.{table} AS c (shop_id, last_number) VALUES (:shop_id, 1) "  # noqa: S608
                "ON CONFLICT (shop_id) DO UPDATE SET last_number = c.last_number + 1 RETURNING last_number"
            ),
            {"shop_id": shop_id},
        )
    ).scalar_one()
    return int(number)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def line_role(spec_category: str | None) -> str:
    return spec_category if spec_category in PC_ROLES else "OTHER"


def apply_line_snapshot(line: QuoteLine, snap: SkuSnapshot, discount_pct: Decimal) -> None:
    """Narx katalogdan, klientdan emas (BL-041). Kafolat ham nusxa (BL-057)."""
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
    line.warranty_months = snap.warranty_months
    line.discount_pct = discount_pct
    line.line_total_uzs_minor = line_total(line.qty, line.unit_price_uzs_minor, discount_pct)


def totals(lines: Sequence[QuoteLine]) -> tuple[int, int, int]:
    """(subtotal, discount, total) — so'mda (tiyin)."""
    subtotal = sum(line.qty * line.unit_price_uzs_minor for line in lines)
    total = sum(line.line_total_uzs_minor for line in lines)
    return subtotal, max(subtotal - total, 0), total


def findings_out(result: CompatibilityResult) -> list[FindingOut]:
    return [
        FindingOut(
            rule_id=f.rule_id,
            severity=f.severity,
            message_key=f.message_key,
            explanation=f.explanation,
            hint=f.hint,
            hint_text=f.hint_text,
            parts=list(f.parts),
        )
        for f in result.findings
    ]


def compat_out(
    result: CompatibilityResult, stage: str = "LIVE", at: datetime | None = None
) -> CompatibilityOut:
    return CompatibilityOut(
        decision=result.decision,
        can_publish=result.can_publish_quote,
        ruleset_version=result.rule_set_version,
        estimated_power_w=result.estimated_power_w,
        recommended_psu_w=result.recommended_psu_w,
        findings=findings_out(result),
        stage=stage,
        checked_at=at,
    )


def snapshot_findings(result: CompatibilityResult) -> list[dict[str, Any]]:
    """Muzlagan natija: qoida, darajasi, kalit, faktlar va dalil (spec versiyasi). Matn saqlanmaydi —
    o'qishda xodim yoki xaridor tilida `message_key` + faktlardan qayta yasaladi (QA 6a F3, 17 §7)."""
    return [
        {
            "rule_id": f.rule_id,
            "severity": f.severity,
            "message_key": f.message_key,
            "facts": f.facts,
            "parts": list(f.parts),
            "hint": f.hint,
            "evidence": [
                {"spec_id": str(e.spec_id), "version": e.version, "source_url": e.source_url}
                for e in f.evidence
            ],
        }
        for f in result.findings
    ]


def _render(item: dict[str, Any], locale: Locale) -> tuple[str, str | None]:
    """Kalit va faktlardan matn; eski snapshot'larda yoki kalit topilmasa — saqlangan matn."""
    key = str(item.get("message_key") or "")
    stored = str(item.get("explanation") or "")
    hint = item.get("hint")
    if not key:
        return stored, item.get("hint_text")
    explanation = render_explanation(key, item.get("facts") or {}, locale)
    if explanation == key and stored:
        explanation = stored
    return explanation, render_hint(hint, locale) or item.get("hint_text")


def snapshot_out(snapshot: QuoteCompatibilitySnapshot, locale: Locale | None = None) -> CompatibilityOut:
    loc = locale or get_display_locale()
    findings: list[FindingOut] = []
    for f in snapshot.findings:
        explanation, hint_text = _render(f, loc)
        findings.append(
            FindingOut(
                rule_id=str(f.get("rule_id")),
                severity=f.get("severity", "INFO"),
                message_key=str(f.get("message_key", "")),
                explanation=explanation,
                hint=f.get("hint"),
                hint_text=hint_text,
                parts=[str(p) for p in f.get("parts", [])],
            )
        )
    return CompatibilityOut(
        decision=snapshot.decision,
        can_publish=snapshot.can_publish,
        ruleset_version=snapshot.ruleset_version,
        estimated_power_w=snapshot.estimated_power_w,
        findings=findings,
        stage=snapshot.stage,
        checked_at=snapshot.checked_at,
    )


def spec_versions(result: CompatibilityResult) -> dict[str, Any]:
    return {
        str(sku): {"spec_id": str(e.spec_id), "version": e.version} for sku, e in result.spec_versions.items()
    }
