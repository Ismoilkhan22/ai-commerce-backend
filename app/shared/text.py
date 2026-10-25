"""Kiritiladigan matn uchun umumiy tip (11 §6.3).

`Text` — boshidagi va oxiridagi bo'shliq olib tashlanadi, KEYIN uzunlik tekshiriladi: `"   "` bo'sh
hisoblanadi (`min_length` ishlaydi). NUL belgisi (`\\x00`) qabul qilinmaydi — PostgreSQL uni saqlay olmaydi.
NUL so'rov darajasida ham ushlanadi (`app.shared.request_guard`); bu yerdagisi HTTP'siz chaqiruvlar uchun.

    name: Text = Field(min_length=1, max_length=80)

`CleanText` — xuddi shunday, lekin ko'rinmas belgilar ham olib tashlanadi (`strip_invisible`):
- Unicode "format" (Cf) toifasidagi hamma belgi: yo'nalish almashtiruvchilar (U+202A–U+202E, U+2066–U+2069),
  nol kenglikdagilar (U+200B–U+200F, U+2060–U+2064, U+FEFF), yumshoq tire (U+00AD), U+180E va boshqalar;
- Cf bo'lmagan, lekin ko'rinmaydiganlar: U+034F (CGJ), qator/xatboshi ajratgichi (U+2028, U+2029),
  hangul "to'ldiruvchi" bo'shliqlari (U+115F, U+1160, U+3164, U+FFA0).
Emoji buzilmaydi: emoji orasidagi ZWJ (U+200D, "👨‍👩‍👧") va bayroq teglari (U+E0020–U+E007F) qoladi.
Xaridor ismi va izohlar uchun: "Ali\u202e…" ro'yxatda boshqacha ko'rinib, xodimni chalg'itmasin.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, StringConstraints

NUL = "\x00"
# Regex sinfi uchun aniq ro'yxat (fayl nomlari ham shundan foydalanadi); Cf toifasi esa funksiyada
INVISIBLE_CHARS = (
    "\u00ad\u034f\u115f\u1160\u180e\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u206f\u3164\ufeff\uffa0"
)
_INVISIBLE = re.compile(f"[{INVISIBLE_CHARS}]")
_ZWJ = "\u200d"
_TAGS = range(0xE0020, 0xE0080)  # bayroq emoji'si ichidagi teglar (🏴󠁧󠁢󠁳󠁣󠁴󠁿)


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return code >= 0x1F000 or 0x2600 <= code <= 0x27BF or code == 0xFE0F


def _drop(text: str, index: int) -> bool:
    char = text[index]
    if char == _ZWJ:  # emoji ketma-ketligi ichidagi ZWJ qoladi
        return not (0 < index < len(text) - 1 and _is_emoji(text[index - 1]) and _is_emoji(text[index + 1]))
    if ord(char) in _TAGS:
        return False
    return bool(_INVISIBLE.match(char)) or unicodedata.category(char) == "Cf"


def reject_nul(value: str) -> str:
    if NUL in value:
        raise ValueError("NUL character is not allowed")
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(reject_nul)]


def strip_invisible(value: object) -> object:
    if not isinstance(value, str) or value.isascii():
        return value
    return "".join(char for index, char in enumerate(value) if not _drop(value, index))


# BeforeValidator: belgilar uzunlik tekshiruvidan OLDIN olib tashlanadi ("\u200b" — bo'sh matn)
CleanText = Annotated[Text, BeforeValidator(strip_invisible)]
