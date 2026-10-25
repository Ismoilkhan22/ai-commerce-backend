"""Platforma paneli kontraktlari: bosh sahifa, shoplar, shop kartochkasi, jurnal (business/15, 11 §9.10).

Platforma shopning savdo ma'lumotini ko'rmaydi — faqat holat, sanoq va jurnal (10 §9).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.platform.shops.schemas import Locale, ShopOut, ShopStatus
from app.platform.staff.schemas import BranchScope, Role

MemberStatus = Literal["INVITED", "ACTIVE", "DISABLED"]
InviteState = Literal["expired", "expiring"]
ShopSort = Literal["created_desc", "activated_desc", "name"]


# ------------------------------------------------------------------ bosh sahifa


class ReviewQueueItem(BaseModel):
    shop_id: UUID
    name: str
    slug: str
    submitted_at: datetime | None
    waiting_days: int
    owner_name: str | None
    branch_count: int
    staff_count: int


class PendingOwnerItem(BaseModel):
    """Ega taklifni hali qabul qilmagan shop: havola eskirgan yoki eskirishiga oz qolgan."""

    shop_id: UUID
    name: str
    slug: str
    status: ShopStatus
    membership_id: UUID
    owner_name: str
    invite_expires_at: datetime
    invite_state: InviteState


class PilotItem(BaseModel):
    shop_id: UUID
    name: str
    slug: str
    activated_at: datetime
    day: int
    days_left: int
    ending_soon: bool


class ActivityItem(BaseModel):
    """Jurnal qatori. Qiymatlar ko'rsatilmaydi — faqat qaysi maydonlar o'zgargani."""

    id: UUID
    occurred_at: datetime
    action: str
    actor_type: str
    actor_id: UUID | None
    actor_name: str | None
    shop_id: UUID | None
    shop_name: str | None
    entity_type: str
    reason: str | None
    changed_fields: list[str]


class ActivityList(BaseModel):
    items: list[ActivityItem]
    total: int


class PlatformDashboard(BaseModel):
    counts_by_status: dict[ShopStatus, int]
    review_queue: list[ReviewQueueItem]
    pending_owners: list[PendingOwnerItem]
    pilots: list[PilotItem]
    new_shops_7d: int
    new_shops_30d: int
    recent_activity: list[ActivityItem]


# ------------------------------------------------------------------ shoplar ro'yxati


class ShopListItem(ShopOut):
    owner_name: str | None
    owner_status: MemberStatus | None
    staff_count: int
    branch_count: int
    last_activity_at: datetime | None


class ShopList(BaseModel):
    items: list[ShopListItem]
    total: int


class PlatformShopUpdate(BaseModel):
    """Platforma shop ma'lumotini tuzatadi. Slug o'zgarmaydi (sayt manzili), sabab majburiy (15 §3)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    legal_name: str | None = Field(default=None, max_length=200)
    tin: str = Field(pattern=r"^[0-9]{9}$")
    default_locale: Locale = "uz"
    reason: str = Field(default="", max_length=500)


# ------------------------------------------------------------------ shop kartochkasi


class ShopMemberOut(BaseModel):
    membership_id: UUID
    full_name: str
    phone: str
    role: Role
    status: MemberStatus
    branch_scope: BranchScope
    last_login_at: datetime | None
    activated_at: datetime | None


class ShopMemberList(BaseModel):
    items: list[ShopMemberOut]


class TransitionOut(BaseModel):
    id: UUID
    command: str
    from_status: str
    to_status: str
    actor_type: str
    actor_name: str | None
    reason: str | None
    forced: bool
    occurred_at: datetime


class TransitionList(BaseModel):
    items: list[TransitionOut]


# ------------------------------------------------------------------ ichki izohlar (15 §3)


class ShopNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=2000)


class ShopNoteOut(BaseModel):
    """Platformaning ichki izohi — shop ko'rmaydi. Faqat qo'shiladi."""

    id: UUID
    body: str
    author_name: str | None
    created_at: datetime


class ShopNoteList(BaseModel):
    items: list[ShopNoteOut]
