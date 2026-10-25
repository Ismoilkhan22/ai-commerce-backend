"""Platform servislarini app.state'dan olish (main.py bir marta yaratadi)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.platform.auth.services.auth_service import AuthService
    from app.platform.shops.services.platform_queries import PlatformQueryService
    from app.platform.shops.services.shop_service import ShopService
    from app.platform.staff.services.platform_team_service import PlatformTeamService
    from app.platform.staff.services.staff_service import StaffService


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service  # type: ignore[no-any-return]


def staff_service(request: Request) -> StaffService:
    return request.app.state.staff_service  # type: ignore[no-any-return]


def shop_service(request: Request) -> ShopService:
    return request.app.state.shop_service  # type: ignore[no-any-return]


def platform_queries(request: Request) -> PlatformQueryService:
    return request.app.state.platform_queries  # type: ignore[no-any-return]


def platform_team(request: Request) -> PlatformTeamService:
    return request.app.state.platform_team  # type: ignore[no-any-return]
