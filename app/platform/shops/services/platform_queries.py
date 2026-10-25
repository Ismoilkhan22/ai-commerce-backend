"""Platforma paneli uchun o'qish ko'rinishlari: bosh sahifa, shoplar, kartochka, jurnal (business/15).

Platforma shopning savdo ma'lumotini ko'rmaydi — faqat holat, sanoq va jurnal (10 §9). Jurnalda
o'zgargan maydonlar NOMI ko'rsatiladi, qiymati emas.

`platform.memberships` da FORCE RLS: bitta so'rov faqat bitta shop a'zoliklarini ko'radi. Shuning uchun
xodimlar sanog'i har shop uchun alohida kontekstda olinadi — pilot hajmida (sahifada ≤100 shop) yetarli;
keyin reporting proyeksiyasi bilan almashtiriladi.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models.orm import AuditEntry
from app.platform.shops.models.orm import Branch, Shop, ShopNote
from app.platform.shops.platform_schemas import (
    ActivityItem,
    ActivityList,
    PendingOwnerItem,
    PilotItem,
    PlatformDashboard,
    ReviewQueueItem,
    ShopList,
    ShopListItem,
    ShopMemberList,
    ShopMemberOut,
    ShopNoteList,
    ShopNoteOut,
    ShopSort,
    TransitionList,
    TransitionOut,
)
from app.platform.shops.schemas import BranchList, BranchOut, ShopOut
from app.platform.shops.state_machine import ENTITY as SHOP
from app.platform.staff.models.orm import Invitation, Membership, PlatformStaff, Principal
from app.platform.use.models.orm import TransitionLog
from app.shared.clock import utcnow
from app.shared.db.session import set_identity_context
from app.shared.errors.base import NotFoundError, ValidationError
from app.shared.phone import normalize_phone

PILOT_DAYS = 30  # DEC-119: pilot faollashtirilgan kundan 30 kun
PILOT_ENDING_SOON_DAYS = 7
INVITE_EXPIRING_WITHIN = timedelta(hours=24)
RECENT_ACTIVITY_LIMIT = 10
STATUSES = ("DRAFT", "PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "CLOSED")
_ROLE_ORDER = {"OWNER": 0, "MANAGER": 1, "SALES": 2, "WAREHOUSE": 3}
_PHONE_LIKE = re.compile(r"[\d\s+()\-]+")


@dataclass(frozen=True)
class _MemberStats:
    owner_name: str | None = None
    owner_status: str | None = None
    staff_count: int = 0
    last_activity_at: datetime | None = None


def _changed_fields(diff: Any) -> list[str]:
    """Diff'dan faqat maydon nomlari: {"changed": [...]} yoki {"name": {"old", "new"}} ko'rinishlari."""
    if not isinstance(diff, dict):
        return []
    if set(diff) == {"changed"} and isinstance(diff["changed"], list):
        return sorted(str(name) for name in diff["changed"])
    return sorted(str(key) for key in diff)


class PlatformQueryService:
    # ---------------------------------------------------------------- bosh sahifa
    async def dashboard(self, db: AsyncSession) -> PlatformDashboard:
        now = utcnow()
        counts = dict.fromkeys(STATUSES, 0)
        for status, count in (
            await db.execute(select(Shop.status, func.count()).group_by(Shop.status))
        ).all():
            counts[status] = count
        new_7d = await db.scalar(
            select(func.count()).select_from(Shop).where(Shop.created_at >= now - timedelta(days=7))
        )
        new_30d = await db.scalar(
            select(func.count()).select_from(Shop).where(Shop.created_at >= now - timedelta(days=30))
        )
        recent = (
            (
                await db.execute(
                    select(AuditEntry)
                    .where(AuditEntry.actor_type == "PLATFORM", AuditEntry.action.not_like("auth.%"))
                    .order_by(AuditEntry.occurred_at.desc())
                    .limit(RECENT_ACTIVITY_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return PlatformDashboard(
            counts_by_status=counts,
            review_queue=await self._review_queue(db, now),
            pending_owners=await self._pending_owners(db, now),
            pilots=await self._pilots(db, now),
            new_shops_7d=new_7d or 0,
            new_shops_30d=new_30d or 0,
            recent_activity=await self._activity(db, recent),
        )

    async def _review_queue(self, db: AsyncSession, now: datetime) -> list[ReviewQueueItem]:
        shops = (await db.execute(select(Shop).where(Shop.status == "PENDING_VERIFICATION"))).scalars().all()
        if not shops:
            return []
        ids = [s.id for s in shops]
        submitted = dict(
            (
                await db.execute(
                    select(TransitionLog.entity_id, func.max(TransitionLog.occurred_at))
                    .where(
                        TransitionLog.entity_type == SHOP,
                        TransitionLog.command == "SUBMIT_FOR_VERIFICATION",
                        TransitionLog.entity_id.in_(ids),
                    )
                    .group_by(TransitionLog.entity_id)
                )
            ).all()
        )
        stats = await self._member_stats(db, ids)
        branches = await self._branch_counts(db, ids)
        items = []
        for shop in shops:
            since = submitted.get(shop.id) or shop.created_at
            items.append(
                ReviewQueueItem(
                    shop_id=shop.id,
                    name=shop.name,
                    slug=shop.slug,
                    submitted_at=submitted.get(shop.id),
                    waiting_days=max(0, (now - since).days),
                    owner_name=stats[shop.id].owner_name,
                    branch_count=branches.get(shop.id, 0),
                    staff_count=stats[shop.id].staff_count,
                )
            )
        return sorted(items, key=lambda i: i.submitted_at or now)  # eng uzoq kutayotgan birinchi

    async def _pending_owners(self, db: AsyncSession, now: datetime) -> list[PendingOwnerItem]:
        """Faqat taklif muddati o'tgan yoki tugashiga oz qolgan egalar."""
        # Ochiq taklif havolalari (invitations'da RLS yo'q) → har biri egami va hali INVITED mi
        open_invites = (
            await db.execute(
                select(Invitation.shop_id, Invitation.membership_id, func.max(Invitation.expires_at))
                .where(
                    Invitation.purpose == "INVITE",
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                )
                .group_by(Invitation.shop_id, Invitation.membership_id)
            )
        ).all()
        if not open_invites:
            return []
        shops = {
            s.id: s
            for s in (
                await db.execute(
                    select(Shop).where(Shop.id.in_({i[0] for i in open_invites}), Shop.status != "CLOSED")
                )
            ).scalars()
        }
        items = []
        for shop_id, membership_id, expires_at in open_invites:
            shop = shops.get(shop_id)
            if shop is None:
                continue
            await set_identity_context(db, shop_id=shop_id)
            row = (
                await db.execute(
                    select(Membership, Principal)
                    .join(Principal, Principal.id == Membership.principal_id)
                    .where(Membership.id == membership_id, Membership.shop_id == shop_id)
                )
            ).one_or_none()
            if row is None or row[0].role != "OWNER" or row[0].status != "INVITED":
                continue
            if expires_at - now >= INVITE_EXPIRING_WITHIN:
                continue  # havola hali amalda — aralashish shart emas (business/15, A bosqich)
            state = "expired" if expires_at <= now else "expiring"
            items.append(
                PendingOwnerItem(
                    shop_id=shop.id,
                    name=shop.name,
                    slug=shop.slug,
                    status=shop.status,
                    membership_id=membership_id,
                    owner_name=row[1].full_name,
                    invite_expires_at=expires_at,
                    invite_state=state,
                )
            )
        return sorted(items, key=lambda i: i.invite_expires_at)  # eskirgani birinchi

    async def _pilots(self, db: AsyncSession, now: datetime) -> list[PilotItem]:
        shops = (
            (await db.execute(select(Shop).where(Shop.status == "ACTIVE", Shop.activated_at.is_not(None))))
            .scalars()
            .all()
        )
        items = []
        for shop in shops:
            assert shop.activated_at is not None
            day = (now - shop.activated_at).days + 1
            days_left = max(0, PILOT_DAYS - day)
            items.append(
                PilotItem(
                    shop_id=shop.id,
                    name=shop.name,
                    slug=shop.slug,
                    activated_at=shop.activated_at,
                    day=day,
                    days_left=days_left,
                    ending_soon=days_left <= PILOT_ENDING_SOON_DAYS,
                )
            )
        return sorted(items, key=lambda i: i.days_left)

    # ---------------------------------------------------------------- shoplar ro'yxati
    async def list_shops(
        self,
        db: AsyncSession,
        *,
        q: str | None,
        statuses: Sequence[str],
        sort: ShopSort,
        limit: int,
        offset: int,
    ) -> ShopList:
        conditions: list[ColumnElement[bool]] = []
        if q and q.strip():
            text = q.strip()
            match = or_(
                func.lower(Shop.name).contains(text.lower(), autoescape=True),
                func.lower(Shop.slug).contains(text.lower(), autoescape=True),
                Shop.tin.contains(text, autoescape=True),
            )
            owner_shops = await self._shops_by_owner_phone(db, text)
            conditions.append(or_(match, Shop.id.in_(owner_shops)) if owner_shops else match)
        if statuses:
            conditions.append(Shop.status.in_(statuses))
        order = {
            "created_desc": (Shop.created_at.desc(),),
            "activated_desc": (Shop.activated_at.desc().nulls_last(), Shop.created_at.desc()),
            "name": (func.lower(Shop.name).asc(),),
        }[sort]
        total = await db.scalar(select(func.count()).select_from(Shop).where(*conditions)) or 0
        shops = (
            (await db.execute(select(Shop).where(*conditions).order_by(*order).limit(limit).offset(offset)))
            .scalars()
            .all()
        )
        ids = [s.id for s in shops]
        stats = await self._member_stats(db, ids)
        branches = await self._branch_counts(db, ids)
        items = [
            ShopListItem(
                **ShopOut.model_validate(shop).model_dump(),
                owner_name=stats[shop.id].owner_name,
                owner_status=stats[shop.id].owner_status,
                staff_count=stats[shop.id].staff_count,
                branch_count=branches.get(shop.id, 0),
                last_activity_at=stats[shop.id].last_activity_at,
            )
            for shop in shops
        ]
        return ShopList(items=items, total=total)

    async def _shops_by_owner_phone(self, db: AsyncSession, text: str) -> list[UUID]:
        if not _PHONE_LIKE.fullmatch(text) or len(re.sub(r"\D", "", text)) < 9:
            return []
        try:
            phone = normalize_phone(text)
        except ValidationError:
            return []
        principal_id = await db.scalar(select(Principal.id).where(Principal.phone == phone))
        if principal_id is None:
            return []
        await set_identity_context(db, principal_id=principal_id)  # memberships RLS: shu odam qatorlari
        return list(
            (
                await db.execute(
                    select(Membership.shop_id).where(
                        Membership.principal_id == principal_id, Membership.role == "OWNER"
                    )
                )
            ).scalars()
        )

    # ---------------------------------------------------------------- shop kartochkasi
    async def members(self, db: AsyncSession, shop_id: UUID) -> ShopMemberList:
        await self._ensure_shop(db, shop_id)
        await set_identity_context(db, shop_id=shop_id)
        rows = (
            await db.execute(
                select(Membership, Principal)
                .join(Principal, Principal.id == Membership.principal_id)
                .where(Membership.shop_id == shop_id)
                .order_by(Membership.created_at)
            )
        ).all()
        items = [
            ShopMemberOut(
                membership_id=m.id,
                full_name=p.full_name,
                phone=p.phone,
                role=m.role,
                status=m.status,
                branch_scope=m.branch_scope,
                last_login_at=p.last_login_at,
                activated_at=m.activated_at,
            )
            for m, p in rows
        ]
        return ShopMemberList(items=sorted(items, key=lambda i: _ROLE_ORDER.get(i.role, 9)))

    async def branches(self, db: AsyncSession, shop_id: UUID) -> BranchList:
        await self._ensure_shop(db, shop_id)
        rows = (
            await db.execute(select(Branch).where(Branch.shop_id == shop_id).order_by(Branch.created_at))
        ).scalars()
        return BranchList(items=[BranchOut.model_validate(b) for b in rows])

    async def history(self, db: AsyncSession, shop_id: UUID) -> TransitionList:
        """Shop holati tarixi (FSM-01): kim, qachon, qaysi holatdan qaysiga va nega."""
        await self._ensure_shop(db, shop_id)
        rows = (
            (
                await db.execute(
                    select(TransitionLog)
                    .where(TransitionLog.entity_type == SHOP, TransitionLog.entity_id == shop_id)
                    .order_by(TransitionLog.occurred_at.desc())
                )
            )
            .scalars()
            .all()
        )
        names = await self._principal_names(db, (r.actor_id for r in rows))
        return TransitionList(
            items=[
                TransitionOut(
                    id=r.id,
                    command=r.command,
                    from_status=r.from_status,
                    to_status=r.to_status,
                    actor_type=r.actor_type,
                    actor_name=names.get(r.actor_id) if r.actor_id else None,
                    reason=r.reason,
                    forced=r.forced,
                    occurred_at=r.occurred_at,
                )
                for r in rows
            ]
        )

    async def shop_audit(self, db: AsyncSession, shop_id: UUID, limit: int, offset: int) -> ActivityList:
        await self._ensure_shop(db, shop_id)
        # Eski platforma yozuvlarida shop_id bo'sh bo'lishi mumkin — shop obyektining o'zi bo'yicha ham
        condition = or_(
            AuditEntry.shop_id == shop_id, and_(AuditEntry.shop_id.is_(None), AuditEntry.entity_id == shop_id)
        )
        return await self._activity_page(db, [condition], limit, offset)

    # ---------------------------------------------------------------- platforma jurnali
    async def platform_audit(
        self,
        db: AsyncSession,
        *,
        shop_id: UUID | None,
        actor_id: UUID | None,
        action: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> ActivityList:
        conditions: list[ColumnElement[bool]] = [AuditEntry.actor_type == "PLATFORM"]
        if shop_id:
            conditions.append(AuditEntry.shop_id == shop_id)
        if actor_id:
            conditions.append(AuditEntry.actor_id == actor_id)
        if action:
            conditions.append(AuditEntry.action.startswith(action, autoescape=True))
        if date_from:
            conditions.append(AuditEntry.occurred_at >= date_from)
        if date_to:
            conditions.append(AuditEntry.occurred_at < date_to)
        return await self._activity_page(db, conditions, limit, offset)

    # ---------------------------------------------------------------- yordamchilar
    async def _activity_page(
        self, db: AsyncSession, conditions: list[ColumnElement[bool]], limit: int, offset: int
    ) -> ActivityList:
        total = await db.scalar(select(func.count()).select_from(AuditEntry).where(*conditions)) or 0
        rows = (
            (
                await db.execute(
                    select(AuditEntry)
                    .where(*conditions)
                    .order_by(AuditEntry.occurred_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return ActivityList(items=await self._activity(db, rows), total=total)

    async def _activity(self, db: AsyncSession, rows: Sequence[AuditEntry]) -> list[ActivityItem]:
        names = await self._principal_names(db, (r.actor_id for r in rows))
        shop_ids = {r.shop_id for r in rows if r.shop_id}
        shop_names = (
            dict((await db.execute(select(Shop.id, Shop.name).where(Shop.id.in_(shop_ids)))).all())
            if shop_ids
            else {}
        )
        return [
            ActivityItem(
                id=r.id,
                occurred_at=r.occurred_at,
                action=r.action,
                actor_type=r.actor_type,
                actor_id=r.actor_id,
                actor_name=names.get(r.actor_id) if r.actor_id else None,
                shop_id=r.shop_id,
                shop_name=shop_names.get(r.shop_id) if r.shop_id else None,
                entity_type=r.entity_type,
                reason=r.reason,
                changed_fields=_changed_fields(r.diff),
            )
            for r in rows
        ]

    async def _principal_names(self, db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
        wanted = {i for i in ids if i}
        if not wanted:
            return {}
        rows = await db.execute(select(Principal.id, Principal.full_name).where(Principal.id.in_(wanted)))
        return dict(rows.all())

    async def _member_stats(self, db: AsyncSession, shop_ids: Sequence[UUID]) -> dict[UUID, _MemberStats]:
        stats: dict[UUID, _MemberStats] = {}
        for shop_id in shop_ids:
            await set_identity_context(db, shop_id=shop_id)
            rows = (
                await db.execute(
                    select(Membership.role, Membership.status, Principal.full_name, Principal.last_login_at)
                    .join(Principal, Principal.id == Membership.principal_id)
                    .where(Membership.shop_id == shop_id)
                    .order_by(Membership.created_at)
                )
            ).all()
            owner = next((r for r in rows if r[0] == "OWNER" and r[1] != "DISABLED"), None)
            logins = [r[3] for r in rows if r[3] is not None]
            stats[shop_id] = _MemberStats(
                owner_name=owner[2] if owner else None,
                owner_status=owner[1] if owner else None,
                staff_count=sum(1 for r in rows if r[1] != "DISABLED"),
                last_activity_at=max(logins, default=None),
            )
        return stats

    async def _branch_counts(self, db: AsyncSession, shop_ids: Sequence[UUID]) -> dict[UUID, int]:
        if not shop_ids:
            return {}
        rows = await db.execute(
            select(Branch.shop_id, func.count())
            .where(Branch.shop_id.in_(shop_ids), Branch.status == "ACTIVE")
            .group_by(Branch.shop_id)
        )
        return dict(rows.all())

    async def notes(self, db: AsyncSession, shop_id: UUID) -> ShopNoteList:
        """Ichki izohlar (15 §3), yangisi birinchi."""
        await self._ensure_shop(db, shop_id)
        rows = await db.execute(
            select(ShopNote, Principal.full_name)
            .join(PlatformStaff, PlatformStaff.id == ShopNote.author_id)
            .join(Principal, Principal.id == PlatformStaff.principal_id)
            .where(ShopNote.shop_id == shop_id)
            .order_by(ShopNote.created_at.desc(), ShopNote.id.desc())
        )
        return ShopNoteList(
            items=[
                ShopNoteOut(id=note.id, body=note.body, author_name=name, created_at=note.created_at)
                for note, name in rows
            ]
        )

    async def _ensure_shop(self, db: AsyncSession, shop_id: UUID) -> None:
        if await db.get(Shop, shop_id) is None:
            raise NotFoundError("Shop not found")
