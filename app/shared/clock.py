"""Vaqt manbai. Kodda `datetime.now()` o'rniga shu — testlarda vaqtni surish mumkin bo'lsin."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
