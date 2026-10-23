"""Xodimlar API kontraktlari (11 §9.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["OWNER", "MANAGER", "SALES", "WAREHOUSE"]
BranchScope = Literal["ALL", "SELECTED"]


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    principal_id: UUID
    full_name: str
    phone: str
    role: Role
    status: Literal["INVITED", "ACTIVE", "DISABLED"]
    branch_scope: BranchScope
    branch_ids: list[UUID]
    activated_at: datetime | None
    version: int


class MemberList(BaseModel):
    items: list[MemberOut]


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=9, max_length=20)
    full_name: str = Field(min_length=2, max_length=120)
    role: Role
    branch_scope: BranchScope = "ALL"
    branch_ids: list[UUID] = Field(default_factory=list, max_length=50)


class LinkOut(BaseModel):
    """Bir martalik havola — ega uni xodimga o'zi yuboradi (DEC-131). Faqat bir marta ko'rsatiladi."""

    url: str
    expires_at: datetime


class InviteOut(BaseModel):
    member: MemberOut
    invite: LinkOut


class AccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    branch_scope: BranchScope = "ALL"
    branch_ids: list[UUID] = Field(default_factory=list, max_length=50)


class DisableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)
