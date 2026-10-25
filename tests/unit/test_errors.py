"""K-07 envelope va xato katalogi (11 §6–7): TC-CONV-01…04."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.orm.exc import StaleDataError

from app.config.settings import Settings
from app.main import create_app
from app.shared.errors import base
from app.shared.errors.catalog import ERROR_CATALOG, FRAMEWORK_ONLY_CODES
from app.shared.i18n.locale import SUPPORTED_LOCALES
from app.shared.i18n.translator import load_catalog
from app.shared.types.manifest import DomainManifest


class LineIn(BaseModel):
    sku_id: str
    quantity: int = Field(ge=1)


class OrderIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1)


class DiscountIn(BaseModel):
    percent: Decimal = Field(ge=Decimal("0.01"), le=Decimal("100"))


SKU_ID = UUID("0192b6f0-3c1a-7c2e-9f00-5a1b2c3d4e5f")


router = APIRouter()


@router.post("/orders")
async def create_order(body: OrderIn) -> dict[str, int]:
    return {"lines": len(body.lines)}


@router.get("/orders/{order_id}")
async def get_order(order_id: str) -> dict[str, str]:
    raise base.NotFoundError("Order not found", order_id=order_id)


@router.post("/orders/{order_id}/confirm")
async def confirm_order(order_id: str) -> dict[str, str]:
    raise base.InsufficientStockError(
        "Insufficient available stock", lines=[{"sku_id": "s1", "requested": 1, "available": 0}]
    )


@router.post("/discounts")
async def apply_discount(body: DiscountIn) -> dict[str, str]:
    return {"percent": str(body.percent)}


@router.post("/orders/{order_id}/lines")
async def add_line(order_id: str) -> dict[str, str]:
    # details'da UUID va Decimal — JSON'ga xavfsiz aylanishi kerak
    raise base.DiscountLimitExceededError("Too big", sku_id=SKU_ID, requested_percent=Decimal("8.5"))


@router.patch("/settings")
async def update_settings() -> dict[str, str]:
    raise StaleDataError(
        "UPDATE statement on table 'shop_policies' expected to update 1 row(s); 0 were matched."
    )


@router.get("/legacy-conflict")
async def legacy_conflict() -> dict[str, str]:
    from fastapi import HTTPException

    raise HTTPException(status_code=409, detail="conflict from a library")


@router.post("/busy")
async def busy() -> dict[str, str]:
    raise base.RateLimitedError("Too many requests", retry_after_seconds=42)


@router.get("/boom")
async def boom() -> dict[str, str]:
    raise RuntimeError("database password=secret leaked?")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings, manifests=[DomainManifest(name="test", routers={"shop": router})])


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _assert_envelope(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}, "FastAPI {'detail': ...} formati chiqmasligi kerak"
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "details", "trace_id"}
    assert error["code"] == code
    assert isinstance(error["trace_id"], str) and len(error["trace_id"]) == 32
    return error


def test_validation_error_envelope(client: TestClient) -> None:  # TC-CONV-01
    response = client.post("/api/v1/shop/orders", json={"lines": [{"sku_id": "a", "quantity": 0}]})
    assert response.status_code == 422
    error = _assert_envelope(response.json(), "VALIDATION_FAILED")
    assert error["details"] == {
        "fields": [{"field": "lines[0].quantity", "code": "min_value", "params": {"min": 1}}]
    }


def test_missing_field_and_bad_json(client: TestClient) -> None:
    response = client.post("/api/v1/shop/orders", json={})
    field = response.json()["error"]["details"]["fields"][0]
    assert (field["field"], field["code"]) == ("lines", "required")

    response = client.post(
        "/api/v1/shop/orders", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400  # buzuq JSON — maydon xatosi emas
    _assert_envelope(response.json(), "INVALID_REQUEST")


def test_rate_limited_sets_retry_after_header(client: TestClient) -> None:
    response = client.post("/api/v1/shop/busy")
    assert response.status_code == 429
    assert _assert_envelope(response.json(), "RATE_LIMITED")["details"] == {"retry_after_seconds": 42}
    assert response.headers["Retry-After"] == "42"


def test_unknown_path_and_method(client: TestClient) -> None:  # TC-CONV-02
    response = client.get("/api/v1/shop/nope")
    assert response.status_code == 404
    _assert_envelope(response.json(), "NOT_FOUND")

    response = client.delete("/api/v1/shop/orders")
    assert response.status_code == 405
    _assert_envelope(response.json(), "METHOD_NOT_ALLOWED")


def test_domain_errors_map_to_catalog_status(client: TestClient) -> None:
    response = client.get("/api/v1/shop/orders/42")
    assert response.status_code == 404
    assert _assert_envelope(response.json(), "NOT_FOUND")["details"] == {"order_id": "42"}

    response = client.post("/api/v1/shop/orders/42/confirm")
    assert response.status_code == 409
    error = _assert_envelope(response.json(), "INSUFFICIENT_AVAILABLE_STOCK")
    assert error["details"] == {"lines": [{"sku_id": "s1", "requested": 1, "available": 0}]}


def test_decimal_constraint_returns_422_not_500(client: TestClient) -> None:
    response = client.post("/api/v1/shop/discounts", json={"percent": "0"})
    assert response.status_code == 422
    field = _assert_envelope(response.json(), "VALIDATION_FAILED")["details"]["fields"][0]
    assert (field["field"], field["code"], field["params"]) == ("percent", "min_value", {"min": "0.01"})


def test_domain_error_details_with_uuid_and_decimal(client: TestClient) -> None:
    response = client.post("/api/v1/shop/orders/1/lines")
    assert response.status_code == 422
    error = _assert_envelope(response.json(), "DISCOUNT_LIMIT_EXCEEDED")
    assert error["details"] == {"sku_id": str(SKU_ID), "requested_percent": "8.5"}


def test_stale_data_becomes_version_conflict(client: TestClient) -> None:
    response = client.patch("/api/v1/shop/settings")
    assert response.status_code == 409
    error = _assert_envelope(response.json(), "VERSION_CONFLICT")
    assert "shop_policies" not in response.text  # jadval nomi tashqariga chiqmaydi
    assert error["details"] == {}


def test_unmapped_4xx_keeps_its_status(client: TestClient) -> None:
    response = client.get("/api/v1/shop/legacy-conflict")
    assert response.status_code == 409  # 500 emas — klient "qayta urinish mumkin" deb o'ylamasin
    _assert_envelope(response.json(), "INVALID_REQUEST")


def test_unexpected_exception_is_hidden(client: TestClient) -> None:  # TC-CONV-03
    response = client.get("/api/v1/shop/boom", headers={"X-Request-ID": "req-12345678"})
    assert response.status_code == 500
    error = _assert_envelope(response.json(), "INTERNAL_ERROR")
    assert "secret" not in response.text
    assert error["message"] == "Internal server error"
    assert response.headers["X-Request-ID"] == "req-12345678"


def test_trace_id_comes_from_traceparent(client: TestClient) -> None:
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = client.get("/api/v1/shop/nope", headers={"traceparent": f"00-{trace}-00f067aa0ba902b7-01"})
    assert response.json()["error"]["trace_id"] == trace


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(response.headers["X-Request-ID"]) == 32


def _concrete_error_classes() -> list[type[base.DomainError]]:
    classes: list[type[base.DomainError]] = []
    stack: list[type[base.DomainError]] = [base.DomainError]
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if not cls.abstract:
            classes.append(cls)
    return classes


def test_every_error_class_is_in_catalog() -> None:  # TC-CONV-04
    missing = {cls.__name__ for cls in _concrete_error_classes() if cls.code not in ERROR_CATALOG}
    assert not missing


def test_every_catalog_code_has_class() -> None:  # TC-CONV-04
    class_codes = {cls.code for cls in _concrete_error_classes()}
    assert set(ERROR_CATALOG) - class_codes - FRAMEWORK_ONLY_CODES == set()


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_catalog_code_is_translated(locale: str) -> None:  # TC-CONV-04
    catalog = load_catalog(locale)  # type: ignore[arg-type]
    missing = {code for code in ERROR_CATALOG if f"errors.{code}" not in catalog}
    assert not missing, f"{locale}: {sorted(missing)}"
