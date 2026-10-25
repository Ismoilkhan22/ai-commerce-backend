"""Platforma jamoasi API kontraktlari (business/15 §5, 11 §9.10)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.platform.staff.schemas import LinkOut

PlatformRole = Literal["PLATFORM_ADMIN", "PLATFORM_SUPPORT", "SPEC_EDITOR"]
PlatformStaffStatus = Literal["INVITED", "ACTIVE", "DISABLED"]


class PlatformStaffOut(BaseModel):
    id: UUID
    principal_id: UUID
    full_name: str
    phone: str
    role: PlatformRole
    status: PlatformStaffStatus
    last_login_at: datetime | None
    created_at: datetime
    invited_by_name: str | None
    version: int


class PlatformStaffList(BaseModel):
    items: list[PlatformStaffOut]


class PlatformInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=9, max_length=20)
    full_name: str = Field(min_length=2, max_length=120)
    role: PlatformRole


class PlatformInviteOut(BaseModel):
    member: PlatformStaffOut
    invite: LinkOut


class PlatformRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: PlatformRole
