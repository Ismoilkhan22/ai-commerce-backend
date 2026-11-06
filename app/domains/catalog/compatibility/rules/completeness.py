"""To'liqlik qoidalari (engineering/17 §6.1)."""

from __future__ import annotations

from app.domains.catalog.compatibility.model import REQUIRED_CATEGORIES, Build
from app.domains.catalog.compatibility.registry import Missing, Outcome, RuleResult, rule

# Bir yig'mada bittadan ortiq bo'lishi mumkin emas.
# Hujjatda CPU, ona plata va PSU; korpus va cooler ham qo'shildi
SINGLE_CATEGORIES = ("CPU", "MOTHERBOARD", "PSU", "CASE", "CPU_COOLER")


@rule("REQUIRED_PARTS", "BLOCK", full_build_only=True)
def required_parts(b: Build) -> RuleResult:
    missing = [category for category in REQUIRED_CATEGORIES if b.count(category) == 0]
    if missing:
        yield Outcome(facts={"missing": missing}, hint={"code": "ADD_PARTS", "categories": missing})


@rule("DISPLAY_OUTPUT", "BLOCK", full_build_only=True)
def display_output(b: Build) -> RuleResult:
    cpu = b.one("CPU")
    if cpu is None or b.count("GPU") > 0 or not cpu.linked:
        return
    graphics = cpu.get("integrated_graphics")
    if graphics is None:
        yield Missing(cpu, "integrated_graphics")
    elif graphics is False:
        yield Outcome(parts=(cpu,), hint={"code": "ADD_GPU"})


@rule("CPU_COOLER_PRESENT", "BLOCK", full_build_only=True)
def cpu_cooler_present(b: Build) -> RuleResult:
    cpu = b.one("CPU")
    if cpu is None or b.count("CPU_COOLER") > 0 or not cpu.linked:
        return
    included = cpu.get("cooler_included")
    if included is None:
        yield Missing(cpu, "cooler_included")
    elif included is False:
        yield Outcome(parts=(cpu,), hint={"code": "ADD_COOLER"})


@rule("DUPLICATE_PART", "BLOCK")
def duplicate_part(b: Build) -> RuleResult:
    for category in SINGLE_CATEGORIES:
        if b.count(category) > 1:
            yield Outcome(
                facts={"category": category, "count": b.count(category)}, parts=tuple(b.all(category))
            )


@rule("UNLINKED_PART", "REVIEW_REQUIRED")
def unlinked_part(b: Build) -> RuleResult:
    for part in b.parts:
        if not part.linked:
            yield Outcome(facts={"category": part.category}, parts=(part,), hint={"code": "LINK_SPEC"})
