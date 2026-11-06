"""Til aniqlash (11 §8.1–8.2). Interfeys tillari: uz (manba), ru, en."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal, cast, get_args

Locale = Literal["uz", "ru", "en"]
SUPPORTED_LOCALES: tuple[Locale, ...] = get_args(Locale)
FALLBACK_LOCALE: Locale = "uz"

_current_locale: ContextVar[Locale] = ContextVar("locale", default=FALLBACK_LOCALE)


# Interfeys tili — `Accept-Language` bo'lsa (panel til tanlagichi har so'rovga qo'yadi). Profil tili (11 §8.2)
# xabarlar/bot matnlariga ustun; sahifada ko'rsatiladigan ma'lumot matni (moslik izohi) — interfeys tilida
# (QA 6a F3). Header bo'lmasa — `get_locale()`.
_display_locale: ContextVar[Locale | None] = ContextVar("display_locale", default=None)


def get_locale() -> Locale:
    return _current_locale.get()


def set_locale(locale: Locale) -> None:
    _current_locale.set(locale)


def get_display_locale() -> Locale:
    return _display_locale.get() or _current_locale.get()


def set_display_locale(locale: Locale | None) -> None:
    _display_locale.set(locale)


def negotiate_locale(accept_language: str | None, default: Locale = FALLBACK_LOCALE) -> Locale:
    """`Accept-Language` dan qo'llab-quvvatlanadigan eng yuqori `q` li tilni tanlaydi.

    `uz-Cyrl` interfeysi Stage 1 da yo'q — `uz` ga tushadi (11 §8.1).
    """
    if not accept_language:
        return default
    candidates: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language.split(",")):
        lang, _, params = part.strip().partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                continue
        primary = lang.strip().lower().split("-")[0]
        if quality > 0 and primary in SUPPORTED_LOCALES:
            # bir xil q bo'lsa — header'dagi tartib
            candidates.append((-quality, index, primary))
    if not candidates:
        return default
    return cast(Locale, min(candidates)[2])
