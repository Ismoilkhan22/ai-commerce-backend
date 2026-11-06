"""PII redaction (14 §7, ai/M06-architecture.md §7, BL-039, DEC-016).

LLM'ga hech qachon xom telefon, email, karta raqami yoki manzil bormaydi — o'rniga `[PHONE_1]` kabi token.
Xarita `platform.llm_pii_refs` da (qiymat shifrlangan, bir suhbatda bir qiymat — bitta token). Javobdagi token
messaging'ga topshirishda haqiqiy qiymatga almashtiriladi (karta — hech qachon, faqat niqob).

Qoidalar regex (14 §7, 26 §6b — shubhada ortiqcha yashirish tomonga):
- telefon: 7–15 raqam, ajratgichlar `space . - / ( )`; lekin faqat telefonga o'xshasa: `+` yoki davlat kodi
  (`998…`, `00…`, 11 raqamli `7`/`8…`), mahalliy 9 raqamli format (`90 123 45 67`) yoki "tel/raqam/номер"
  konteksti. Oddiy summa (`3500000 so'm`, `1 200 000 - 3 500 000 so'm`, `narx 4 800 000`) — telefon emas;
- karta: Luhn'dan o'tgan 13–19 raqam, istalgan ajratgich bilan;
- shaxsiy hujjat: JSHSHIR/PINFL (14 raqam) va pasport (`AA1234567`) — `ID`;
- email, jumladan yashirilgan (`ali [at] gmail [dot] com`, `ali собака mail точка ru`);
- manzil: kalit so'z (ko'cha, uy, kv, mavze, massiv, ул., дом, кв …) atrofidagi bo'lak va uy raqami naqshi
  (`4-17-45`);
- joylashuv: koordinatalar — o'nlik (`41.311151, 69.279737`, `lat 41.3110 lon 69.2405`) va daraja-minut-soniya
  (`41°18'39.9"N`) — `LOCATION` (tiklanmaydi).
Ism (NER) Stage 1 da yo'q — hujjatda qayd etilgan.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.llm.models.orm import LlmPiiRef
from app.shared.clock import utcnow
from app.shared.db.encryption import search_hmac

RESTORABLE = frozenset({"PHONE", "EMAIL", "ADDRESS"})  # ID, LOCATION, CARD — hech qachon tiklanmaydi
REF_TTL = timedelta(days=365)  # suhbat saqlash muddati bilan (26 §5)

_SEP = r"[\s\-./()\u00a0]"
_PHONE = re.compile(rf"(?<![\w\[])\+?\(?\d(?:{_SEP}{{0,3}}\d){{6,14}}(?!\d)")
_MONEY_AFTER = re.compile(
    r"^\s?(so['‘’`ʻ]?m|сўм|сум|sum\b|uzs|usd|\$|mln|млн|million|ming|минг|тыс|dollar|доллар|ta\b|dona|шт|gb|tb|"
    r"гб|w\b|вт|mhz|ghz|oy\b|ой|%)",
    re.IGNORECASE,
)
_MONEY_GROUPS = re.compile(r"^\$?\d{1,3}(?:[ .,\u00a0]\d{3})+$")
_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+\s*(?:@|\(at\)|\[at\]|\{at\}|\s(?:at|собака|kuchukcha)\s)\s*[A-Za-z0-9\-]+"
    r"(?:\s*(?:\.|\(dot\)|\[dot\]|\{dot\}|\s(?:dot|точка|nuqta)\s)\s*[A-Za-z0-9\-]+)*"
    r"\s*(?:\.|\(dot\)|\[dot\]|\{dot\}|\s(?:dot|точка|nuqta)\s)\s*[A-Za-z]{2,}",
    re.IGNORECASE,
)
_CARD = re.compile(rf"(?<!\d)\d(?:{_SEP}{{0,2}}\d){{12,18}}(?!\d)")
_PINFL = re.compile(r"(?<!\d)[1-7]\d{13}(?!\d)")
_PASSPORT = re.compile(r"\b[A-ZА-Я]{2}\s?\d{7}\b")
_COORDS = re.compile(r"-?\d{1,3}\.\d{4,}(?:\s*[,;]\s*|%2C)-?\d{1,3}\.\d{4,}", re.IGNORECASE)
_COORD_LABEL = r"(?:lat(?:itude)?|lon(?:g(?:itude)?)?|lng|широта|долгота|kenglik|uzunlik|кенглик|узунлик)"
_COORDS_LABELED = re.compile(  # "lat 41.3110 lon 69.2405", "latitude=41.31, longitude=69.24"
    rf"\b{_COORD_LABEL}\b[\s:='\"]*-?\d{{1,3}}[.,]\d+(?:\W{{1,5}}{_COORD_LABEL}\b[\s:='\"]*-?\d{{1,3}}[.,]\d+)?",
    re.IGNORECASE,
)
_COORDS_DMS = re.compile(  # 41°18'39.9"N, 41° 18′ 39″ N, 41.3110° N
    r"-?\d{1,3}\s?°\s?\d{1,2}\s?['′’ʼ]\s?(?:\d{1,2}(?:\.\d+)?\s?(?:\"|″|”|''|’’)?)?(?:\s?[NSEWnsew](?![A-Za-z]))?"
    r"|-?\d{1,3}\.\d{3,}\s?°\s?(?:[NSEWnsew](?![A-Za-z]))?"
)
_HOUSE = re.compile(r"(?<![\w\-])\d{1,3}\s?[-/]\s?\d{1,3}\s?[-/]\s?\d{1,4}(?![\w\-])")
_ADDRESS = re.compile(
    r"(?P<pre>(?:[^.,;\n]{0,40},\s*)?[^.,;\n]{0,40})\b(?P<kw>(?:ko['‘’`ʻ]?chasi|kuchasi|ko['‘’`ʻ]?cha|mavzesi|mavze|massivi|massiv|mahallasi|mahalla|"
    r"tumani|kvartal|uy\s*\d+|\d+[\s-]?uy|\d+-xonadon|xonadon\s*\d+|kv\.?\s*\d+|"
    r"кўчаси|кучаси|мавзеси|массиви|маҳалла|район|мкр|микрорайон|улиц\w*|ул\.|проспект|пр-т|переулок|тупик|"
    r"квартал|дом\s*№?\s*\d+|д\.\s*\d+|кв\.?\s*\d+|street|st\.|avenue|ave\.|apt\.?\s*\d+|"
    r"apartment\s*\d+))\b(?P<post>[^.,;\n]{0,30})",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\[(PHONE|EMAIL|ADDRESS|CARD|NAME|ID|LOCATION)_(\d+)\]")


@dataclass(frozen=True)
class PiiMatch:
    kind: str
    start: int
    end: int
    value: str


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def normalize(kind: str, value: str) -> str:
    if kind in ("PHONE", "CARD"):
        digits = re.sub(r"\D", "", value)
        if kind == "PHONE" and len(digits) == 9:
            digits = "998" + digits
        return digits
    return " ".join(value.lower().split())


_MONEY_BEFORE = re.compile(
    r"(narx\w*|нарх\w*|цен\w*|стоим\w*|price|cost|budjet\w*|byudjet\w*|бюджет\w*|budget|summa|сумма)"
    r"[\s:–—-]{0,3}$",
    re.IGNORECASE,
)


_PHONE_CONTEXT = re.compile(
    r"(?:tel\w*|тел\w*|phone|raqam\w*|номер\w*|nomer\w*|whats?app|telegram|aloqa|связ\w*|call|mobil\w*|"
    r"мобил\w*|qo['‘’`ʻ]?ng['‘’`ʻ]?iroq\w*|звон\w*|contact|kontakt\w*)[\s:.\-–—=]{0,4}$",
    re.IGNORECASE,
)
_UZ_CODES = frozenset(
    "20 33 50 55 61 62 65 66 67 69 70 71 72 73 74 75 76 77 78 79 87 88 90 91 93 94 95 97 98 99".split()
)


def _phone_shaped(value: str, digits: str) -> bool:
    """Telefonga o'xshaydimi: `+`, davlat kodi, 11 raqamli 7/8-…, yoki mahalliy 9 raqamli format."""
    if value.lstrip("(").startswith("+"):
        return True
    if len(digits) == 12 and digits.startswith("998"):
        return True
    if digits.startswith("00") and len(digits) >= 11:
        return True
    if len(digits) == 11 and digits[0] in "78":
        return True
    return len(digits) == 9 and digits[:2] in _UZ_CODES


