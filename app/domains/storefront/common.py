"""storefront ichidagi yordamchilar: havola nomi (slug), rang kontrasti, ko'rib chiqish tokeni, kesh."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.shared.cache import Cache
from app.shared.cache.keys import global_key, shop_key
from app.shared.clock import utcnow

# ------------------------------------------------------------------ havola nomi (storefront.md §5)

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}  # fmt: skip
_NOT_SLUG = re.compile(r"[^a-z0-9]+")
SLUG_MAX = 80


def title_slug(title: str) -> str:
    """ "MSI GeForce RTX 4060 Ventus 2X" → "msi-geforce-rtx-4060-ventus-2x". Bazada saqlanmaydi: mahsulotni
    id topadi, nom faqat chiroy va qidiruv tizimlari uchun (storefront.md §5)."""
    text = "".join(_TRANSLIT.get(char, char) for char in title.lower())
    slug = _NOT_SLUG.sub("-", text).strip("-")[:SLUG_MAX].rstrip("-")
    return slug or "mahsulot"


# ------------------------------------------------------------------ rang kontrasti (WCAG)

LIGHT_BACKGROUND = "#FFFFFF"
DARK_BACKGROUND = "#0F172A"
MIN_ACCENT_CONTRAST = 3.0  # WCAG 1.4.11: interfeys elementi fonga nisbatan kamida 3:1


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def background(theme_mode: str) -> str:
    return DARK_BACKGROUND if theme_mode == "DARK" else LIGHT_BACKGROUND


def accent_text_color(accent: str) -> str:
    """Tugma ustidagi matn: oq yoki qora — qaysi biri rang bilan ko'proq farq qilsa."""
    return "#FFFFFF" if contrast(accent, "#FFFFFF") >= contrast(accent, "#000000") else "#000000"


# ------------------------------------------------------------------ ko'rib chiqish tokeni (storefront.md §0)

PREVIEW_TTL = timedelta(minutes=30)
_NONCE = re.compile(r"[A-Za-z0-9_-]{8,32}")


class PreviewSigner:
    """Ega saytni ochishdan oldin xaridor ko'rganidek ko'radi. Token bazada saqlanmaydi: shop + muddat + HMAC.

    `{shop_id}.{exp}.{nonce}.{sig}` — faqat shu shop va 30 daqiqa. Tasodifiy `nonce` har chiqarishda boshqa
    token beradi (bir soniyada ikki marta so'ralsa ham — QA M04 F7); tekshiruv baribir holatsiz.
    Kalit JWT kalitidan alohida maqsad bilan olinadi.
    """

    def __init__(self, secret: str) -> None:
        self._key = hashlib.sha256(b"cos-storefront-preview\x00" + secret.encode()).digest()

    def _sig(self, shop_id: UUID, exp: int, nonce: str) -> str:
        return hmac.new(self._key, f"{shop_id}\n{exp}\n{nonce}".encode(), hashlib.sha256).hexdigest()

    def issue(self, shop_id: UUID, now: datetime | None = None) -> tuple[str, datetime]:
        expires_at = (now or utcnow()) + PREVIEW_TTL
        exp = int(expires_at.timestamp())
        nonce = secrets.token_urlsafe(9)  # 12 belgi, nuqtasiz
        return f"{shop_id.hex}.{exp}.{nonce}.{self._sig(shop_id, exp, nonce)}", expires_at

    def valid_for(self, token: str | None, shop_id: UUID, now: datetime | None = None) -> bool:
        if not token or len(token) > 200:
            return False
        parts = token.split(".")
        if (
            len(parts) != 4
            or parts[0] != shop_id.hex
            or not parts[1].isdigit()
            or not _NONCE.fullmatch(parts[2])
        ):
            return False
        exp = int(parts[1])
        if exp < int((now or utcnow()).timestamp()):
            return False
        return hmac.compare_digest(self._sig(shop_id, exp, parts[2]), parts[3])


# ------------------------------------------------------------------ kesh (08 §4)

DOMAIN = "storefront"
SLUG_TTL = 600  # slug → shop_id
SITE_TTL = 300  # sayt sozlamalari va sahifalar (saqlanganda darhol o'chiriladi)
LIST_TTL = 60  # katalog ro'yxati va mahsulot sahifasi (+ jitter)
JITTER = 10


def slug_key(slug: str) -> str:
    return global_key(DOMAIN, slug=slug)


def site_key(shop_id: UUID) -> str:
    return shop_key(shop_id, DOMAIN, "site")


def pages_key(shop_id: UUID) -> str:
    return shop_key(shop_id, DOMAIN, "pages")


def index_version_key(shop_id: UUID) -> str:
    return shop_key(shop_id, DOMAIN, "index_version")


async def index_version(cache: Cache, shop_id: UUID) -> int:
    """Ro'yxat kalitlarining versiyasi: oshirilsa eski ro'yxatlar birdan eskiradi (08 §4.3)."""
    return int(await cache.get(index_version_key(shop_id)) or 0)


async def invalidate_shop(cache: Cache, shop_id: UUID) -> None:
    """Sayt sozlamasi yoki sahifa saqlandi: sozlamalar darhol, ro'yxatlar versiya bilan."""
    await cache.delete(site_key(shop_id), pages_key(shop_id))
    await cache.incr(index_version_key(shop_id))


async def cached_json(
    cache: Cache, key: str, ttl: int, produce: Callable[[], Awaitable[Any]], *, jitter: bool = False
) -> Any:
    """Keshdan JSON; bo'lmasa — `produce()` va saqlash. Kesh ishlamasa ham javob to'g'ri (DB'dan)."""
    hit = await cache.get(key)
    if hit is not None:
        return json.loads(hit)
    value = await produce()
    extra = random.randint(0, JITTER) if jitter else 0  # noqa: S311 — kesh tarqoqligi, kriptografiya emas
    await cache.set(key, json.dumps(value, default=str), ttl + extra)
    return value
