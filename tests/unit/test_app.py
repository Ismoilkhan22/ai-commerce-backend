"""Ilova yig'ilishi: surface prefikslari, yo'l to'qnashuvi, health (S0-02)."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import RouteConflictError, create_app
from app.shared.types.manifest import DomainManifest


def _router(path: str, prefix: str = "") -> APIRouter:
    router = APIRouter(prefix=prefix)

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


def test_conflict_between_prefixed_and_plain_router_is_detected(settings: Settings) -> None:
    # Bir xil yakuniy manzil: /api/v1/shop/orders/{id} — biri prefiks bilan, biri prefikssiz
    first = DomainManifest(name="commerce", routers={"shop": _router("/{order_id}", prefix="/orders")})
    second = DomainManifest(name="support", routers={"shop": _router("/orders/{order_id}")})
    with pytest.raises(RouteConflictError, match="/api/v1/shop/orders/\\{order_id\\}"):
        create_app(settings, manifests=[first, second])


def test_conflict_with_differently_named_path_params_is_detected(settings: Settings) -> None:
    # /orders/{order_id} va /orders/{case_id} — bir xil manzil; ikkinchisi jimgina yopilib qolardi
    first = DomainManifest(name="commerce", routers={"shop": _router("/orders/{order_id}")})
    second = DomainManifest(name="support", routers={"shop": _router("/orders/{case_id}")})
    with pytest.raises(RouteConflictError):
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


def test_openapi_describes_bearer_auth_for_frontend_client(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        spec = client.get("/api/v1/openapi.json").json()
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    operations = [op for path in spec["paths"].values() for op in path.values()]
    ids = [op["operationId"] for op in operations]
    assert len(ids) == len(set(ids)) and "auth_login" in ids and "staff_invite_member" in ids
    me = spec["paths"]["/api/v1/auth/me"]["get"]
    assert me["security"] == [{"HTTPBearer": []}]
    assert "security" not in spec["paths"]["/api/v1/auth/login"]["post"]  # login ochiq
