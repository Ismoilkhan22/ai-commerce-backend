"""Vazifa navbati — `app.shared.queue` da (platforma admini API'si ham ishlatadi); bu yerda qayta eksport."""

from __future__ import annotations

from app.shared.queue import ArqQueue, RecordingQueue, TaskQueue

__all__ = ["ArqQueue", "RecordingQueue", "TaskQueue"]
