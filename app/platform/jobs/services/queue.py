"""API jarayonidan vazifa navbati — faqat platforma admini "qayta yuborish" bosganda (05 §7, QA 5a F1).

Pool birinchi kerak bo'lganda ochiladi (Redis o'chiq bo'lsa API ishga tushishi to'xtamaydi). Xotira rejimida
(testlar) — `RecordingQueue`: test navbatni `app.state.task_queue` dan o'qiydi.
"""

from __future__ import annotations

import asyncio

from arq import create_pool
from arq.connections import RedisSettings
from starlette.datastructures import State

from app.shared.queue import ArqQueue, RecordingQueue, TaskQueue

_lock = asyncio.Lock()


async def task_queue(state: State) -> TaskQueue:
    queue: TaskQueue | None = getattr(state, "task_queue", None)
    if queue is not None:
        return queue
    async with _lock:
        queue = getattr(state, "task_queue", None)
        if queue is None:
            url: str | None = getattr(state, "arq_redis_url", None)
            queue = ArqQueue(await create_pool(RedisSettings.from_dsn(url))) if url else RecordingQueue()
            state.task_queue = queue
    return queue
