"""Qoidalar reyestri (engineering/17 §6): har qoida — toza funksiya + metadata.

`requires` — qoida ishlashi uchun kerakli atributlar. Ulardan biri noma'lum bo'lsa qoida bajarilmaydi va
`MISSING_ATTRIBUTE` (REVIEW_REQUIRED) qo'yiladi; WARNING/INFO qoidalar esa jimgina o'tkaziladi — ular natijaga
ta'sir qilmaydi. Shartli atributlar (cooler turi, disk turi) qoida ichida `Missing` bilan qaytariladi.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.domains.catalog.compatibility.model import Build, Part
from app.shared.contracts.compatibility import Severity


@dataclass(frozen=True)
class Outcome:
    """Qoida buzildi. `severity` — standartdan farq qilsa (masalan, adapter bilan → REVIEW)."""

    facts: dict[str, Any] = field(default_factory=dict)
    parts: tuple[Part, ...] = ()
    severity: Severity | None = None
    reason: str | None = None  # xabar kaliti qo'shimchasi: compat.rules.<ID>.<reason>
    hint: dict[str, Any] | None = None


@dataclass(frozen=True)
class Missing:
    part: Part
    attribute: str


RuleResult = Iterable[Outcome | Missing]


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    fn: Callable[[Build], RuleResult]
    requires: dict[str, tuple[str, ...]]
    full_build_only: bool


RULES: list[Rule] = []


def rule(
    rule_id: str,
    severity: Severity,
    *,
    requires: dict[str, tuple[str, ...]] | None = None,
    full_build_only: bool = False,
) -> Callable[[Callable[[Build], RuleResult]], Callable[[Build], RuleResult]]:
    def register(fn: Callable[[Build], RuleResult]) -> Callable[[Build], RuleResult]:
        if any(r.id == rule_id for r in RULES):
            raise ValueError(f"Duplicate rule id {rule_id}")
        RULES.append(Rule(rule_id, severity, fn, requires or {}, full_build_only))
        return fn

    return register
