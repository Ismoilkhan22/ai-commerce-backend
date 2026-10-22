"""Ilova yig'ilishi: surface prefikslari, yo'l to'qnashuvi, health (S0-02)."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import RouteConflictError, create_app
from app.shared.types.manifest import DomainManifest


def _router(path: str) -> APIRouter:
    router = APIRouter()

    @router.get(path)
    async def handler() -> dict[str, str]:
        return {"ok": "yes"}

    return router


def test_routers_are_mounted_under_surface_prefixes(settings: Settings) -> None:
    manifest = DomainManifest(
        name="commerce",
        routers={"shop": _router("/orders"), "storefront": _router("/order-requests")},
    )
    client = TestClient(create_app(settings, manifests=[manifest]))
    assert client.get("/api/v1/shop/orders").status_code == 200
    assert client.get("/api/v1/storefront/acme/order-requests").status_code == 200
    assert client.get("/api/v1/shop/commerce/orders").status_code == 404  # URL'da domen nomi yo'q


def test_same_route_in_two_modules_fails_on_boot(settings: Settings) -> None:  # TC-API-07
    first = DomainManifest(name="catalog", routers={"shop": _router("/products")})
    second = DomainManifest(name="commerce", routers={"shop": _router("/products")})
    with pytest.raises(RouteConflictError, match="catalog"):
        create_app(settings, manifests=[first, second])


def test_same_path_on_different_surfaces_is_allowed(settings: Settings) -> None:
    first = DomainManifest(name="catalog", routers={"shop": _router("/products")})
    second = DomainManifest(name="storefront", routers={"storefront": _router("/products")})
    create_app(settings, manifests=[first, second])


def test_health_live_and_ready(settings: Settings) -> None:
    with TestClient(create_app(settings, manifests=[])) as client:
        client.app.state.readiness_checks = {}  # type: ignore[attr-defined]  # DB'siz unit test
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ready", "checks": {}}


def test_health_ready_reports_failed_check(settings: Settings) -> None:
    async def failing() -> None:
        raise ConnectionError("postgres down")

    with TestClient(create_app(settings, manifests=[])) as client:
        client.app.state.readiness_checks = {"postgres": failing}  # type: ignore[attr-defined]
        response = client.get("/health/ready")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_UNAVAILABLE"
    assert error["details"] == {"checks": {"postgres": "fail"}}
    assert "postgres down" not in response.text


def test_real_app_discovers_manifests_without_error() -> None:
    from app.main import app

    assert app.title == "AI Commerce OS API"