def _is_phone(text: str, start: int, end: int, value: str, digits: str) -> bool:
    digits = "".join(str(unicodedata.digit(c, 0)) for c in digits)  # arab-hind va to'liq kenglikdagi raqamlar
    if not 7 <= len(digits) <= 15:
        return False
    if _PHONE_CONTEXT.search(text[max(0, start - 24) : start]):
        return True  # "tel: 1234567", "raqamim 971234567" — kontekst
    if _phone_like_money(text, start, end, value) or _bare_amount(text, start, end, value):
        return False
    return _phone_shaped(value, digits)


def _bare_amount(text: str, start: int, end: int, value: str) -> bool:
    """`3500000 so'm`, `$3500000`, `narx 3500000`: valyuta yoki narx so'zi yonidagi oddiy son."""
    before = text[max(0, start - 14) : start]
    return (
        bool(_MONEY_AFTER.match(text[end:]))
        or before.endswith("$")
        or bool(_MONEY_BEFORE.search(before))
        or bool(_RANGE_BEFORE.search(text[max(0, start - 3) : start]) and _MONEY_AFTER.match(text[end:]))
    )


_RANGE_BEFORE = re.compile(r"[-–—]\s?$")


def _phone_like_money(text: str, start: int, end: int, value: str) -> bool:
    """`3 500 000 so'm`, `narx 4 800 000`, `$1 250` — pul summasi, telefon emas (faqat valyuta, birlik yoki
    narx so'zi yonida bo'lsa; aks holda — ehtiyot uchun telefon deb yashiriladi)."""
    if not _MONEY_GROUPS.match(value.strip()):
        return False
    before = text[max(0, start - 14) : start]
    return bool(_MONEY_AFTER.match(text[end:])) or before.endswith("$") or bool(_MONEY_BEFORE.search(before))


