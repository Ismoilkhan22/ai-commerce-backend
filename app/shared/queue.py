"""Vazifa navbati (arq, Redis db1 — 06 §4.1). Service bu yerga o'zi yozmaydi — faqat outbox_worker,
rekonsilyatsiya, scheduler va platforma adminining dead-letter "qayta yuborish"i (ADR-033, 05 §7).

`job_id` — takror himoyasi: arq bir xil ID'li vazifani ikkinchi marta qo'ymaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from arq.connections import ArqRedis


class TaskQueue(Protocol):
    async def enqueue(self, function: str, *, job_id: str, defer_seconds: int = 0, **kwargs: Any) -> bool:
        """True — qo'yildi; False — shu `job_id` allaqachon navbatda (dublikat)."""
        ...


class ArqQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self.pool = pool

    async def enqueue(self, function: str, *, job_id: str, defer_seconds: int = 0, **kwargs: Any) -> bool:
        job = await self.pool.enqueue_job(
            function,
            _job_id=job_id,
            _defer_by=timedelta(seconds=defer_seconds) if defer_seconds else None,
            **kwargs,
        )
        return job is not None


@dataclass
class RecordingQueue:
    """Testlar va Redis'siz lokal: vazifalar ro'yxatga yoziladi, `run_recorded` bilan bajariladi."""

    jobs: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    _ids: set[str] = field(default_factory=set)
    fail: Exception | None = None  # Redis o'chiq holatini sinash uchun

    async def enqueue(self, function: str, *, job_id: str, defer_seconds: int = 0, **kwargs: Any) -> bool:
        if self.fail is not None:
            raise self.fail
        if job_id in self._ids:
            return False
        self._ids.add(job_id)
        self.jobs.append((function, job_id, kwargs))
        return True

    def take(self) -> list[tuple[str, str, dict[str, Any]]]:
        jobs, self.jobs = self.jobs, []
        return jobs

    def forget(self, job_id: str) -> None:
        """Vazifa tugadi (arq natijani o'chirdi) — shu ID bilan qayta qo'yish mumkin."""
        self._ids.discard(job_id)
