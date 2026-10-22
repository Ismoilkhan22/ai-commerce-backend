"""UUIDv7 (RFC 9562) — vaqt bo'yicha tartiblangan ID (07 §2). Python 3.12 da `uuid.uuid7` yo'q."""

from __future__ import annotations

import os
import threading
import time
from uuid import UUID

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> UUID:
    """48 bit ms vaqt + 12 bit monoton hisoblagich (bir ms ichida tartib) + 62 bit tasodifiy."""
    global _last_ms, _counter
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms <= _last_ms:
            _counter += 1
            if _counter > 0xFFF:  # bir ms da 4096 dan ko'p — keyingi ms ga o'tamiz
                _last_ms += 1
                _counter = 0
            now_ms = _last_ms
        else:
            _last_ms = now_ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF  # tasodifiy boshlanish, o'sish uchun joy
        counter = _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (now_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= counter << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand_b
    return UUID(int=value)
