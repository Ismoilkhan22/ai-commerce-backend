"""HttpInstagramClient.get_account: Page tokeni (instagram_business_account) va Instagram-login tokeni."""

from __future__ import annotations

import httpx
import pytest

from app.domains.messaging.channels import instagram as ig_mod
from app.domains.messaging.channels.base import ChannelConnectError
from app.domains.messaging.channels.instagram import HttpInstagramClient


def _patch(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(ig_mod.httpx, "AsyncClient", lambda **kw: real(transport=handler, **kw))


async def test_page_token_returns_linked_instagram_account(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "instagram_business_account" in request.url.params["fields"]
        return httpx.Response(
            200, json={"id": "1", "instagram_business_account": {"id": "178", "username": "shop"}}
        )

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = await HttpInstagramClient().get_account("tok")
    assert (account.id, account.username) == ("178", "shop")


async def test_page_without_instagram_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "1"})))
    with pytest.raises(ChannelConnectError):
        await HttpInstagramClient().get_account("tok")


async def test_user_token_resolves_page_token_via_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me/accounts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1",
                            "access_token": "PAGE",
                            "instagram_business_account": {"id": "178", "username": "shop"},
                        }
                    ]
                },
            )
        return httpx.Response(400, json={"error": {"code": 100}})  # /me User tugunida Instagram maydoni yo'q

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = await HttpInstagramClient().get_account("USER")
    assert (account.id, account.username, account.token) == ("178", "shop", "PAGE")


async def test_instagram_login_token_falls_back_to_me(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if (
            request.url.path.endswith("/me/accounts")
            or "instagram_business_account" in request.url.params["fields"]
        ):
            return httpx.Response(400, json={"error": {"code": 100}})
        return httpx.Response(200, json={"id": "55", "username": "me"})

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = await HttpInstagramClient().get_account("tok")
    assert (account.id, account.username) == ("55", "me")


async def test_invalid_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"code": 190}})))
    with pytest.raises(ChannelConnectError):
        await HttpInstagramClient().get_account("tok")


async def test_instagram_login_token_uses_graph_instagram(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "app-scoped", "user_id": "1784", "username": "shop"})

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = await HttpInstagramClient().get_account("IGAAtoken")
    assert (account.id, account.username) == ("1784", "shop")
    assert seen[0].url.host == "graph.instagram.com"


async def test_subscribe_instagram_login_subscribes_account(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True})

    _patch(monkeypatch, httpx.MockTransport(handler))
    ok = await HttpInstagramClient().subscribe("IGAAtoken", ig_mod.InstagramAccount("1784", "shop"))
    assert ok is True
    assert seen[0].url.host == "graph.instagram.com" and seen[0].url.path.endswith("/1784/subscribed_apps")
    assert seen[0].url.params["subscribed_fields"] == "messages,comments"


async def test_subscribe_facebook_login_subscribes_page(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True})

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = ig_mod.InstagramAccount("178", "shop", page_id="1493")
    assert await HttpInstagramClient().subscribe("EAAtoken", account) is True
    assert seen[0].url.host == "graph.facebook.com" and seen[0].url.path.endswith("/1493/subscribed_apps")


async def test_system_user_token_finds_instagram_account_via_debug_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": []})
        if path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={"data": {"granular_scopes": [{"scope": "instagram_basic", "target_ids": ["1784"]}]}},
            )
        if path.endswith("/1784"):
            return httpx.Response(200, json={"id": "1784", "username": "shop"})
        return httpx.Response(400, json={"error": {"code": 100}})  # /me — Page emas

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = await HttpInstagramClient().get_account("EAAsuat", app_token="1|secret")
    assert (account.id, account.username) == ("1784", "shop")


async def test_system_user_token_without_app_credentials_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(400, json={"error": {"code": 100}})

    _patch(monkeypatch, httpx.MockTransport(handler))
    with pytest.raises(ChannelConnectError):
        await HttpInstagramClient().get_account("EAAsuat")


async def test_system_user_token_with_explicit_account_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/17841462299764460"):
            return httpx.Response(200, json={"id": "17841462299764460", "username": "shop"})
        return httpx.Response(400, json={"error": {"code": 100}})

    _patch(monkeypatch, httpx.MockTransport(handler))
    account = await HttpInstagramClient().get_account("EAAsuat", account_id="17841462299764460")
    assert (account.id, account.username) == ("17841462299764460", "shop")


async def test_extend_token_exchanges_short_for_long(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/oauth/access_token")
        assert request.url.params["grant_type"] == "fb_exchange_token"
        return httpx.Response(200, json={"access_token": "LONG", "expires_in": 5183944})

    _patch(monkeypatch, httpx.MockTransport(handler))
    assert await HttpInstagramClient().extend_token("SHORT", app_id="1", app_secret="s") == "LONG"


async def test_extend_token_failure_keeps_original(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"code": 190}})))
    assert await HttpInstagramClient().extend_token("SHORT", app_id="1", app_secret="s") is None
