"""Integratsiya testlari uchun umumiy yordamchilar: HTTP orqali shop, ega, xodim yaratish.

`world` fixture'i — `conftest.py` da (hamma integratsiya testlari ishlatadi).
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.config.settings import Settings
from tests.integration.conftest import PgUrls

PASSWORD = "Kuchli-parol-2026"
ADMIN_PASSWORD = "Admin-parol-2026!"
SHOP = {"audience": "shop"}


def _phone() -> str:
    return "+99890" + "".join(secrets.choice("0123456789") for _ in range(7))


def _tin() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(9))


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": f"key-{uuid4()}"}


def _bearer(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


def _sql(url: str, query: str, *args: Any) -> list[asyncpg.Record]:
    async def run() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            return list(await conn.fetch(query, *args))
        finally:
            await conn.close()

    return asyncio.run(run())


@dataclass
class World:
    client: TestClient
    urls: PgUrls
    settings: Settings
    admin_token: str
    admin_phone: str

    def login(self, phone: str, password: str = PASSWORD) -> str:
        response = self.client.post(
            "/api/v1/auth/login", json={"phone": phone, "password": password, "audience": "shop"}
        )
        assert response.status_code == 200, response.text
        return str(response.json()["access_token"])

    def accept(self, invite_url: str, password: str = PASSWORD) -> str:
        token = invite_url.rsplit("/", 1)[1]
        response = self.client.post(f"/api/v1/auth/invites/{token}/accept", json={"password": password})
        assert response.status_code == 200, response.text
        return str(response.json()["access_token"])

    def create_shop(self) -> dict[str, Any]:
        """Platforma shop yaratadi → ega taklifni qabul qiladi. Ega tokeni bilan qaytadi."""
        owner_phone = _phone()
        response = self.client.post(
            "/api/v1/platform/shops",
            json={
                "slug": f"shop-{uuid4().hex[:8]}",
                "name": "TechPC",
                "tin": _tin(),
                "owner_phone": owner_phone,
                "owner_full_name": "Ali Valiyev",
            },
            headers=_bearer(self.admin_token, **_idem()),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        owner_token = self.accept(body["owner_invite"]["url"])
        return {
            "shop": body["shop"],
            "owner_phone": owner_phone,
            "owner_token": owner_token,
            "owner_membership_id": body["owner_membership_id"],
        }

    def invite(self, owner_token: str, role: str, **extra: Any) -> tuple[str, str, str]:
        phone = _phone()
        response = self.client.post(
            "/api/v1/shop/members/invites",
            json={"phone": phone, "full_name": "Vali Aliyev", "role": role, **extra},
            headers=_bearer(owner_token, **_idem()),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return phone, body["member"]["id"], self.accept(body["invite"]["url"])

    def branch(self, owner_token: str, name: str = "Chilonzor") -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/shop/branches",
            json={
                "name": name,
                "address": "Toshkent, Chilonzor 1",
                "working_hours": {"mon": [["10:00", "20:00"]]},
            },
            headers=_bearer(owner_token, **_idem()),
        )
        assert response.status_code == 201, response.text
        return dict(response.json())


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])
