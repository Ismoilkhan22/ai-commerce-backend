"""Auth yordamchilari: telefon, parol talablari, tokenlar, ruxsatlar reyestri (DB'siz)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.platform.auth.config import AuthConfig
from app.platform.auth.passwords import PasswordHasher, validate_new_password
from app.platform.auth.tokens import (
    AccessClaims,
    decode_access_token,
    hash_token,
    issue_access_token,
    new_refresh_token,
    parse_refresh_token,
)
from app.platform.staff.permissions import PermissionRegistry
from app.shared.errors.base import UnauthenticatedError, ValidationError
from app.shared.phone import normalize_phone

CONFIG = AuthConfig(jwt_secret="unit-test-secret-" + "x" * 32)


@pytest.mark.parametrize(
    "raw", ["+998 90 123-45-67", "998901234567", "901234567", "(90) 123 45 67", "+998901234567"]
)
def test_phone_normalized_to_e164(raw: str) -> None:
    assert normalize_phone(raw) == "+998901234567"


@pytest.mark.parametrize("raw", ["", "12345", "+7 900 123 45 67", "99890123456789"])
def test_invalid_phone_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        normalize_phone(raw)


@pytest.mark.parametrize(
    ("password", "code"),
    [("short1", "min_length"), ("12345678", "too_weak"), ("Password", "too_weak"), ("x" * 129, "max_length")],
)
def test_weak_passwords_rejected(password: str, code: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_new_password(password)
    assert exc.value.details["fields"][0]["code"] == code  # type: ignore[index]


def test_password_containing_phone_digits_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_new_password("ab901234567", phone="+998901234567")
    validate_new_password("Kuchli-parol-2026", phone="+998901234567")


async def test_hasher_verifies_and_resists_missing_hash() -> None:
    hasher = PasswordHasher(time_cost=1, memory_kib=1024, parallelism=1)
    stored = await hasher.hash("Kuchli-parol-2026")
    assert await hasher.verify(stored, "Kuchli-parol-2026")
    assert not await hasher.verify(stored, "boshqa")
    assert not await hasher.verify(None, "Kuchli-parol-2026")  # hash yo'q — doim False


def _claims(audience: str = "shop") -> AccessClaims:
    return AccessClaims(uuid4(), uuid4(), uuid4() if audience == "shop" else None, audience)  # type: ignore[arg-type]


def test_access_token_roundtrip() -> None:
    claims = _claims()
    token, expires_in = issue_access_token(CONFIG, claims, datetime.now(UTC))
    assert expires_in == 900
    assert decode_access_token(CONFIG, token, "shop") == claims
    assert "role" not in jwt.decode(token, options={"verify_signature": False})  # rollar tokenda emas


def test_access_token_rejected_for_other_panel_expired_or_forged() -> None:
    token, _ = issue_access_token(CONFIG, _claims(), datetime.now(UTC))
    with pytest.raises(UnauthenticatedError):
        decode_access_token(CONFIG, token, "platform")
    old, _ = issue_access_token(CONFIG, _claims(), datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(UnauthenticatedError):
        decode_access_token(CONFIG, old, "shop")
    forged, _ = issue_access_token(
        AuthConfig(jwt_secret="boshqa-kalit-" + "y" * 32), _claims(), datetime.now(UTC)
    )
    with pytest.raises(UnauthenticatedError):
        decode_access_token(CONFIG, forged, "shop")


def test_refresh_token_stores_only_hash() -> None:
    session_id = uuid4()
    token, token_hash = new_refresh_token(session_id)
    parsed_id, parsed_hash = parse_refresh_token(token)
    assert (parsed_id, parsed_hash) == (session_id, token_hash)
    assert token_hash == hash_token(token.split(".", 1)[1]) and token_hash not in token
    with pytest.raises(UnauthenticatedError):
        parse_refresh_token("not-a-uuid.secret")


def test_permission_registry_merges_module_grants() -> None:
    registry = PermissionRegistry(
        [{"OWNER": frozenset({"a.b.c"})}, {"OWNER": frozenset({"d.e.f"}), "SALES": frozenset()}]
    )
    assert registry.for_role("OWNER") == {"a.b.c", "d.e.f"}
    assert registry.for_role("UNKNOWN") == frozenset()


def test_real_manifests_give_owner_everything_manager_less() -> None:
    from app.main import discover_manifests

    registry = PermissionRegistry.from_manifests(discover_manifests())
    owner, manager, sales = (registry.for_role(r) for r in ("OWNER", "MANAGER", "SALES"))
    assert manager < owner and "staff.member.invite" in owner and "staff.member.invite" not in manager
    assert "shops.settings.view" not in sales
