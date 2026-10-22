"""Til aniqlash va backend tarjimalari (11 §8)."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.shared.i18n.locale import get_locale, negotiate_locale
from app.shared.i18n.translator import missing_keys, t
from app.shared.types.manifest import DomainManifest


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "uz"),
        ("", "uz"),
        ("ru", "ru"),
        ("ru-RU,ru;q=0.9,en;q=0.8", "ru"),
        ("de-DE,en;q=0.5,ru;q=0.7", "ru"),
        ("en;q=0.9,uz;q=0.9", "en"),  # bir xil q — header tartibi
        ("uz-Cyrl", "uz"),  # kirill interfeysi yo'q — lotin
        ("fr,de", "uz"),
        ("ru;q=0", "uz"),
        ("ru;q=abc,en", "en"),
    ],
)
def test_negotiate_locale(header: str | None, expected: str) -> None:
    assert negotiate_locale(header) == expected


def test_request_locale_from_accept_language(settings: Settings) -> None:  # TC-CONV-05 (profil tili — S0-04)
    router = APIRouter()

    @router.get("/locale")
    async def locale() -> dict[str, str]:
        return {"locale": get_locale(), "text": t("errors.NOT_FOUND")}

    app = create_app(settings, manifests=[DomainManifest(name="test", routers={"shop": router})])
    client = TestClient(app)
    assert client.get("/api/v1/shop/locale", headers={"Accept-Language": "ru"}).json() == {
        "locale": "ru",
        "text": "Не найдено",
    }
    assert client.get("/api/v1/shop/locale").json()["locale"] == "uz"


def test_translation_fallbacks() -> None:
    assert t("errors.NOT_FOUND", "en") == "Not found"
    assert t("no.such.key", "ru") == "no.such.key"


def test_locales_have_same_keys() -> None:
    assert all(not keys for keys in missing_keys().values()), missing_keys()
