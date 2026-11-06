"""Engine kirishi: yig'ma va uning qismlari (engineering/17 §4.1, §6).

Atributlar — kutubxonadagi tasdiqlangan spec versiyasining `attributes` lug'ati, o'zgartirilmagan holda.
Yo'q kalit — noma'lum (BL-028): engine uni hech qachon 0 yoki "mos" deb hisoblamaydi.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

# Faol qoidalar to'plami. Chegaralar (75 W, ×1.3) o'zgarsa — yangi versiya (17 §6.4, §9)
# v2 (QA 6a F2): bog'lanmagan qism endi ma'lum BLOCK'ni yashirmaydi — qoidalar bog'langan qismlarda ishlaydi
RULESET_VERSION = "pc-2026-10-v2"

POWER_OVERHEAD_W = 75  # ona plata, RAM, disk, fanlar
PSU_HEADROOM = Decimal("1.3")
PSU_ROUND_TO_W = 50  # tavsiya — bozordagi quvvat bloklari qadami

PC_CATEGORIES = ("CPU", "MOTHERBOARD", "GPU", "RAM", "PSU", "CASE", "CPU_COOLER", "STORAGE")
REQUIRED_CATEGORIES = ("CPU", "MOTHERBOARD", "RAM", "STORAGE", "PSU", "CASE")


@dataclass(frozen=True, eq=False)  # qism — o'zligi bilan (bir xil ikkita SSD qatori ikkita qism)
class Part:
    category: str
    attributes: dict[str, Any] = field(default_factory=dict)
    quantity: int = 1
    sku_id: UUID | None = None
    spec_id: UUID | None = None  # None — SKU kutubxonaga bog'lanmagan (UNLINKED_PART)
    spec_version: int | None = None
    source_url: str | None = None
    model_label: str = ""  # "AMD Ryzen 5 7600" — BIOS ro'yxati va aralash RAM uchun

    @property
    def linked(self) -> bool:
        return self.spec_id is not None

    def get(self, attribute: str) -> Any:
        return self.attributes.get(attribute)


@dataclass(frozen=True)
class Build:
    parts: tuple[Part, ...]
    full_build: bool = True  # xaridor faqat qism so'rasa — to'liqlik qoidalari qo'llanmaydi (17 §6.1)

    @classmethod
    def of(cls, parts: Sequence[Part], *, full_build: bool = True) -> Build:
        return cls(tuple(parts), full_build)

    def all(self, category: str) -> list[Part]:
        return [p for p in self.parts if p.category == category]

    def one(self, category: str) -> Part | None:
        """Bitta bo'lishi kerak bo'lgan qism (CPU, ona plata, PSU, korpus, cooler); birinchisi."""
        found = self.all(category)
        return found[0] if found else None

    def count(self, category: str) -> int:
        return sum(p.quantity for p in self.all(category))

    def units(self, category: str) -> Iterator[Part]:
        """Har donasi alohida (2 ta bir xil SSD — 2 ta disk)."""
        for part in self.all(category):
            for _ in range(part.quantity):
                yield part

    def ref(self, part: Part) -> str:
        if part.sku_id is not None:
            return str(part.sku_id)
        same = [p for p in self.parts if p.category == part.category]
        index = next((i for i, p in enumerate(same) if p is part), 0)
        return f"{part.category}#{index + 1}"


_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_label(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


_VERSION_PART = re.compile(r"(\d+)|(\D+)")


def version_key(text: str) -> tuple[tuple[int, int | str], ...]:
    """BIOS versiyalarini "tabiiy" solishtirish: F9 < F20, 1.9 < 1.10, 7D75v1A < 7D75v1B."""
    key: list[tuple[int, int | str]] = []
    for number, other in _VERSION_PART.findall(text.strip().upper()):
        key.append((0, int(number)) if number else (1, other))
    return tuple(key)
