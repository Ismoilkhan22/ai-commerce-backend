"""Kirish logida xaridor telefoni bo'lmasin (QA 3-modul F2, 26 §4): query qiymatlari yozilmaydi."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from app.config.logging import configure_logging
from app.shared.tracing import middleware
from app.shared.tracing.middleware import RequestContextMiddleware, query_keys


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


async def _ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


def test_query_keys_keep_names_only() -> None:
    assert query_keys(b"q=%2B998901234567&limit=20&q=x") == ["limit", "q"]
    assert query_keys(b"") == []


async def test_access_log_never_contains_query_values(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(middleware, "access_logger", recorder)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/shop/orders",
        "query_string": b"q=%2B998+93+555+01+24&status=CONFIRMED",
        "headers": [],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: dict[str, Any]) -> None:
        return None

    await RequestContextMiddleware(_ok_app)(scope, receive, send)
    assert len(recorder.events) == 1
    event, fields = recorder.events[0]
    assert event == "http.request"
    assert fields["query_keys"] == ["q", "status"] and fields["status"] == 200
    assert "555" not in repr(fields) and "998" not in repr(fields)


def test_uvicorn_access_log_is_disabled() -> None:
    configure_logging("INFO", json=True)
    assert logging.getLogger("uvicorn.access").disabled is True


def test_redact_path_masks_tokens_and_ids() -> None:
    token = "dMvqXiys3Mr-tMGfpBXVUURod4Ozft4LEVbkwsLhy0Y"
    assert middleware.redact_path(f"/api/v1/auth/invites/{token}/accept") == (
        "/api/v1/auth/invites/{seg}/accept"
    )
    assert middleware.redact_path("/api/v1/shop/orders/01a16e27-a876-71d6-8ed2-dc26fe760440") == (
        "/api/v1/shop/orders/{id}"
    )
    assert middleware.redact_path("/x/+998901234567") == "/x/{seg}"


def test_access_log_uses_route_template_not_raw_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    recorder = _Recorder()
    monkeypatch.setattr(middleware, "access_logger", recorder)
    app = FastAPI()

    @app.post("/api/v1/auth/invites/{token}/accept")
    async def accept(token: str) -> dict[str, str]:
        return {}

    client = TestClient(RequestContextMiddleware(app))
    secret = "dMvqXiys3Mr-tMGfpBXVUURod4Ozft4LEVbkwsLhy0Y"
    client.post(f"/api/v1/auth/invites/{secret}/accept")
    client.get(f"/api/v1/unknown/{secret}")
    paths = [fields["path"] for _, fields in recorder.events]
    assert paths == ["/api/v1/auth/invites/{token}/accept", "/api/v1/unknown/{seg}"]
    assert all(secret not in repr(fields) for _, fields in recorder.events)
