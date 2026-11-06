"""Moslik qoidalari (engineering/17 §6.2): soket, RAM, korpus, cooler, quvvat bloki joyi, disklar."""

from __future__ import annotations

from app.domains.catalog.compatibility.model import Build, Part, normalize_label, version_key
from app.domains.catalog.compatibility.registry import Missing, Outcome, RuleResult, rule

# Quvvat bloki o'lchami: kichik blok katta joyga adapter bilan sig'adi (REVIEW), aksincha — sig'maydi (BLOCK)
PSU_SIZE = {"SFX": 1, "SFX_L": 2, "ATX": 3}


def _ram_modules(b: Build) -> int:
    return sum(int(p.get("module_count")) * p.quantity for p in b.all("RAM"))


@rule("CPU_MB_SOCKET", "BLOCK", requires={"CPU": ("socket",), "MOTHERBOARD": ("socket",)})
def cpu_mb_socket(b: Build) -> RuleResult:
    cpu, mb = b.one("CPU"), b.one("MOTHERBOARD")
    assert cpu and mb
    if cpu.get("socket") != mb.get("socket"):
        yield Outcome(
            facts={"cpu_socket": cpu.get("socket"), "mb_socket": mb.get("socket")},
            parts=(cpu, mb),
            hint={"code": "MATCH_SOCKET", "socket": cpu.get("socket")},
        )


def _cpu_names(cpu: Part) -> set[str]:
    names = {normalize_label(cpu.model_label)}
    # model_label "AMD Ryzen 5 7600" bo'lsa, ro'yxatda "Ryzen 5 7600" ham mos kelsin
    words = cpu.model_label.split(maxsplit=1)
    if len(words) == 2:
        names.add(normalize_label(words[1]))
    return {n for n in names if n}


@rule("BIOS_SUPPORT", "REVIEW_REQUIRED", requires={"CPU": ("socket",), "MOTHERBOARD": ("socket",)})
def bios_support(b: Build) -> RuleResult:
    cpu, mb = b.one("CPU"), b.one("MOTHERBOARD")
    assert cpu and mb
    if cpu.get("socket") != mb.get("socket"):
        return  # soket mos emas — CPU_MB_SOCKET BLOCK beradi, BIOS savoli ortiqcha
    support = mb.get("cpu_support")
    if support is None:
        yield Missing(mb, "cpu_support")
        return
    names = _cpu_names(cpu)
    entry = next((s for s in support if normalize_label(str(s.get("cpu_model", ""))) in names), None)
    if entry is None:
        yield Outcome(facts={"cpu_model": cpu.model_label}, parts=(cpu, mb), reason="not_listed")
        return
    shipped = mb.get("shipped_bios")
    min_bios = str(entry.get("min_bios"))
    if shipped is None:
        yield Outcome(
            facts={"cpu_model": cpu.model_label, "min_bios": min_bios},
            parts=(cpu, mb),
            reason="unknown_shipped",
            hint={"code": "CHECK_BIOS", "min_bios": min_bios},
        )
    elif version_key(min_bios) > version_key(str(shipped)):
        yield Outcome(
            facts={"cpu_model": cpu.model_label, "min_bios": min_bios, "shipped_bios": shipped},
            parts=(cpu, mb),
            reason="update_needed",
            hint={"code": "UPDATE_BIOS", "min_bios": min_bios},
        )


