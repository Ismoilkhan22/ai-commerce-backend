"""Kiritiladigan matn uchun umumiy tip (11 §6.3).

`Text` — boshidagi va oxiridagi bo'shliq olib tashlanadi, KEYIN uzunlik tekshiriladi: `"   "` bo'sh
hisoblanadi (`min_length` ishlaydi). NUL belgisi (`\\x00`) qabul qilinmaydi — PostgreSQL uni saqlay olmaydi.
NUL so'rov darajasida ham ushlanadi (`app.shared.request_guard`); bu yerdagisi HTTP'siz chaqiruvlar uchun.

    name: Text = Field(min_length=1, max_length=80)
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

NUL = "\x00"


def reject_nul(value: str) -> str:
    if NUL in value:
        raise ValueError("NUL character is not allowed")
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(reject_nul)]