def find_pii(text: str) -> list[PiiMatch]:
    """Matndagi PII bo'laklari (bir-birini qoplamaydi, chapdan o'ngga; uzunroq bo'lak ustun)."""
    found: list[PiiMatch] = []
    for match in _COORDS.finditer(text):
        found.append(PiiMatch("LOCATION", match.start(), match.end(), match.group()))
    for pattern in (_COORDS_LABELED, _COORDS_DMS):
        for match in pattern.finditer(text):
            found.append(PiiMatch("LOCATION", match.start(), match.end(), match.group()))
    for match in _EMAIL.finditer(text):
        found.append(PiiMatch("EMAIL", match.start(), match.end(), match.group()))
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19:
            # Luhn'dan o'tmagan uzun raqam ham (karta xatosi, hisob raqami) — ehtiyot uchun yashiriladi
            found.append(
                PiiMatch("CARD" if _luhn(digits) else "ID", match.start(), match.end(), match.group())
            )
    for match in _PINFL.finditer(text):
        found.append(PiiMatch("ID", match.start(), match.end(), match.group()))
    for match in _PASSPORT.finditer(text):
        found.append(PiiMatch("ID", match.start(), match.end(), match.group()))
    for match in _PHONE.finditer(text):
        value = match.group()
        digits = re.sub(r"\D", "", value)
        if _is_phone(text, match.start(), match.end(), value, digits):
            found.append(PiiMatch("PHONE", match.start(), match.end(), value))
    for match in _HOUSE.finditer(text):
        found.append(PiiMatch("ADDRESS", match.start(), match.end(), match.group()))
    others = [m for m in found if m.kind != "ADDRESS"]
    for match in _ADDRESS.finditer(text):
        # manzil oynasi boshqa PII'ni yutmaydi: oyna undan keyin boshlanadi / oldin tugaydi
        start, end = match.start(), match.end()
        for other in others:
            if other.end <= match.start("kw"):
                start = max(start, other.end)
            elif other.start >= match.end("kw"):
                end = min(end, other.start)
        chunk = text[start:end]
        lead = len(chunk) - len(chunk.lstrip(" ,;:–—-"))
        value = chunk.strip(" ,;:–—-")
        if value:
            found.append(PiiMatch("ADDRESS", start + lead, start + lead + len(value), value))
    # ustunlik: koordinata, email, karta, hujjat, telefon, manzil; keyin uzunroq bo'lak
    priority = {"LOCATION": 0, "EMAIL": 1, "CARD": 2, "ID": 3, "PHONE": 4, "ADDRESS": 5}
    found.sort(key=lambda m: (priority[m.kind], m.start, -(m.end - m.start)))
    taken: list[PiiMatch] = []
    for item in found:
        if all(item.end <= t.start or item.start >= t.end for t in taken):
            taken.append(item)
    return sorted(taken, key=lambda m: m.start)