@rule("RAM_TYPE_MB", "BLOCK", requires={"RAM": ("type",), "MOTHERBOARD": ("memory_type",)})
def ram_type_mb(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    for ram in b.all("RAM"):
        if ram.get("type") != mb.get("memory_type"):
            yield Outcome(
                facts={"ram_type": ram.get("type"), "mb_type": mb.get("memory_type")},
                parts=(ram, mb),
                hint={"code": "MATCH_RAM_TYPE", "type": mb.get("memory_type")},
            )


@rule("RAM_TYPE_CPU", "BLOCK", requires={"RAM": ("type",), "CPU": ("memory_types",)})
def ram_type_cpu(b: Build) -> RuleResult:
    cpu = b.one("CPU")
    assert cpu
    supported = list(cpu.get("memory_types"))
    for ram in b.all("RAM"):
        if ram.get("type") not in supported:
            yield Outcome(facts={"ram_type": ram.get("type"), "cpu_types": supported}, parts=(ram, cpu))


@rule("RAM_FORM_FACTOR", "BLOCK", requires={"RAM": ("form_factor",)})
def ram_form_factor(b: Build) -> RuleResult:
    for ram in b.all("RAM"):
        if ram.get("form_factor") != "DIMM":
            yield Outcome(facts={"form_factor": ram.get("form_factor")}, parts=(ram,))


@rule("RAM_SLOTS", "BLOCK", requires={"RAM": ("module_count",), "MOTHERBOARD": ("memory_slots",)})
def ram_slots(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    modules, slots = _ram_modules(b), int(mb.get("memory_slots"))
    if modules > slots:
        yield Outcome(facts={"modules": modules, "slots": slots}, parts=(*b.all("RAM"), mb))


@rule(
    "RAM_CAPACITY",
    "BLOCK",
    requires={"RAM": ("module_count", "capacity_per_module_gb"), "MOTHERBOARD": ("max_memory_gb",)},
)
def ram_capacity(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    total = sum(
        int(p.get("module_count")) * int(p.get("capacity_per_module_gb")) * p.quantity for p in b.all("RAM")
    )
    limit = int(mb.get("max_memory_gb"))
    if total > limit:
        yield Outcome(facts={"total_gb": total, "max_gb": limit}, parts=(*b.all("RAM"), mb))


@rule(
    "MB_CASE_FORM_FACTOR",
    "BLOCK",
    requires={"MOTHERBOARD": ("form_factor",), "CASE": ("supported_mb_form_factors",)},
)
def mb_case_form_factor(b: Build) -> RuleResult:
    mb, case = b.one("MOTHERBOARD"), b.one("CASE")
    assert mb and case
    supported = list(case.get("supported_mb_form_factors"))
    if mb.get("form_factor") not in supported:
        yield Outcome(
            facts={"mb_form_factor": mb.get("form_factor"), "case_form_factors": supported},
            parts=(mb, case),
            hint={"code": "BIGGER_CASE", "form_factor": mb.get("form_factor")},
        )


@rule("GPU_CASE_LENGTH", "BLOCK", requires={"GPU": ("length_mm",), "CASE": ("max_gpu_length_mm",)})
def gpu_case_length(b: Build) -> RuleResult:
    case = b.one("CASE")
    assert case
    limit = int(case.get("max_gpu_length_mm"))
    for gpu in b.all("GPU"):
        if int(gpu.get("length_mm")) > limit:
            yield Outcome(
                facts={"gpu_length_mm": gpu.get("length_mm"), "max_gpu_length_mm": limit},
                parts=(gpu, case),
                hint={"code": "CASE_GPU_LENGTH", "min_mm": gpu.get("length_mm")},
            )


@rule("COOLER_SOCKET", "BLOCK", requires={"CPU": ("socket",), "CPU_COOLER": ("supported_sockets",)})
def cooler_socket(b: Build) -> RuleResult:
    cpu, cooler = b.one("CPU"), b.one("CPU_COOLER")
    assert cpu and cooler
    supported = list(cooler.get("supported_sockets"))
    if cpu.get("socket") not in supported:
        yield Outcome(
            facts={"cpu_socket": cpu.get("socket"), "cooler_sockets": supported}, parts=(cpu, cooler)
        )


@rule(
    "COOLER_HEIGHT_CASE", "BLOCK", requires={"CPU_COOLER": ("type",), "CASE": ("max_cpu_cooler_height_mm",)}
)
def cooler_height_case(b: Build) -> RuleResult:
    cooler, case = b.one("CPU_COOLER"), b.one("CASE")
    assert cooler and case
    if cooler.get("type") != "AIR":
        return
    height = cooler.get("height_mm")
    if height is None:
        yield Missing(cooler, "height_mm")
        return
    limit = int(case.get("max_cpu_cooler_height_mm"))
    if int(height) > limit:
        yield Outcome(facts={"cooler_height_mm": height, "max_cooler_height_mm": limit}, parts=(cooler, case))


@rule("AIO_RADIATOR_CASE", "BLOCK", requires={"CPU_COOLER": ("type",), "CASE": ()})
def aio_radiator_case(b: Build) -> RuleResult:
    cooler, case = b.one("CPU_COOLER"), b.one("CASE")
    assert cooler and case
    if cooler.get("type") != "AIO":
        return
    radiator, support = cooler.get("radiator_mm"), case.get("radiator_support_mm")
    if radiator is None:
        yield Missing(cooler, "radiator_mm")
    if support is None:
        yield Missing(case, "radiator_support_mm")
    if radiator is not None and support is not None and int(radiator) not in [int(s) for s in support]:
        yield Outcome(facts={"radiator_mm": radiator, "case_radiators": list(support)}, parts=(cooler, case))


@rule("PSU_CASE_FORM_FACTOR", "BLOCK", requires={"PSU": ("form_factor",), "CASE": ("psu_form_factor",)})
def psu_case_form_factor(b: Build) -> RuleResult:
    psu, case = b.one("PSU"), b.one("CASE")
    assert psu and case
    psu_size, slot_size = PSU_SIZE[psu.get("form_factor")], PSU_SIZE[case.get("psu_form_factor")]
    facts = {"psu_form_factor": psu.get("form_factor"), "case_psu_form_factor": case.get("psu_form_factor")}
    if psu_size > slot_size:
        yield Outcome(facts=facts, parts=(psu, case), reason="too_big")
    elif psu_size < slot_size:
        yield Outcome(facts=facts, parts=(psu, case), severity="REVIEW_REQUIRED", reason="adapter")


@rule("PSU_CASE_LENGTH", "WARNING", requires={"PSU": ("length_mm",), "CASE": ("max_psu_length_mm",)})
def psu_case_length(b: Build) -> RuleResult:
    psu, case = b.one("PSU"), b.one("CASE")
    assert psu and case
    if int(psu.get("length_mm")) > int(case.get("max_psu_length_mm")):
        yield Outcome(
            facts={"psu_length_mm": psu.get("length_mm"), "max_psu_length_mm": case.get("max_psu_length_mm")},
            parts=(psu, case),
        )


def _drive_slot(drive: Part) -> str | None:
    """M.2 disk ona platadagi M.2 slotni, 2.5"/3.5" disk SATA portni egallaydi; aniqlab bo'lmasa — None."""
    form_factor, interface = drive.get("form_factor"), drive.get("interface")
    if isinstance(form_factor, str) and form_factor.startswith("M2_"):
        return "M2"
    if isinstance(form_factor, str) and form_factor.startswith("SATA_"):
        return "SATA"
    if interface == "NVME":
        return "M2"
    return None  # SATA interfeysi M.2 ham, 2.5" ham bo'lishi mumkin — form_factor kerak


def _unique(parts: list[Part]) -> list[Part]:
    seen: list[Part] = []
    for part in parts:
        if not any(part is s for s in seen):
            seen.append(part)
    return seen


def _drives(b: Build, slot: str) -> tuple[list[Part], list[Missing]]:
    found: list[Part] = []
    missing: list[Missing] = []
    for drive in b.all("STORAGE"):
        kind = _drive_slot(drive)
        if kind is None:
            missing.append(Missing(drive, "form_factor"))
        elif kind == slot:
            found.extend([drive] * drive.quantity)
    return found, missing


@rule("STORAGE_M2_SLOTS", "BLOCK", requires={"STORAGE": (), "MOTHERBOARD": ("m2_slots",)})
def storage_m2_slots(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    drives, missing = _drives(b, "M2")
    yield from missing
    if len(drives) > int(mb.get("m2_slots")):
        yield Outcome(
            facts={"drives": len(drives), "slots": mb.get("m2_slots")}, parts=(*_unique(drives), mb)
        )


@rule("STORAGE_SATA_PORTS", "BLOCK", requires={"STORAGE": (), "MOTHERBOARD": ("sata_ports",)})
def storage_sata_ports(b: Build) -> RuleResult:
    mb = b.one("MOTHERBOARD")
    assert mb
    drives, missing = _drives(b, "SATA")
    yield from missing
    if len(drives) > int(mb.get("sata_ports")):
        yield Outcome(
            facts={"drives": len(drives), "ports": mb.get("sata_ports")}, parts=(*_unique(drives), mb)
        )
