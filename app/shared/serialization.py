"""JSON'ga aylantirish — API javobi bilan aynan bir xil qoidada (Pydantic).

FastAPI javoblarni Pydantic bilan serializatsiya qiladi: Decimal → "12.50" (matn, aniqlik yo'qolmaydi),
datetime → "2026-10-23T10:00:00Z", UUID → matn. Xato tafsilotlari va saqlanadigan javoblar
(idempotency) ham shu funksiyadan o'tadi — takroriy so'rov birinchisi bilan aynan bir xil javob oladi.
"""

from __future__ import annotations

from typing import Any

from pydantic_core import to_jsonable_python


def to_json_compatible(value: Any) -> Any:
    return to_jsonable_python(value)
