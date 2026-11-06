"""Ogohlantirishlar (engineering/17 §6.4) — natijaga ta'sir qilmaydi, faqat ko'rsatiladi."""

from __future__ import annotations

from app.domains.catalog.compatibility.model import Build, normalize_label
from app.domains.catalog.compatibility.registry import Outcome, RuleResult, rule


@rule("RAM_SPEED", "WARNING", requires={"RAM": ("speed_mts",), "MOTHERBOARD": ("max_memory_speed_mts",)})
def ram_speed(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    limit = int(mb.get("max_memory_speed_mts"))
    for ram in b.all("RAM"):
        if int(ram.get("speed_mts")) > limit:
            yield Outcome(facts={"ram_speed": ram.get("speed_mts"), "mb_max_speed": limit}, parts=(ram, mb))


@rule("SINGLE_CHANNEL", "WARNING", requires={"RAM": ("module_count",)})
def single_channel(b: Build) -> RuleResult:
    if sum(int(p.get("module_count")) * p.quantity for p in b.all("RAM")) == 1:
        yield Outcome(parts=tuple(b.all("RAM")), hint={"code": "DUAL_CHANNEL"})


@rule("MIXED_RAM_KITS", "WARNING", requires={"RAM": ()})
def mixed_ram_kits(b: Build) -> RuleResult:
    kits = {str(p.spec_id) if p.spec_id else normalize_label(p.model_label) for p in b.all("RAM")}
    if len(kits) > 1:
        yield Outcome(facts={"kits": len(kits)}, parts=tuple(b.all("RAM")))


@rule("NO_UPGRADE_SLOT", "INFO", requires={"RAM": ("module_count",), "MOTHERBOARD": ("memory_slots",)})
def no_upgrade_slot(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    modules = sum(int(p.get("module_count")) * p.quantity for p in b.all("RAM"))
    if modules == int(mb.get("memory_slots")):
        yield Outcome(facts={"slots": modules}, parts=(*b.all("RAM"), mb))
