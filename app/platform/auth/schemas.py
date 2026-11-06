"""Auth API kontraktlari (11 §9.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=9, max_length=20)
    password: str = Field(min_length=1, max_length=128)
    # Qaysi panelga kirilyapti. Odamda bu panelga kirish huquqi bo'lmasa — oddiy "noto'g'ri login"
    audience: Literal["shop", "platform"]


class RefreshIn(BaseModel):
    """Har panelning o'z refresh cookie'si bor — bitta brauzerda ikkala panel bir-biriga xalaqit bermaydi."""

    model_config = ConfigDict(extra="forbid")

    audience: Literal["shop", "platform"]


class TokenOut(BaseModel):
    """Access token frontend XOTIRASIDA saqlanadi (localStorage — taqiq). Refresh token — httpOnly cookie."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — parol emas, OAuth token turi
    expires_in: int
    audience: Literal["shop", "platform"]


class SetPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)


class ResetConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class MeShop(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str


class MeOut(BaseModel):
    """Frontend sahifa va tugmalarni shunga qarab ko'rsatadi; server baribir har so'rovda tekshiradi."""

    principal_id: UUID
    full_name: str
    phone: str
    locale: str
    audience: Literal["shop", "platform"]
    role: str
    permissions: list[str]
    shop: MeShop | None
    branch_ids: list[UUID] | None
    membership_id: UUID | None = (
        None  # shop panelida — joriy a'zolik (vazifa "menga" filtri); platformada yo'q
    )


class SessionOut(BaseModel):
    id: UUID
    user_agent: str | None
    created_at: datetime
    last_used_at: datetime | None
    current: bool


class SessionList(BaseModel):
    items: list[SessionOut]
