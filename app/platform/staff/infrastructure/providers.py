"""Platform servislarini app.state'dan olish (main.py bir marta yaratadi)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.platform.auth.services.auth_service import AuthService


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service  # type: ignore[no-any-return]
