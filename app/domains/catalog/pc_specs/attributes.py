"""Texnik atributlar sxemasi — har tur uchun alohida (engineering/17 §4.1).

O'lchamlar mm, quvvat W, sig'im GB. Hamma maydon ixtiyoriy: **yo'q atribut — noma'lum** (0 yoki bo'sh emas),
moslik tekshiruvi uni "tekshirish kerak" deb biladi. Noma'lum kalit qabul qilinmaydi (xato yozuv ushlanadi).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from app.shared.errors.base import ValidationError
from app.shared.errors.handlers import validation_fields

Code = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_\-]{0,31}$")]  # AM5, LGA1700, B650
Watts = Annotated[int, Field(ge=1, le=5000)]
Millimetres = Annotated[int, Field(ge=1, le=1000)]
Count = Annotated[int, Field(ge=0, le=64)]
MemoryType = Literal["DDR3", "DDR4", "DDR5"]
BoardFormFactor = Literal["E_ATX", "ATX", "MICRO_ATX", "MINI_ITX"]
PsuFormFactor = Literal["ATX", "SFX", "SFX_L"]
PowerConnectorType = Literal["PCIE_6PIN", "PCIE_8PIN", "12VHPWR", "12V_2X6"]


class _Attrs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PowerConnector(_Attrs):
    type: PowerConnectorType
    count: Annotated[int, Field(ge=1, le=8)]


class CpuSupport(_Attrs):
    cpu_model: Annotated[str, Field(min_length=1, max_length=100)]
    min_bios: Annotated[str, Field(min_length=1, max_length=50)]


class CpuAttrs(_Attrs):
    socket: Code | None = None
    memory_types: list[MemoryType] | None = None
    base_power_w: Watts | None = None
    max_power_w: Watts | None = None
    integrated_graphics: bool | None = None
    cooler_included: bool | None = None


class MotherboardAttrs(_Attrs):
    socket: Code | None = None
    chipset: Code | None = None
    form_factor: BoardFormFactor | None = None
    memory_type: MemoryType | None = None
    memory_slots: Count | None = None
    max_memory_gb: Annotated[int, Field(ge=1, le=4096)] | None = None
    max_memory_speed_mts: Annotated[int, Field(ge=100, le=20000)] | None = None
    m2_slots: Count | None = None
    sata_ports: Count | None = None
    cpu_support: list[CpuSupport] | None = None
    shipped_bios: Annotated[str, Field(max_length=50)] | None = None


class RamAttrs(_Attrs):
    type: MemoryType | None = None
    form_factor: Literal["DIMM", "SO_DIMM"] | None = None
    module_count: Annotated[int, Field(ge=1, le=16)] | None = None
    capacity_per_module_gb: Annotated[int, Field(ge=1, le=512)] | None = None
    speed_mts: Annotated[int, Field(ge=100, le=20000)] | None = None


class GpuAttrs(_Attrs):
    length_mm: Millimetres | None = None
    slot_width: Annotated[float, Field(ge=1, le=5)] | None = None
    board_power_w: Watts | None = None
    recommended_psu_w: Watts | None = None
    memory_gb: Annotated[int, Field(ge=1, le=256)] | None = None
    power_connectors: list[PowerConnector] | None = None


class PsuAttrs(_Attrs):
    wattage_w: Watts | None = None
    form_factor: PsuFormFactor | None = None
    connectors: list[PowerConnector] | None = None
    length_mm: Millimetres | None = None


class CaseAttrs(_Attrs):
    supported_mb_form_factors: list[BoardFormFactor] | None = None
    max_gpu_length_mm: Millimetres | None = None
    max_cpu_cooler_height_mm: Millimetres | None = None
    max_psu_length_mm: Millimetres | None = None
    psu_form_factor: PsuFormFactor | None = None
    radiator_support_mm: list[Millimetres] | None = None


class CpuCoolerAttrs(_Attrs):
    type: Literal["AIR", "AIO"] | None = None
    supported_sockets: list[Code] | None = None
    height_mm: Millimetres | None = None
    radiator_mm: Millimetres | None = None
    tdp_rating_w: Watts | None = None


class StorageAttrs(_Attrs):
    interface: Literal["NVME", "SATA"] | None = None
    form_factor: Literal["M2_2280", "M2_2242", "SATA_2_5", "SATA_3_5"] | None = None
    capacity_gb: Annotated[int, Field(ge=1, le=100_000)] | None = None


SCHEMAS: dict[str, type[_Attrs]] = {
    "CPU": CpuAttrs,
    "MOTHERBOARD": MotherboardAttrs,
    "GPU": GpuAttrs,
    "RAM": RamAttrs,
    "PSU": PsuAttrs,
    "CASE": CaseAttrs,
    "CPU_COOLER": CpuCoolerAttrs,
    "STORAGE": StorageAttrs,
}


def validate_attributes(category: str, attributes: dict[str, Any]) -> dict[str, Any]:
    """Toifa sxemasi bo'yicha tekshiradi; noma'lum (None) maydonlar saqlanmaydi."""
    try:
        parsed = SCHEMAS[category].model_validate(attributes)
    except PydanticValidationError as exc:
        fields = validation_fields(exc.errors())
        for item in fields:
            item["field"] = f"attributes.{item['field']}" if item["field"] else "attributes"
        raise ValidationError("Invalid attributes", fields=fields) from exc
    return parsed.model_dump(mode="json", exclude_none=True)
