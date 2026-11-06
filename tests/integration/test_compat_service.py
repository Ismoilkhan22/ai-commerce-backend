"""PC moslik — shop SKU'lari orqali (engineering/17 §7): SKU → kutubxona spec'i → engine, port orqali.

Haqiqiy PostgreSQL: spec'lar platforma tomonida ikki ko'z bilan tasdiqlanadi, SKU'lar avtomatik bog'lanadi.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.shared.contracts.compatibility import BuildLine, CompatibilityResult
from app.shared.errors.base import ValidationError
from tests.integration.helpers import World
from tests.integration.test_catalog import _approved_spec, _create, _platform_member, _sku

pytestmark = pytest.mark.integration


def _specs(world: World, editor: str, tag: str) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """Toifa → (brend, model, atributlar); har biri tasdiqlangan holda kutubxonaga kiritiladi."""
    specs: dict[str, tuple[str, str, dict[str, Any]]] = {
        "CPU": (
            "AMD",
            f"Ryzen {tag}",
            {
                "socket": "AM5",
                "memory_types": ["DDR5"],
                "base_power_w": 65,
                "max_power_w": 88,
                "integrated_graphics": True,
                "cooler_included": True,
            },
        ),
        "MOTHERBOARD": (
            "MSI",
            f"PRO B650M {tag}",
            {
                "socket": "AM5",
                "form_factor": "MICRO_ATX",
                "memory_type": "DDR5",
                "memory_slots": 4,
                "max_memory_gb": 192,
                "m2_slots": 2,
                "sata_ports": 4,
                "cpu_support": [{"cpu_model": f"Ryzen {tag}", "min_bios": "1.0"}],
                "shipped_bios": "1.2",
            },
        ),
        "RAM": (
            "Kingston",
            f"FURY Beast {tag}",
            {"type": "DDR5", "form_factor": "DIMM", "module_count": 2, "capacity_per_module_gb": 16},
        ),
        "GPU": (
            "MSI",
            f"RTX 4060 {tag}",
            {
                "length_mm": 199,
                "board_power_w": 115,
                "recommended_psu_w": 550,
                "power_connectors": [{"type": "PCIE_8PIN", "count": 1}],
            },
        ),
        "PSU": (
            "DeepCool",
            f"PK550 {tag}",
            {"wattage_w": 550, "form_factor": "ATX", "connectors": [{"type": "PCIE_8PIN", "count": 2}]},
        ),
        "CASE": (
            "Zalman",
            f"i3 Neo {tag}",
            {
                "supported_mb_form_factors": ["ATX", "MICRO_ATX"],
                "max_gpu_length_mm": 315,
                "psu_form_factor": "ATX",
            },
        ),
        "STORAGE": ("Samsung", f"990 PRO {tag}", {"interface": "NVME", "form_factor": "M2_2280"}),
    }
    for category, (brand, model, attributes) in specs.items():
        _approved_spec(world, editor, category=category, brand=brand, model_name=model, attributes=attributes)
    return specs


def _check(world: World, shop_id: str, lines: list[BuildLine], locale: str = "uz") -> CompatibilityResult:
    from app.dependencies import get_catalog_query
    from app.shared.db.session import Database, DatabaseConfig

    async def run() -> CompatibilityResult:
        database = Database(DatabaseConfig(url=world.urls.runtime))
        try:
            async with database.transaction(UUID(shop_id)) as db:
                return await get_catalog_query().check_compatibility(
                    db,
                    UUID(shop_id),
                    lines,
                    locale,  # type: ignore[arg-type]
                )
        finally:
            await database.dispose()

    return asyncio.run(run())


def test_check_compatibility_through_linked_skus(world: World) -> None:
    a, b = world.create_shop(), world.create_shop()
    owner, shop_id = a["owner_token"], a["shop"]["id"]
    editor = _platform_member(world)
    tag = uuid4().hex[:5].upper()
    specs = _specs(world, editor, tag)

    skus: dict[str, UUID] = {}
    for category, (brand, model, _) in specs.items():
        product = _create(
            world,
            owner,
            category_code=category,
            brand=brand,
            title=f"{brand} {model}",
            skus=[_sku(model_name=model)],
        )
        sku = product["skus"][0]
        assert sku["spec_link"] is not None, (category, sku)  # brend + model aniq mos — avtomatik bog'landi
        skus[category] = UUID(sku["id"])
    monitor = _create(world, owner, category_code="MONITOR", brand="LG", title="LG 24MP400", skus=[_sku()])
    unknown_gpu = _create(
        world,
        owner,
        category_code="GPU",
        brand="MSI",
        title="RTX ???",
        skus=[_sku(model_name=f"RTX 9999 {tag}")],
    )
    monitor_sku, unlinked_gpu = UUID(monitor["skus"][0]["id"]), UUID(unknown_gpu["skus"][0]["id"])

    lines = [BuildLine(sku_id) for sku_id in skus.values()] + [BuildLine(monitor_sku)]
    result = _check(world, shop_id, lines)
    assert result.decision == "PASS", [(f.rule_id, f.explanation) for f in result.findings]
    assert result.rule_set_version == "pc-2026-10-v2"
    assert result.estimated_power_w == 88 + 115 + 75 and result.recommended_psu_w == 550
    assert result.ignored_sku_ids == (monitor_sku,)  # monitor PC qismi emas — tekshirilmaydi
    assert set(result.spec_versions) == set(skus.values())
    assert all(ev.version == 1 and ev.source_url for ev in result.spec_versions.values())

    # Bog'lanmagan videokarta — REVIEW, tushuntirish so'ralgan tilda
    without_gpu = [BuildLine(s) for c, s in skus.items() if c != "GPU"]
    review = _check(world, shop_id, [*without_gpu, BuildLine(unlinked_gpu)], locale="ru")
    assert review.decision == "REVIEW_REQUIRED"
    unlinked = next(f for f in review.findings if f.rule_id == "UNLINKED_PART")
    assert unlinked.parts == (str(unlinked_gpu),)
    assert unlinked.explanation.startswith("Эта позиция (видеокарта)")

    # Ikki ta disk — M.2 slotlar yetadi; uchta — yo'q
    three = [*without_gpu, BuildLine(skus["GPU"]), BuildLine(skus["STORAGE"], quantity=2)]
    blocked = _check(world, shop_id, three)
    assert blocked.decision == "BLOCK"
    assert any(f.rule_id == "STORAGE_M2_SLOTS" for f in blocked.findings)

    # Boshqa shopning SKU'si — xato maydoni bilan
    foreign = UUID(_create(world, b["owner_token"], skus=[_sku()])["skus"][0]["id"])
    with pytest.raises(ValidationError) as caught:
        _check(world, shop_id, [BuildLine(skus["CPU"]), BuildLine(foreign)])
    assert caught.value.details["fields"] == [{"field": "lines[1].sku_id", "code": "invalid", "params": {}}]