class PiiStore(Protocol):
    async def token_for(self, kind: str, value: str) -> str: ...

    async def values(self) -> dict[str, tuple[str, str]]:
        """token → (kind, qiymat). Karta qiymati — niqob."""
        ...


@dataclass
class MemoryPiiStore:
    """Sinov oynasi va testlar uchun (bazasiz)."""

    _tokens: dict[str, str] = field(default_factory=dict)  # hmac → token
    _values: dict[str, tuple[str, str]] = field(default_factory=dict)

    async def token_for(self, kind: str, value: str) -> str:
        key = f"{kind}:{normalize(kind, value)}"
        if key in self._tokens:
            return self._tokens[key]
        count = sum(1 for k, _ in self._values.values() if k == kind)
        token = f"{kind}_{count + 1}"
        self._tokens[key] = token
        self._values[token] = (kind, _mask(value) if kind == "CARD" else value)
        return token

    async def values(self) -> dict[str, tuple[str, str]]:
        return dict(self._values)


class DbPiiStore:
    """Suhbat bo'yicha `platform.llm_pii_refs` (shop konteksti o'rnatilgan tranzaksiyada)."""

    def __init__(self, db: AsyncSession, shop_id: UUID, conversation_id: UUID) -> None:
        self.db = db
        self.shop_id = shop_id
        self.conversation_id = conversation_id

    async def token_for(self, kind: str, value: str) -> str:
        digest = search_hmac(f"{kind}:{normalize(kind, value)}")
        existing = (
            await self.db.execute(
                select(LlmPiiRef.token).where(
                    LlmPiiRef.shop_id == self.shop_id,
                    LlmPiiRef.conversation_id == self.conversation_id,
                    LlmPiiRef.value_hmac == digest,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        count = (
            await self.db.execute(
                select(func.count()).where(
                    LlmPiiRef.shop_id == self.shop_id,
                    LlmPiiRef.conversation_id == self.conversation_id,
                    LlmPiiRef.kind == kind,
                )
            )
        ).scalar_one()
        token = f"{kind}_{count + 1}"
        self.db.add(
            LlmPiiRef(
                shop_id=self.shop_id,
                conversation_id=self.conversation_id,
                token=token,
                kind=kind,
                value_enc=_mask(value) if kind == "CARD" else value,
                value_hmac=digest,
                expires_at=utcnow() + REF_TTL,
            )
        )
        await self.db.flush()
        return token

    async def values(self) -> dict[str, tuple[str, str]]:
        rows = (
            await self.db.execute(
                select(LlmPiiRef.token, LlmPiiRef.kind, LlmPiiRef.value_enc).where(
                    LlmPiiRef.shop_id == self.shop_id, LlmPiiRef.conversation_id == self.conversation_id
                )
            )
        ).all()
        return {r.token: (r.kind, r.value_enc) for r in rows}


def _mask(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"**** {digits[-4:]}" if len(digits) >= 4 else "****"


async def redact(store: PiiStore, text: str) -> str:
    """Matndagi PII → `[KIND_N]` tokenlari (bir qiymat — har doim bir token)."""
    matches = find_pii(text)
    if not matches:
        return text
    out: list[str] = []
    cursor = 0
    for match in matches:
        out.append(text[cursor : match.start])
        out.append(f"[{await store.token_for(match.kind, match.value)}]")
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


async def restore(store: PiiStore, text: str, *, allowed: frozenset[str] = RESTORABLE) -> str:
    """Javobdagi tokenlar → haqiqiy qiymat (faqat ruxsat etilgan turlar; karta — niqob)."""
    if not _TOKEN.search(text):
        return text
    values = await store.values()

    def swap(match: re.Match[str]) -> str:
        token = f"{match.group(1)}_{match.group(2)}"
        kind_value = values.get(token)
        if kind_value is None:
            return match.group()
        kind, value = kind_value
        if kind == "CARD":
            return value
        if kind in ("ID", "LOCATION"):
            return match.group()
        return value if kind in allowed else match.group()

    return _TOKEN.sub(swap, text)


def has_raw_pii(text: str) -> bool:
    """Tekshiruv: redact qilingan matnda PII qoldimi (testlar, provayderga ketishdan oldin)."""
    return bool(find_pii(text))


TokenResolver = Callable[[str], str | None]
