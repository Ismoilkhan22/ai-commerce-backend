"""Quvvat hisobi (engineering/17 §6.3): taxminiy iste'mol = CPU max + GPU'lar + 75 W.

Noma'lum qiymat — None (hech qachon 0 emas). AI va UI uchun tavsiya qilinadigan quvvat bloki ham shu yerda.
"""

from __future__ import annotations

import math

from app.domains.catalog.compatibility.model import POWER_OVERHEAD_W, PSU_HEADROOM, PSU_ROUND_TO_W, Build


def estimate_power_w(build: Build) -> int | None:
    """CPU va hamma GPU'larning quvvati ma'lum bo'lsagina; CPU yo'q bo'lsa — hisoblanmaydi."""
    cpu = build.one("CPU")
    if cpu is None or not cpu.linked or cpu.get("max_power_w") is None:
        return None
    total = int(cpu.get("max_power_w"))
    for gpu in build.units("GPU"):
        if not gpu.linked or gpu.get("board_power_w") is None:
            return None
        total += int(gpu.get("board_power_w"))
    return total + POWER_OVERHEAD_W


def round_up_psu(watts: int) -> int:
    return math.ceil(watts / PSU_ROUND_TO_W) * PSU_ROUND_TO_W


def headroom_target_w(build: Build) -> int | None:
    """max(GPU tavsiyasi, iste'mol × 1.3). GPU tavsiyasi noma'lum bo'lsa — None (noma'lum ≠ yetarli)."""
    draw = estimate_power_w(build)
    if draw is None:
        return None
    target = math.ceil(draw * PSU_HEADROOM)
    for gpu in build.all("GPU"):
        recommended = gpu.get("recommended_psu_w")
        if recommended is None:
            return None
        target = max(target, int(recommended))
    return target


def recommended_psu_w(build: Build) -> int | None:
    """Xaridorga aytiladigan quvvat bloki: zaxira bilan, 50 W ga yaxlitlangan (650, 750 ...)."""
    target = headroom_target_w(build)
    return round_up_psu(target) if target is not None else None
