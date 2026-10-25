"""FileService'ni app.state'dan olish (main.py bir marta yaratadi)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.platform.storage.services.file_service import FileService


def file_service(request: Request) -> FileService:
    return request.app.state.file_service  # type: ignore[no-any-return]
