"""Instagram izohi qoidalari (DEC-148, instagram_comments.md §4): «+» va narx so'rovi — oddiy qoida, AI emas.

Toza funksiyalar (DB va tarmoqsiz): bir xil matn — doim bir xil natija. Arzon, xatosiz; g'ayrioddiy yozilgan
savollar ("skoka turadi") o'tib ketishi mumkin — lug'at pilotdan keyin to'ldiriladi (I3).
"""

from __future__ import annotations

import re
import unicodedata

PLUS = "PLUS"
PRICE_QUESTION = "PRICE_QUESTION"
NONE = "NONE"

_PLUS_ONLY = re.compile(r"\++\d{0,2}")
_APOSTROPHES = re.compile(r"['‘’`ʻʼ´]")

# Narx so'zlari: uz (lotin va kirill), ru, en. Bosh chegara: so'z o'rtasidagi moslik hisoblanmaydi
_PRICE_WORDS = (
    # uz lotin
    r"narx\w*",
    r"qancha\w*",
    r"necha\s+(?:pul|som|so'?m|dollar|ming|mln)\w*",
    r"nech\s+(?:pul|som|so'?m)\w*",
    r"baho\w*",
    r"puli\b",
    # uz kirill
    r"нарх\w*",
    r"қанча\w*",
    r"канча\w*",
    r"неча\s+(?:пул|сўм|сум)\w*",
    r"баҳо\w*",
    # ru
    r"цен[аыуе]\b",
    r"цено[йю]\b",
    r"сколько",
    r"почем",
    r"почём",
    r"стоимост\w*",
    r"прайс\w*",
    r"стоит",
    # en
    r"prices?\b",
    r"how\s+much",
    r"costs?\b",
)
_PRICE = re.compile(r"(?<!\w)(?:" + "|".join(_PRICE_WORDS) + ")", re.IGNORECASE)
_UZ_CYRILLIC = re.compile(r"[ўқғҳЎҚҒҲ]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_EN_PRICE = re.compile(r"(?<!\w)(?:prices?|how\s+much|costs?)\b", re.IGNORECASE)


def _normal(text: str) -> str:
    return _APOSTROPHES.sub("'", unicodedata.normalize("NFKC", text)).lower()


def _plus_core(text: str) -> str:
    """Bo'shliq, emoji, tinish belgisi va ko'rinmas belgilarsiz: faqat '+', raqam va harflar qoladi."""
    kept: list[str] = []
    for ch in unicodedata.normalize("NFKC", text):
        if ch == "+" or ch.isalnum():
            kept.append(ch)
        elif unicodedata.category(ch)[0] in ("Z", "S", "C", "M", "P"):
            continue
        else:
            kept.append(ch)
    return "".join(kept)


def is_plus(text: str) -> bool:
    """«+», "++", "+1", "+ +", "+ 👍" — "menga narxini Direct'da yozing". Telefon yoki gap emas."""
    return bool(_PLUS_ONLY.fullmatch(_plus_core(text)))


def is_price_question(text: str) -> bool:
    return bool(_PRICE.search(_normal(text)))


def classify_trigger(text: str | None) -> str:
    """`PLUS` | `PRICE_QUESTION` | `NONE`. Matnsiz izoh (faqat rasm/stiker) — `NONE`."""
    if not text or not text.strip():
        return NONE
    if is_plus(text):
        return PLUS
    if is_price_question(text):
        return PRICE_QUESTION
    return NONE


def detect_locale(text: str | None) -> str | None:
    """Javob tili izoh tilidan; aniqlanmasa `None` (chaqiruvchi shop standartini oladi)."""
    if not text:
        return None
    if _CYRILLIC.search(text):
        return "uz" if _UZ_CYRILLIC.search(text) else "ru"
    if _EN_PRICE.search(text):
        return "en"
    return None
