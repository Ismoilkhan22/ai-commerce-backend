"""Idempotency header va hash, audit diff himoyasi — DB'siz."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.platform.audit.services.audit_service import AuditDiffError, _check_diff
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.store import request_hash
from app.shared.types.manifest import DomainManifest


def test_request_hash_ignores_key_order_but_not_values() -> None:
    a = request_hash("post", "/api/v1/shop/orders", {"b": 1, "a": [1, 2]})
    b = request_hash("POST", "/api/v1/shop/orders", {"a": [1, 2], "b": 1})
    assert a == b
    assert a != request_hash("POST", "/api/v1/shop/orders", {"a": [2, 1], "b": 1})
    assert a != request_hash("POST", "/api/v1/shop/other", {"a": [1, 2], "b": 1})


@pytest.fixture
def client(settings: Settings) -> TestClient:
    router = APIRouter()

    @router.post("/things")
    async def create(key: Annotated[str, Depends(get_idempotency_key)]) -> dict[str, str]:
        return {"key": key}

    return TestClient(create_app(settings, manifests=[DomainManifest(name="t", routers={"shop": router})]))


def test_missing_idempotency_key_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/v1/shop/things")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["error"]["details"] == {"header": "Idempotency-Key"}


@pytest.mark.parametrize("bad", ["short", "has space here", "x" * 129])
def test_malformed_idempotency_key(client: TestClient, bad: str) -> None:
    assert client.post("/api/v1/shop/things", headers={"Idempotency-Key": bad}).status_code == 400


def test_valid_idempotency_key(client: TestClient) -> None:
    key = "0192b6f0-3c1a-7c2e-9f00-5a1b2c3d4e5f"
    assert client.post("/api/v1/shop/things", headers={"Idempotency-Key": key}).json() == {"key": key}


@pytest.mark.parametrize(
    "diff",
    [
        {"customer_phone": "+998901234567"},
        {"changes": {"delivery_address": "x"}},
        {"items": [{"refresh_token": "t"}]},
    ],
)
def test_audit_diff_rejects_pii_and_secrets(diff: dict[str, object]) -> None:
    with pytest.raises(AuditDiffError):
        _check_diff(diff)


def test_audit_diff_allows_business_fields() -> None:
    _check_diff({"price": {"old": {"amount_minor": 100, "currency": "UZS"}, "new": {"amount_minor": 120}}})
