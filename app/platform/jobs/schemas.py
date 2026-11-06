"""Platforma paneli: dead-letter va rejali ishlar sog'ligi (05 §7, 06 §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.text import Text

DeadLetterStatus = Literal["OPEN", "REPLAYED", "IGNORED"]


class DeadLetterOut(BaseModel):
    id: UUID
    event_id: UUID
    source_schema: str
    event_type: str
    consumer: str
    shop_id: UUID | None
    attempts: int
    last_error: str
    first_failed_at: datetime
    last_failed_at: datetime
    status: DeadLetterStatus
    resolved_at: datetime | None
    resolution_note: str | None


class DeadLetterList(BaseModel):
    items: list[DeadLetterOut]
    open_count: int


class DeadLetterResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Text = Field(min_length=3, max_length=500)


class JobHealth(BaseModel):
    """Har ro'yxatdagi ish — hali bir marta ham ishlamagani ham (QA 5a I2): `last_*` bo'sh bo'ladi."""

    job_name: str
    schedule: str | None  # "every 900s" yoki cron ("30 3 * * *", Asia/Tashkent)
    interval_seconds: int | None  # taxminiy oraliq — "3 × oraliq" ogohlantirishi uchun (06 §8)
    overdue: bool  # oxirgi muvaffaqiyatli ishdan 3 × oraliqdan ko'p o'tdi (yoki hech ishlamadi)
    alert: bool  # oxirgi ish ogohlantirish qoldirdi (masalan ombor solishtiruvida farq) — platforma ko'rsin
    last_status: Literal["RUNNING", "OK", "FAILED", "SKIPPED"] | None
    last_started_at: datetime | None
    last_ok_at: datetime | None
    last_error: str | None
    last_details: dict[str, Any]


class JobHealthList(BaseModel):
    items: list[JobHealth]
