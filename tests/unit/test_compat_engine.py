"""PC moslik engine'i (engineering/17 §6, §12).

Har qoida — mos / mos emas / noma'lum; real yig'malar; xossalar.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domains.catalog.compatibility import RULESET_VERSION, Build, Part, check, estimate_power_w
from app.domains.catalog.compatibility.model import version_key
from app.domains.catalog.compatibility.power import recommended_psu_w
from app.shared.contracts.compatibility import CompatibilityResult

# ------------------------------------------------------------------ qismlar (bozorda keng tarqalgan)


def part(category: str, label: str = "", *, linked: bool = True, quantity: int = 1, **attrs: Any) -> Part:
    return Part(
        category=category,
        attributes=attrs,
        quantity=quantity,
        sku_id=uuid4(),
        spec_id=uuid4() if linked else None,
        spec_version=1 if linked else None,
        source_url="https://example.com/spec" if linked else None,
        model_label=label,
    )


def ryzen_7600(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "socket": "AM5",
        "memory_types": ["DDR5"],
        "base_power_w": 65,
        "max_power_w": 88,
        "integrated_graphics": True,
        "cooler_included": True,
    }
    return part("CPU", "AMD Ryzen 5 7600", **(attrs | over))


def i5_12400f(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "socket": "LGA1700",
        "memory_types": ["DDR4", "DDR5"],
        "base_power_w": 65,
        "max_power_w": 117,
        "integrated_graphics": False,
        "cooler_included": True,
    }
    return part("CPU", "Intel Core i5-12400F", **(attrs | over))


def b650m(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "socket": "AM5",
        "chipset": "B650",
        "form_factor": "MICRO_ATX",
        "memory_type": "DDR5",
        "memory_slots": 4,
        "max_memory_gb": 192,
        "max_memory_speed_mts": 6400,
        "m2_slots": 2,
        "sata_ports": 4,
        "cpu_support": [{"cpu_model": "Ryzen 5 7600", "min_bios": "7D78v10"}],
        "shipped_bios": "7D78v12",
    }
    return part("MOTHERBOARD", "MSI PRO B650M-A WIFI", **(attrs | over))


def b660_d4(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "socket": "LGA1700",
        "chipset": "B660",
        "form_factor": "ATX",
        "memory_type": "DDR4",
        "memory_slots": 4,
        "max_memory_gb": 128,
        "max_memory_speed_mts": 3200,
        "m2_slots": 2,
        "sata_ports": 4,
        "cpu_support": [{"cpu_model": "Core i5-12400F", "min_bios": "0401"}],
        "shipped_bios": "0820",
    }
    return part("MOTHERBOARD", "ASUS PRIME B660-PLUS D4", **(attrs | over))


def ddr5_kit(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "type": "DDR5",
        "form_factor": "DIMM",
        "module_count": 2,
        "capacity_per_module_gb": 16,
        "speed_mts": 6000,
    }
    return part("RAM", "Kingston FURY Beast 32GB DDR5-6000", **(attrs | over))


def ddr4_kit(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "type": "DDR4",
        "form_factor": "DIMM",
        "module_count": 2,
        "capacity_per_module_gb": 8,
        "speed_mts": 3200,
    }
    return part("RAM", "Kingston FURY Beast 16GB DDR4-3200", **(attrs | over))


def rtx_4060(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "length_mm": 199,
        "board_power_w": 115,
        "recommended_psu_w": 550,
        "power_connectors": [{"type": "PCIE_8PIN", "count": 1}],
    }
    return part("GPU", "MSI RTX 4060 Ventus 2X", **(attrs | over))


def rtx_4070_super(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "length_mm": 261,
        "board_power_w": 220,
        "recommended_psu_w": 650,
        "power_connectors": [{"type": "12VHPWR", "count": 1}],
    }
    return part("GPU", "Gigabyte RTX 4070 SUPER WINDFORCE", **(attrs | over))


def psu(watts: int, *, connectors: list[dict[str, Any]] | None = None, **over: Any) -> Part:
    attrs: dict[str, Any] = {
        "wattage_w": watts,
        "form_factor": "ATX",
        "length_mm": 140,
        "connectors": connectors if connectors is not None else [{"type": "PCIE_8PIN", "count": 2}],
    }
    return part("PSU", f"PSU {watts}W", **(attrs | over))


def atx_case(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "supported_mb_form_factors": ["ATX", "MICRO_ATX", "MINI_ITX"],
        "max_gpu_length_mm": 330,
        "max_cpu_cooler_height_mm": 165,
        "max_psu_length_mm": 180,
        "psu_form_factor": "ATX",
        "radiator_support_mm": [240, 280, 360],
    }
    return part("CASE", "Zalman i3 Neo", **(attrs | over))


def itx_case(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "supported_mb_form_factors": ["MINI_ITX"],
        "max_gpu_length_mm": 300,
        "max_cpu_cooler_height_mm": 70,
        "psu_form_factor": "SFX",
    }
    return part("CASE", "Mini ITX", **(attrs | over))


def ak400(**over: Any) -> Part:
    attrs: dict[str, Any] = {
        "type": "AIR",
        "supported_sockets": ["AM5", "AM4", "LGA1700"],
        "height_mm": 155,
        "tdp_rating_w": 220,
    }
    return part("CPU_COOLER", "DeepCool AK400", **(attrs | over))


def nvme(**over: Any) -> Part:
    attrs: dict[str, Any] = {"interface": "NVME", "form_factor": "M2_2280"}
    return part("STORAGE", "Samsung 990 PRO 1TB", **(attrs | over))


def hdd(**over: Any) -> Part:
    attrs: dict[str, Any] = {"interface": "SATA", "form_factor": "SATA_3_5"}
    return part("STORAGE", "Seagate 2TB", **(attrs | over))


def ryzen_build(**replace: Part | None) -> list[Part]:
    parts: dict[str, Part | None] = {
        "cpu": ryzen_7600(),
        "mb": b650m(),
        "ram": ddr5_kit(),
        "gpu": rtx_4060(),
        "psu": psu(550),
        "case": atx_case(),
        "storage": nvme(),
        "cooler": ak400(),
    }
    parts.update(replace)
    return [p for p in parts.values() if p is not None]


def run(parts: list[Part], *, full_build: bool = True, locale: str = "uz") -> CompatibilityResult:
    return check(Build.of(parts, full_build=full_build), locale)  # type: ignore[arg-type]


def ids(result: CompatibilityResult) -> list[str]:
    return [f.rule_id for f in result.findings]


def find(result: CompatibilityResult, rule_id: str) -> Any:
    matches = [f for f in result.findings if f.rule_id == rule_id]
    assert matches, f"{rule_id} not in {ids(result)}"
    return matches[0]


# ------------------------------------------------------------------ real yig'malar


def test_ryzen_7600_b650_ddr5_rtx4060_passes() -> None:
    result = run(ryzen_build())
    assert result.decision == "PASS", ids(result)
    assert result.can_publish_quote is True
    assert result.rule_set_version == RULESET_VERSION == "pc-2026-10-v2"
    assert result.estimated_power_w == 88 + 115 + 75
    assert result.recommended_psu_w == 550
    assert len(result.spec_versions) == 8


def test_i5_12400f_b660_ddr4_rtx4060_passes() -> None:
    parts = [i5_12400f(), b660_d4(), ddr4_kit(), rtx_4060(), psu(550), atx_case(), nvme(), hdd()]
    result = run(parts)
    assert result.decision == "PASS", ids(result)
    assert result.estimated_power_w == 117 + 115 + 75


def test_rtx4070_super_on_550w_with_8pin_only_needs_review() -> None:
    result = run(ryzen_build(gpu=rtx_4070_super(), cpu=i5_12400f(), mb=b660_d4(), ram=ddr4_kit()))
    assert result.decision == "REVIEW_REQUIRED"
    headroom = find(result, "PSU_HEADROOM")
    assert headroom.hint == {"code": "PSU_RECOMMENDED_WATTAGE", "min_w": 650}
    assert headroom.hint_text == "Kamida 650 W quvvat bloki tavsiya qilinadi."
    connectors = find(result, "PSU_GPU_CONNECTORS")
    assert connectors.severity == "REVIEW_REQUIRED" and connectors.facts["reason"] == "adapter"
    assert "PSU_WATTAGE" not in ids(result)


def test_rtx4070_super_on_650w_with_16pin_passes() -> None:
    supply = psu(650, connectors=[{"type": "12V_2X6", "count": 1}, {"type": "PCIE_8PIN", "count": 2}])
    result = run(ryzen_build(gpu=rtx_4070_super(), psu=supply))
    assert result.decision == "PASS", ids(result)


def test_underpowered_psu_blocks_with_minimum_hint() -> None:
    result = run(
        ryzen_build(gpu=rtx_4070_super(), cpu=i5_12400f(), mb=b660_d4(), ram=ddr4_kit(), psu=psu(350))
    )
    assert result.decision == "BLOCK"
    wattage = find(result, "PSU_WATTAGE")
    assert wattage.facts == {"psu_w": 350, "estimated_w": 412}
    assert wattage.hint == {"code": "PSU_MIN_WATTAGE", "min_w": 450}
    assert "PSU_HEADROOM" not in ids(result)  # yetmaydigan blokka "zaxira kam" deyilmaydi


def test_micro_atx_board_in_itx_case_blocks() -> None:
    result = run(ryzen_build(case=itx_case(max_cpu_cooler_height_mm=170), psu=psu(550, form_factor="SFX")))
    assert result.decision == "BLOCK"
    finding = find(result, "MB_CASE_FORM_FACTOR")
    assert finding.facts["mb_form_factor"] == "MICRO_ATX"
    assert finding.hint == {"code": "BIGGER_CASE", "form_factor": "MICRO_ATX"}


def test_ram_type_mismatch_blocks_on_board_and_cpu() -> None:
    result = run(ryzen_build(ram=ddr4_kit()))
    assert {"RAM_TYPE_MB", "RAM_TYPE_CPU"} <= set(ids(result))
    assert result.decision == "BLOCK"


# ------------------------------------------------------------------ to'liqlik


def test_required_parts_blocks_only_full_builds() -> None:
    parts = ryzen_build(psu=None, case=None)
    result = run(parts)
    assert find(result, "REQUIRED_PARTS").facts["missing"] == ["PSU", "CASE"]
    assert find(result, "REQUIRED_PARTS").explanation == "Yig‘mada yetishmayapti: quvvat bloki, korpus."
    assert "REQUIRED_PARTS" not in ids(run(parts, full_build=False))


def test_display_output_without_igpu_and_gpu() -> None:
    parts = [i5_12400f(), b660_d4(), ddr4_kit(), psu(550), atx_case(), nvme()]
    assert find(run(parts), "DISPLAY_OUTPUT").severity == "BLOCK"
    assert "DISPLAY_OUTPUT" not in ids(run(parts, full_build=False))
    with_igpu = [ryzen_7600(), b650m(), ddr5_kit(), psu(550), atx_case(), nvme()]
    assert "DISPLAY_OUTPUT" not in ids(run(with_igpu))
    unknown = run([i5_12400f(integrated_graphics=None), b660_d4(), ddr4_kit(), psu(550), atx_case(), nvme()])
    assert find(unknown, "MISSING_ATTRIBUTE").facts["attribute"] == "integrated_graphics"


def test_cpu_cooler_present() -> None:
    tray = ryzen_7600(cooler_included=False)
    assert find(run(ryzen_build(cpu=tray, cooler=None)), "CPU_COOLER_PRESENT").severity == "BLOCK"
    assert "CPU_COOLER_PRESENT" not in ids(run(ryzen_build(cpu=tray)))
    missing = run(ryzen_build(cpu=ryzen_7600(cooler_included=None), cooler=None))
    assert find(missing, "MISSING_ATTRIBUTE").facts["attribute"] == "cooler_included"


def test_duplicate_cpu_or_psu_blocks() -> None:
    result = run([*ryzen_build(), ryzen_7600()])
    assert find(result, "DUPLICATE_PART").facts == {"category": "CPU", "count": 2}
    doubled = run(ryzen_build(psu=psu(550, quantity=2)))
    assert find(doubled, "DUPLICATE_PART").facts["category"] == "PSU"


def test_unlinked_part_needs_review_without_missing_noise() -> None:
    unlinked_gpu = Part(category="GPU", sku_id=uuid4())
    result = run(ryzen_build(gpu=unlinked_gpu))
    assert result.decision == "REVIEW_REQUIRED"
    assert find(result, "UNLINKED_PART").hint == {"code": "LINK_SPEC"}
    assert "MISSING_ATTRIBUTE" not in ids(result)
    assert "GPU_CASE_LENGTH" not in ids(result)
    assert result.estimated_power_w is None  # GPU quvvati noma'lum — taxmin qilinmaydi


# ------------------------------------------------------------------ moslik


def test_cpu_mb_socket() -> None:
    result = run(ryzen_build(mb=b660_d4(), ram=ddr4_kit()))
    socket = find(result, "CPU_MB_SOCKET")
    assert socket.facts == {"cpu_socket": "AM5", "mb_socket": "LGA1700"}
    assert socket.explanation == "Protsessor soketi (AM5) ona plata soketiga (LGA1700) mos emas."
    assert "BIOS_SUPPORT" not in ids(result)


def test_missing_socket_is_one_missing_finding_for_all_rules() -> None:
    result = run(ryzen_build(cpu=ryzen_7600(socket=None)))
    missing = [f for f in result.findings if f.rule_id == "MISSING_ATTRIBUTE"]
    assert len(missing) == 1
    assert missing[0].facts["rules"] == ["BIOS_SUPPORT", "COOLER_SOCKET", "CPU_MB_SOCKET"]
    assert result.decision == "REVIEW_REQUIRED"


def test_bios_support_variants() -> None:
    not_listed = run(
        ryzen_build(mb=b650m(cpu_support=[{"cpu_model": "Ryzen 7 9700X", "min_bios": "7D78v20"}]))
    )
    assert find(not_listed, "BIOS_SUPPORT").facts["reason"] == "not_listed"
    unknown = run(ryzen_build(mb=b650m(shipped_bios=None)))
    assert find(unknown, "BIOS_SUPPORT").facts["reason"] == "unknown_shipped"
    old = run(ryzen_build(mb=b650m(shipped_bios="7D78v9")))
    bios = find(old, "BIOS_SUPPORT")
    assert bios.facts["reason"] == "update_needed"
    assert bios.hint == {"code": "UPDATE_BIOS", "min_bios": "7D78v10"}
    no_list = run(ryzen_build(mb=b650m(cpu_support=None)))
    assert find(no_list, "MISSING_ATTRIBUTE").facts["attribute"] == "cpu_support"
    assert all(r.decision == "REVIEW_REQUIRED" for r in (not_listed, unknown, old, no_list))


def test_bios_version_ordering_is_natural() -> None:
    assert version_key("F9") < version_key("F20")
    assert version_key("1.9") < version_key("1.10")
    assert version_key("7D78v10") > version_key("7D78v9")
    assert version_key("0401") < version_key("0820")


def test_ram_form_factor_slots_and_capacity() -> None:
    so_dimm = run(ryzen_build(ram=ddr5_kit(form_factor="SO_DIMM")))
    assert find(so_dimm, "RAM_FORM_FACTOR").severity == "BLOCK"
    too_many = run(ryzen_build(mb=b650m(memory_slots=2), ram=ddr5_kit(quantity=2)))
    assert find(too_many, "RAM_SLOTS").facts == {"modules": 4, "slots": 2}
    too_big = run(ryzen_build(ram=ddr5_kit(module_count=4, capacity_per_module_gb=64)))
    assert find(too_big, "RAM_CAPACITY").facts == {"total_gb": 256, "max_gb": 192}


def test_gpu_length_vs_case() -> None:
    result = run(ryzen_build(gpu=rtx_4060(length_mm=335), case=atx_case(max_gpu_length_mm=300)))
    finding = find(result, "GPU_CASE_LENGTH")
    assert finding.facts == {"gpu_length_mm": 335, "max_gpu_length_mm": 300}
    assert result.decision == "BLOCK"


def test_cooler_socket_height_and_aio_radiator() -> None:
    assert (
        find(run(ryzen_build(cooler=ak400(supported_sockets=["AM4"]))), "COOLER_SOCKET").severity == "BLOCK"
    )
    tall = run(ryzen_build(case=atx_case(max_cpu_cooler_height_mm=150)))
    assert find(tall, "COOLER_HEIGHT_CASE").facts == {"cooler_height_mm": 155, "max_cooler_height_mm": 150}
    aio = part(
        "CPU_COOLER", "AIO 360", type="AIO", supported_sockets=["AM5"], radiator_mm=360, tdp_rating_w=300
    )
    assert find(run(ryzen_build(cooler=aio, case=atx_case(radiator_support_mm=[240]))), "AIO_RADIATOR_CASE")
    assert "COOLER_HEIGHT_CASE" not in ids(
        run(ryzen_build(cooler=aio, case=atx_case(max_cpu_cooler_height_mm=10)))
    )
    unknown_radiator = part("CPU_COOLER", "AIO", type="AIO", supported_sockets=["AM5"])
    missing = run(ryzen_build(cooler=unknown_radiator))
    assert find(missing, "MISSING_ATTRIBUTE").facts["attribute"] == "radiator_mm"
    unknown_type = run(ryzen_build(cooler=ak400(type=None)))
    assert find(unknown_type, "MISSING_ATTRIBUTE").facts["attribute"] == "type"


def test_psu_case_form_factor() -> None:
    too_big = run(ryzen_build(case=atx_case(psu_form_factor="SFX")))
    assert find(too_big, "PSU_CASE_FORM_FACTOR").severity == "BLOCK"
    adapter = run(ryzen_build(psu=psu(550, form_factor="SFX")))
    finding = find(adapter, "PSU_CASE_FORM_FACTOR")
    assert finding.severity == "REVIEW_REQUIRED" and finding.facts["reason"] == "adapter"
    assert adapter.decision == "REVIEW_REQUIRED"


def test_psu_length_is_only_a_warning() -> None:
    result = run(ryzen_build(psu=psu(550, length_mm=200)))
    assert find(result, "PSU_CASE_LENGTH").severity == "WARNING"
    assert result.decision == "PASS"


def test_storage_slots_and_ports() -> None:
    m2 = run(ryzen_build(storage=nvme(quantity=3)))
    assert find(m2, "STORAGE_M2_SLOTS").facts == {"drives": 3, "slots": 2}
    sata = run([*ryzen_build(), hdd(quantity=5)])
    assert find(sata, "STORAGE_SATA_PORTS").facts == {"drives": 5, "ports": 4}
    m2_sata = part("STORAGE", "M.2 SATA", interface="SATA", form_factor="M2_2280")
    assert run(ryzen_build(storage=m2_sata)).decision == "PASS"  # M.2 SATA disk SATA portni egallamaydi
    ambiguous = run(ryzen_build(storage=part("STORAGE", "SSD", interface="SATA")))
    missing = find(ambiguous, "MISSING_ATTRIBUTE")
    assert missing.facts["attribute"] == "form_factor"
    assert missing.facts["rules"] == ["STORAGE_M2_SLOTS", "STORAGE_SATA_PORTS"]


# ------------------------------------------------------------------ quvvat


def test_power_estimate_and_recommendation() -> None:
    no_gpu = Build.of([ryzen_7600(), b650m()])
    assert estimate_power_w(no_gpu) == 88 + 75
    assert recommended_psu_w(no_gpu) == 250  # 163 × 1.3 = 212 → 250
    two_gpus = Build.of([ryzen_7600(), rtx_4060(quantity=2)])
    assert estimate_power_w(two_gpus) == 88 + 2 * 115 + 75
    assert estimate_power_w(Build.of([ryzen_7600(), rtx_4060(board_power_w=None)])) is None
    assert estimate_power_w(Build.of([rtx_4060()])) is None


def test_power_missing_attributes_are_review() -> None:
    result = run(ryzen_build(gpu=rtx_4060(board_power_w=None)))
    missing = find(result, "MISSING_ATTRIBUTE")
    assert missing.facts["attribute"] == "board_power_w"
    assert missing.facts["rules"] == ["PSU_HEADROOM", "PSU_WATTAGE"]
    no_reco = run(ryzen_build(gpu=rtx_4060(recommended_psu_w=None)))
    assert find(no_reco, "MISSING_ATTRIBUTE").facts == {
        "category": "GPU",
        "attribute": "recommended_psu_w",
        "rules": ["PSU_HEADROOM"],
    }


def test_gpu_connectors() -> None:
    hungry = rtx_4060(power_connectors=[{"type": "PCIE_8PIN", "count": 3}])
    blocked = run(ryzen_build(gpu=hungry, psu=psu(850)))
    assert find(blocked, "PSU_GPU_CONNECTORS").facts["reason"] == "missing"
    six_pin = rtx_4060(power_connectors=[{"type": "PCIE_6PIN", "count": 1}])
    assert "PSU_GPU_CONNECTORS" not in ids(run(ryzen_build(gpu=six_pin)))  # 6+2 pin 6-pin o'rnida ishlaydi
    slot_powered = rtx_4060(power_connectors=[])
    assert "PSU_GPU_CONNECTORS" not in ids(run(ryzen_build(gpu=slot_powered)))
    no_adapter = run(
        ryzen_build(gpu=rtx_4070_super(), psu=psu(750, connectors=[{"type": "PCIE_8PIN", "count": 1}]))
    )
    assert find(no_adapter, "PSU_GPU_CONNECTORS").severity == "BLOCK"
    unknown = run(ryzen_build(psu=_without(psu(550), "connectors")))
    assert find(unknown, "MISSING_ATTRIBUTE").facts["attribute"] == "connectors"


def test_cooler_tdp_warning_does_not_change_decision() -> None:
    result = run(ryzen_build(cooler=ak400(tdp_rating_w=50)))
    assert find(result, "COOLER_TDP").severity == "WARNING"
    assert result.decision == "PASS"


# ------------------------------------------------------------------ ogohlantirishlar


def test_advisory_rules() -> None:
    fast = run(ryzen_build(ram=ddr5_kit(speed_mts=7200)))
    assert find(fast, "RAM_SPEED").facts == {"ram_speed": 7200, "mb_max_speed": 6400}
    single = run(ryzen_build(ram=ddr5_kit(module_count=1)))
    assert find(single, "SINGLE_CHANNEL").hint == {"code": "DUAL_CHANNEL"}
    mixed = run([*ryzen_build(), ddr5_kit()])
    assert find(mixed, "MIXED_RAM_KITS").facts == {"kits": 2}
    full = run(ryzen_build(ram=ddr5_kit(module_count=4)))
    assert find(full, "NO_UPGRADE_SLOT").severity == "INFO"
    assert {r.decision for r in (fast, single, mixed, full)} == {"PASS"}
    # WARNING qoidasi uchun ma'lumot yo'q — topilma ham yo'q, natija o'zgarmaydi
    assert run(ryzen_build(mb=b650m(max_memory_speed_mts=None))).decision == "PASS"


# ------------------------------------------------------------------ tillar va dalil


def test_explanations_follow_locale_and_carry_evidence() -> None:
    parts = ryzen_build(mb=b660_d4(), ram=ddr4_kit())
    ru = find(run(parts, locale="ru"), "CPU_MB_SOCKET")
    en = find(run(parts, locale="en"), "CPU_MB_SOCKET")
    assert ru.explanation.startswith("Сокет процессора (AM5)")
    assert en.explanation == "CPU socket (AM5) does not match motherboard socket (LGA1700)."
    assert ru.message_key == "compat.rules.CPU_MB_SOCKET"
    assert len(ru.evidence) == 2 and ru.evidence[0].version == 1
    assert ru.parts == (str(parts[0].sku_id), str(parts[1].sku_id))


def test_missing_attribute_text_names_category_in_language() -> None:
    finding = find(run(ryzen_build(case=atx_case(max_gpu_length_mm=None)), locale="ru"), "MISSING_ATTRIBUTE")
    assert finding.explanation == (
        "В справочнике нет данных «max_gpu_length_mm» для позиции «корпус» — нужна проверка специалиста."
    )


# ------------------------------------------------------------------ xossalar (17 §12)

POOLS: dict[str, list[Any]] = {
    "CPU": [ryzen_7600, i5_12400f],
    "MOTHERBOARD": [b650m, b660_d4],
    "RAM": [ddr5_kit, ddr4_kit],
    "GPU": [rtx_4060, rtx_4070_super],
    "PSU": [lambda: psu(350), lambda: psu(550), lambda: psu(850, form_factor="SFX")],
    "CASE": [atx_case, itx_case],
    "CPU_COOLER": [ak400],
    "STORAGE": [nvme, hdd],
}


@st.composite
def builds(draw: st.DrawFn) -> list[Part]:
    parts: list[Part] = []
    for category, makers in POOLS.items():
        if category not in ("CPU", "MOTHERBOARD") and draw(st.booleans()) and draw(st.booleans()):
            continue  # ba'zan qism tushib qoladi
        parts.append(draw(st.sampled_from(makers))())
    return parts


def _without(target: Part, attribute: str) -> Part:
    attrs: dict[str, Any] = {k: v for k, v in target.attributes.items() if k != attribute}
    return Part(
        category=target.category,
        attributes=attrs,
        quantity=target.quantity,
        sku_id=target.sku_id,
        spec_id=target.spec_id,
        spec_version=target.spec_version,
        source_url=target.source_url,
        model_label=target.model_label,
    )


@settings(max_examples=300, deadline=None)
@given(parts=builds(), full=st.booleans())
def test_result_is_deterministic(parts: list[Part], full: bool) -> None:
    assert run(parts, full_build=full) == run(parts, full_build=full)


@settings(max_examples=400, deadline=None)
@given(parts=builds(), full=st.booleans(), data=st.data())
def test_removing_an_attribute_never_turns_a_problem_into_pass(
    parts: list[Part], full: bool, data: st.DataObject
) -> None:
    before = run(parts, full_build=full)
    index = data.draw(st.integers(0, len(parts) - 1))
    target = parts[index]
    if not target.attributes:
        return
    attribute = data.draw(st.sampled_from(sorted(target.attributes)))
    changed = [*parts[:index], _without(target, attribute), *parts[index + 1 :]]
    after = run(changed, full_build=full)
    if before.decision != "PASS":
        assert after.decision != "PASS", (before.decision, attribute, ids(after))


# ---------------------------------------------------- QA 6a F2: bog'lanmagan qism BLOCK'ni yashirmaydi

RANK = {"PASS": 0, "REVIEW_REQUIRED": 1, "BLOCK": 2}


def test_unlinked_sibling_does_not_hide_known_block() -> None:
    # DDR4 plata + DDR5 RAM — BLOCK; yoniga bog'lanmagan RAM qo'shilsa ham BLOCK qoladi
    parts = [i5_12400f(), b660_d4(), ddr5_kit(), part("RAM", linked=False)]
    result = run(ryzen_build(cpu=None, mb=None, ram=None) + parts)
    assert result.decision == "BLOCK"
    assert "RAM_TYPE_MB" in ids(result) and "UNLINKED_PART" in ids(result)
    # 3 ta NVMe 2 slotli platada + bog'lanmagan SSD
    storage = [nvme(), nvme(), nvme(), part("STORAGE", linked=False)]
    result = run(ryzen_build(storage=None) + storage)
    assert result.decision == "BLOCK" and "STORAGE_M2_SLOTS" in ids(result)
    # 3 ta 2 modulli to'plam (6 > 4 slot) + bog'lanmagan RAM
    rams = [ddr5_kit(), ddr5_kit(), ddr5_kit(), part("RAM", linked=False)]
    result = run(ryzen_build(ram=None) + rams)
    assert result.decision == "BLOCK" and "RAM_SLOTS" in ids(result)


def test_unlinked_only_category_is_still_review() -> None:
    result = run(ryzen_build(ram=part("RAM", linked=False)))
    assert result.decision == "REVIEW_REQUIRED"
    assert "UNLINKED_PART" in ids(result) and "RAM_TYPE_MB" not in ids(result)


def test_adapter_finding_has_hint() -> None:
    gpu = rtx_4070_super()
    result = run(ryzen_build(gpu=gpu, psu=psu(750, connectors=[{"type": "PCIE_8PIN", "count": 3}])))
    finding = find(result, "PSU_GPU_CONNECTORS")
    assert finding.severity == "REVIEW_REQUIRED" and finding.hint == {"code": "PSU_NATIVE_16PIN"}
    assert finding.hint_text


@settings(max_examples=400, deadline=None)
@given(parts=builds(), full=st.booleans(), data=st.data())
def test_adding_an_unlinked_part_never_lowers_severity(
    parts: list[Part], full: bool, data: st.DataObject
) -> None:
    # Mavjud toifaga bog'lanmagan "qo'shni" qism (yo'q toifani to'ldirish REQUIRED_PARTS'ni
    # haqli olib tashlaydi)
    before = run(parts, full_build=full)
    category = data.draw(st.sampled_from(sorted({p.category for p in parts})))
    after = run([*parts, part(category, linked=False)], full_build=full)
    assert RANK[after.decision] >= RANK[before.decision], (before.decision, after.decision, category)
    # avval topilgan har BLOCK qoidasi saqlanadi
    blocks = {f.rule_id for f in before.findings if f.severity == "BLOCK"}
    assert blocks <= {f.rule_id for f in after.findings if f.severity == "BLOCK"} | {"DUPLICATE_PART"}
