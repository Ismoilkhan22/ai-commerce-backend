"""Engine: qoidalarni yig'maga qo'llaydi va natijani yig'adi (engineering/17 §3, §6, §7).

Toza funksiya: DB'ga yozmaydi, vaqt va tasodifga bog'liq emas — bir xil kirish, bir xil natija.
Yig'ish: birorta BLOCK → BLOCK; aks holda birorta REVIEW_REQUIRED → REVIEW_REQUIRED; aks holda PASS.
"""

from __future__ import annotations

# Qoidalar modullari import qilinganda reyestrga yoziladi — tartib natijadagi tartib
from app.domains.catalog.compatibility.model import RULESET_VERSION, Build, Part
from app.domains.catalog.compatibility.power import estimate_power_w, recommended_psu_w
from app.domains.catalog.compatibility.registry import RULES, Missing, Outcome, Rule
from app.domains.catalog.compatibility.rules import advisory, completeness, fit, power  # noqa: F401
from app.shared.compat_text import render_explanation, render_hint
from app.shared.contracts.compatibility import CompatibilityResult, Decision, Evidence, Finding, Severity
from app.shared.i18n.locale import Locale

DECISION_SEVERITIES: tuple[Severity, ...] = ("BLOCK", "REVIEW_REQUIRED")
MISSING_RULE_ID = "MISSING_ATTRIBUTE"


def _evidence(parts: tuple[Part, ...]) -> tuple[Evidence, ...]:
    items: list[Evidence] = []
    for part in parts:
        if part.spec_id is not None and part.spec_version is not None:
            ev = Evidence(part.spec_id, part.spec_version, part.source_url)
            if ev not in items:
                items.append(ev)
    return tuple(items)


def _finding(build: Build, rule_id: str, severity: Severity, outcome: Outcome, locale: Locale) -> Finding:
    key = f"compat.rules.{rule_id}" + (f".{outcome.reason}" if outcome.reason else "")
    explanation = render_explanation(key, outcome.facts, locale)
    hint_text = render_hint(outcome.hint, locale)
    facts = dict(outcome.facts)
    if outcome.reason:
        facts["reason"] = outcome.reason
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message_key=key,
        explanation=explanation,
        facts=facts,
        parts=tuple(build.ref(p) for p in outcome.parts),
        evidence=_evidence(outcome.parts),
        hint=outcome.hint,
        hint_text=hint_text,
    )


def _applicable(build: Build, rule: Rule) -> tuple[Build | None, list[Missing]]:
    """Qoida qaysi qismlarda ishlaydi va qaysi atributlar noma'lum (QA 6a F2).

    Kerakli toifada bog'lanmagan qism bo'lsa: qaror qoidalari (BLOCK/REVIEW) **bog'langan qismlarda**
    baribir ishlaydi — ma'lum buzilish yashirinmaydi, noma'lum qism UNLINKED_PART (REVIEW) bilan belgilanadi.
    Bog'lanmagan qism faqat ehtiyojni oshiradi (modul, disk, quvvat), shuning uchun bog'langanlarda topilgan
    BLOCK haqiqiy. WARNING/INFO qoidalar esa bunday holatda o'tkaziladi (yolg'on ogohlantirish bo'lmasin).
    Kerakli toifada birorta ham bog'langan qism yo'q bo'lsa — qoida qo'llanmaydi.
    """
    view = build
    if any(not p.linked for p in build.parts if p.category in rule.requires):
        if rule.severity not in DECISION_SEVERITIES:
            return None, []
        view = Build(
            tuple(p for p in build.parts if p.linked or p.category not in rule.requires), build.full_build
        )
    missing: list[Missing] = []
    for category, attributes in rule.requires.items():
        parts = view.all(category)
        if not parts:
            return None, []
        missing += [Missing(p, a) for p in parts for a in attributes if p.get(a) is None]
    return view, missing


def check(build: Build, locale: Locale = "uz") -> CompatibilityResult:
    findings: list[Finding] = []
    missing: dict[tuple[str, str], tuple[Part, list[str]]] = {}

    def note_missing(item: Missing, rule: Rule) -> None:
        if rule.severity not in DECISION_SEVERITIES:
            return  # WARNING/INFO: ma'lumot yo'q — ogohlantirish ham yo'q, natijaga ta'sir qilmaydi
        if not item.part.linked:
            return  # UNLINKED_PART allaqachon REVIEW_REQUIRED
        key = (build.ref(item.part), item.attribute)
        missing.setdefault(key, (item.part, []))[1].append(rule.id)

    for rule in RULES:
        if rule.full_build_only and not build.full_build:
            continue
        view, absent = _applicable(build, rule)
        if view is None:
            continue
        if absent:
            for item in absent:
                note_missing(item, rule)
            continue
        for outcome in rule.fn(view):
            if isinstance(outcome, Missing):
                note_missing(outcome, rule)
            else:
                findings.append(_finding(build, rule.id, outcome.severity or rule.severity, outcome, locale))

    for (_, attribute), (part, rule_ids) in missing.items():
        outcome = Outcome(
            facts={"category": part.category, "attribute": attribute, "rules": sorted(set(rule_ids))},
            parts=(part,),
        )
        findings.append(_finding(build, MISSING_RULE_ID, "REVIEW_REQUIRED", outcome, locale))

    decision: Decision = "PASS"
    if any(f.severity == "BLOCK" for f in findings):
        decision = "BLOCK"
    elif any(f.severity == "REVIEW_REQUIRED" for f in findings):
        decision = "REVIEW_REQUIRED"
    versions = {
        p.sku_id: Evidence(p.spec_id, p.spec_version, p.source_url)
        for p in build.parts
        if p.sku_id is not None and p.spec_id is not None and p.spec_version is not None
    }
    return CompatibilityResult(
        rule_set_version=RULESET_VERSION,
        decision=decision,
        can_publish_quote=decision == "PASS",
        full_build=build.full_build,
        findings=tuple(findings),
        estimated_power_w=estimate_power_w(build),
        recommended_psu_w=recommended_psu_w(build),
        checked_sku_ids=tuple(p.sku_id for p in build.parts if p.sku_id is not None),
        spec_versions=versions,
    )
