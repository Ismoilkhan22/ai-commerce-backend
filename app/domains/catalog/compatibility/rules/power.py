"""Quvvat qoidalari (engineering/17 §6.3)."""

from __future__ import annotations

from app.domains.catalog.compatibility.model import POWER_OVERHEAD_W, Build, Part
from app.domains.catalog.compatibility.power import estimate_power_w, headroom_target_w, round_up_psu
from app.domains.catalog.compatibility.registry import Missing, Outcome, RuleResult, rule

# 12VHPWR va yangi 12V-2x6 bir xil 16-pin ulagich (12V-2x6 orqaga mos)
HIGH_POWER = ("12VHPWR", "12V_2X6")
# 16-pin ulagichni 8-pin'lardan adapter bilan olish uchun kamida shuncha 8-pin kerak
# (hujjat: 2×8-pin → 12VHPWR)
ADAPTER_8PIN_PER_16PIN = 2


def _power_missing(b: Build) -> list[Missing]:
    missing: list[Missing] = []
    cpu = b.one("CPU")
    if cpu is not None and cpu.linked and cpu.get("max_power_w") is None:
        missing.append(Missing(cpu, "max_power_w"))
    for gpu in b.all("GPU"):
        if gpu.linked and gpu.get("board_power_w") is None:
            missing.append(Missing(gpu, "board_power_w"))
    return missing


def _unlinked_power_part(b: Build) -> bool:
    return any(not p.linked for p in (*b.all("CPU"), *b.all("GPU")))


def _known_draw_floor(b: Build) -> int | None:
    """Bog'langan qismlar bo'yicha iste'molning pastki chegarasi (bog'lanmagan GPU faqat qo'shadi)."""
    cpu = b.one("CPU")
    if cpu is None or not cpu.linked or cpu.get("max_power_w") is None:
        return None
    total = int(cpu.get("max_power_w")) + POWER_OVERHEAD_W
    for gpu in b.units("GPU"):
        if not gpu.linked:
            continue
        if gpu.get("board_power_w") is None:
            return None
        total += int(gpu.get("board_power_w"))
    return total


@rule("PSU_WATTAGE", "BLOCK", requires={"PSU": ("wattage_w",), "CPU": ()})
def psu_wattage(b: Build) -> RuleResult:
    psu = b.one("PSU")
    assert psu
    if _unlinked_power_part(b):
        # Noma'lum qism bor: bog'langanlarning o'zi ham sig'masa — baribir BLOCK (QA 6a F2)
        floor = _known_draw_floor(b)
        wattage = int(psu.get("wattage_w"))
        if floor is not None and wattage < floor:
            yield Outcome(
                facts={"psu_w": wattage, "estimated_w": floor},
                parts=(psu, *b.all("CPU"), *b.all("GPU")),
                hint={"code": "PSU_MIN_WATTAGE", "min_w": round_up_psu(floor)},
            )
        return
    missing = _power_missing(b)
    if missing:
        yield from missing
        return
    draw = estimate_power_w(b)
    assert draw is not None
    wattage = int(psu.get("wattage_w"))
    if wattage < draw:
        yield Outcome(
            facts={"psu_w": wattage, "estimated_w": draw},
            parts=(psu, *b.all("CPU"), *b.all("GPU")),
            hint={"code": "PSU_MIN_WATTAGE", "min_w": round_up_psu(draw)},
        )


@rule("PSU_HEADROOM", "REVIEW_REQUIRED", requires={"PSU": ("wattage_w",), "CPU": ()})
def psu_headroom(b: Build) -> RuleResult:
    psu = b.one("PSU")
    assert psu
    if _unlinked_power_part(b):
        return
    missing = _power_missing(b)
    missing += [Missing(g, "recommended_psu_w") for g in b.all("GPU") if g.get("recommended_psu_w") is None]
    if missing:
        yield from missing
        return
    target = headroom_target_w(b)
    assert target is not None
    wattage = int(psu.get("wattage_w"))
    draw = estimate_power_w(b)
    if draw is not None and wattage >= draw and wattage < target:  # yetmasa — PSU_WATTAGE BLOCK beradi
        yield Outcome(
            facts={"psu_w": wattage, "recommended_w": round_up_psu(target), "estimated_w": draw},
            parts=(psu, *b.all("GPU")),
            hint={"code": "PSU_RECOMMENDED_WATTAGE", "min_w": round_up_psu(target)},
        )


def _connector_counts(part: Part, attribute: str) -> dict[str, int]:
    counts = {"PCIE_6PIN": 0, "PCIE_8PIN": 0, "HIGH": 0}
    for connector in part.get(attribute) or []:
        kind = connector.get("type")
        key = "HIGH" if kind in HIGH_POWER else kind
        if key in counts:
            counts[key] += int(connector.get("count", 1))
    return counts


@rule("PSU_GPU_CONNECTORS", "BLOCK", requires={"GPU": ("power_connectors",), "PSU": ("connectors",)})
def psu_gpu_connectors(b: Build) -> RuleResult:
    psu = b.one("PSU")
    assert psu
    need = {"PCIE_6PIN": 0, "PCIE_8PIN": 0, "HIGH": 0}
    for gpu in b.units("GPU"):
        for key, value in _connector_counts(gpu, "power_connectors").items():
            need[key] += value
    have = _connector_counts(psu, "connectors")
    # 8-pin (6+2) 6-pin o'rnida ham ishlaydi; avval to'g'ridan-to'g'ri ehtiyojlar, keyin adapter
    spare_8 = have["PCIE_8PIN"] - need["PCIE_8PIN"]
    spare_8 -= max(0, need["PCIE_6PIN"] - have["PCIE_6PIN"])
    missing_high = max(0, need["HIGH"] - have["HIGH"])
    facts = {
        "need_8pin": need["PCIE_8PIN"],
        "need_6pin": need["PCIE_6PIN"],
        "need_16pin": need["HIGH"],
        "have_8pin": have["PCIE_8PIN"],
        "have_6pin": have["PCIE_6PIN"],
        "have_16pin": have["HIGH"],
    }
    parts = (psu, *b.all("GPU"))
    if spare_8 < 0:
        yield Outcome(facts=facts, parts=parts, reason="missing", hint={"code": "PSU_CONNECTORS"})
    elif missing_high and spare_8 >= missing_high * ADAPTER_8PIN_PER_16PIN:
        yield Outcome(
            facts=facts,
            parts=parts,
            severity="REVIEW_REQUIRED",
            reason="adapter",
            hint={"code": "PSU_NATIVE_16PIN"},
        )
    elif missing_high:
        yield Outcome(facts=facts, parts=parts, reason="missing", hint={"code": "PSU_CONNECTORS"})


@rule("COOLER_TDP", "WARNING", requires={"CPU_COOLER": ("tdp_rating_w",), "CPU": ("base_power_w",)})
def cooler_tdp(b: Build) -> RuleResult:
    cooler, cpu = b.one("CPU_COOLER"), b.one("CPU")
    assert cooler and cpu
    if int(cooler.get("tdp_rating_w")) < int(cpu.get("base_power_w")):
        yield Outcome(
            facts={"cooler_tdp_w": cooler.get("tdp_rating_w"), "cpu_base_w": cpu.get("base_power_w")},
            parts=(cooler, cpu),
        )
