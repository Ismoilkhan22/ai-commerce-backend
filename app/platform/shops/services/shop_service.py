"""Shop: profil, sozlamalar, filiallar (shop paneli) va platforma amallari (DEC-122, FSM-01)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.config import AuthConfig
from app.platform.shops.models.orm import Branch, Shop, ShopPolicy
from app.platform.shops.schemas import (
    BranchIn,
    BranchOut,
    PolicyOut,
    PolicyUpdate,
    ShopCreatedOut,
    ShopCreateIn,
    ShopOut,
    ShopProfileUpdate,
)
from app.platform.shops.state_machine import ENTITY as SHOP
from app.platform.staff.models.orm import Membership, Principal
from app.platform.staff.schemas import LinkOut
from app.platform.staff.services.links import issue_link
from app.platform.staff.services.staff_service import StaffService
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.db.session import set_identity_context
from app.shared.errors.base import BranchClosedError, NotFoundError, ValidationError
from app.shared.http import check_version
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext


def _not_unique(field: str) -> ValidationError:
    return ValidationError(
        f"{field} already used", fields=[{"field": field, "code": "not_unique", "params": {}}]
    )


class ShopService:
    def __init__(self, use: UseService, audit: AuditService, config: AuthConfig, staff: StaffService) -> None:
        self.use = use
        self.audit = audit
        self.config = config
        self.staff = staff

    # ------------------------------------------------------------- shop panel
    async def profile(self, db: AsyncSession, actor: ActorContext) -> ShopOut:
        return ShopOut.model_validate(await self._shop(db, actor.shop_id))

    async def update_profile(
        self, db: AsyncSession, actor: ActorContext, expected_version: int, data: ShopProfileUpdate
    ) -> ShopOut:
        shop = await self._shop(db, actor.shop_id, for_update=True)
        check_version(shop.version, expected_version)
        changed = {k: v for k, v in data.model_dump().items() if getattr(shop, k) != v}
        for key, value in changed.items():
            setattr(shop, key, value)
        await self._flush_unique(db, {"uq_shops_tin": "tin"})
        await self.audit.record(
            db,
            action="shops.profile.updated",
            entity_type=SHOP,
            entity_id=shop.id,
            actor=actor,
            entity_version=shop.version,
            diff={"changed": sorted(changed)},
        )
        return ShopOut.model_validate(shop)

    async def submit_for_verification(self, db: AsyncSession, actor: ActorContext) -> ShopOut:
        shop = await self._shop(db, actor.shop_id, for_update=True)
        return await self._transition(
            db, actor, shop, "PENDING_VERIFICATION", "SUBMIT_FOR_VERIFICATION", None
        )

    async def policies(self, db: AsyncSession, actor: ActorContext) -> PolicyOut:
        return PolicyOut.model_validate(await self._policy(db, actor.shop_id))

    async def update_policies(
        self, db: AsyncSession, actor: ActorContext, expected_version: int, data: PolicyUpdate
    ) -> PolicyOut:
        policy = await self._policy(db, actor.shop_id, for_update=True)
        check_version(policy.version, expected_version)
        changed = {k: v for k, v in data.model_dump().items() if getattr(policy, k) != v}
        for key, value in changed.items():
            setattr(policy, key, value)
        await db.flush()
        await self.audit.record(
            db,
            action="shops.policy.updated",
            entity_type="platform.shop_policy",
            entity_id=policy.shop_id,
            actor=actor,
            entity_version=policy.version,
            diff={key: {"new": value} for key, value in changed.items()},
        )
        return PolicyOut.model_validate(policy)

    async def branches(self, db: AsyncSession, actor: ActorContext) -> list[BranchOut]:
        query = select(Branch).where(Branch.shop_id == actor.shop_id).order_by(Branch.created_at)
        if actor.branch_ids is not None:  # filialga biriktirilgan xodim faqat o'z filiallarini ko'radi
            query = query.where(Branch.id.in_(actor.branch_ids))
        return [BranchOut.model_validate(b) for b in (await db.execute(query)).scalars()]

    async def create_branch(self, db: AsyncSession, actor: ActorContext, data: BranchIn) -> BranchOut:
        values = data.model_dump()
        if values["phone"]:
            values["phone"] = normalize_phone(values["phone"])
        branch = Branch(shop_id=actor.shop_id, **values)
        db.add(branch)
        await db.flush()
        await self.audit.record(
            db, action="shops.branch.created", entity_type="platform.branch", entity_id=branch.id, actor=actor
        )
        return BranchOut.model_validate(branch)

    async def update_branch(
        self, db: AsyncSession, actor: ActorContext, branch_id: UUID, expected_version: int, data: BranchIn
    ) -> BranchOut:
        branch = await self._branch(db, actor, branch_id)
        check_version(branch.version, expected_version)
        if branch.status == "CLOSED":
            raise BranchClosedError("Branch is closed", branch_id=branch.id)
        values = data.model_dump()
        if values["phone"]:
            values["phone"] = normalize_phone(values["phone"])
        changed = {k: v for k, v in values.items() if getattr(branch, k) != v}
        for key, value in changed.items():
            setattr(branch, key, value)
        await db.flush()
        await self.audit.record(
            db,
            action="shops.branch.updated",
            entity_type="platform.branch",
            entity_id=branch.id,
            actor=actor,
            entity_version=branch.version,
            diff={"changed": sorted(changed)},
        )
        return BranchOut.model_validate(branch)

    async def close_branch(self, db: AsyncSession, actor: ActorContext, branch_id: UUID) -> BranchOut:
        branch = await self._branch(db, actor, branch_id)
        if branch.status == "CLOSED":
            raise BranchClosedError("Branch is already closed", branch_id=branch.id)
        branch.status = "CLOSED"  # o'chirilmaydi — eski buyurtmalar unga bog'langan
        await db.flush()
        await self.audit.record(
            db, action="shops.branch.closed", entity_type="platform.branch", entity_id=branch.id, actor=actor
        )
        return BranchOut.model_validate(branch)

    # --------------------------------------------------------------- platform
    async def create_shop(self, db: AsyncSession, actor: ActorContext, data: ShopCreateIn) -> ShopCreatedOut:
        owner_phone = normalize_phone(data.owner_phone, field="owner_phone")
        if (await db.execute(select(Principal.id).where(Principal.phone == owner_phone))).first():
            raise _not_unique("owner_phone")  # hozircha bir odam — bitta shop (DEC-131)
        shop = Shop(
            slug=data.slug,
            name=data.name,
            legal_name=data.legal_name,
            tin=data.tin,
            default_locale=data.default_locale,
        )
        db.add(shop)
        await self._flush_unique(db, {"uq_shops_slug": "slug", "uq_shops_tin": "tin"})
        await set_identity_context(db, shop_id=shop.id)  # memberships RLS: yangi shop konteksti
        db.add(ShopPolicy(shop_id=shop.id))
        principal = Principal(
            phone=owner_phone, full_name=data.owner_full_name.strip(), locale=data.default_locale
        )
        db.add(principal)
        await db.flush()
        owner = Membership(shop_id=shop.id, principal_id=principal.id, role="OWNER")
        db.add(owner)
        await db.flush()
        url, expires_at = await issue_link(
            db,
            shop_id=shop.id,
            membership_id=owner.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.app_public_url,
        )
        await self.audit.record(
            db, action="shops.shop.created", entity_type=SHOP, entity_id=shop.id, actor=actor
        )
        await db.refresh(shop)
        return ShopCreatedOut(
            shop=ShopOut.model_validate(shop),
            owner_membership_id=owner.id,
            owner_invite=LinkOut(url=url, expires_at=expires_at),
        )

    async def list_shops(self, db: AsyncSession, limit: int) -> list[ShopOut]:
        rows = (await db.execute(select(Shop).order_by(Shop.created_at.desc()).limit(limit))).scalars()
        return [ShopOut.model_validate(s) for s in rows]

    async def get_shop(self, db: AsyncSession, shop_id: UUID) -> ShopOut:
        return ShopOut.model_validate(await self._shop(db, shop_id))

    async def platform_transition(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, command: str, reason: str | None
    ) -> ShopOut:
        target = {"ACTIVATE": "ACTIVE", "SUSPEND": "SUSPENDED", "REACTIVATE": "ACTIVE", "CLOSE": "CLOSED"}[
            command
        ]
        shop = await self._shop(db, shop_id, for_update=True)
        return await self._transition(db, actor, shop, target, command, reason)

    async def member_password_reset(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, membership_id: UUID
    ) -> LinkOut:
        """Egasi parolini unutsa — platforma admini tiklash havolasini beradi (faqat egalarga)."""
        await set_identity_context(db, shop_id=shop_id)
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.id == membership_id, Membership.shop_id == shop_id, Membership.role == "OWNER"
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            raise NotFoundError("Owner not found")
        return await self.staff.password_reset_link(db, actor, membership)

    async def owner_invite_link(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, membership_id: UUID
    ) -> LinkOut:
        """Ega taklifini qayta berish (shop yaratish takrorlanganda). Eski havola bekor bo'ladi."""
        await set_identity_context(db, shop_id=shop_id)
        owner = await db.get(Membership, membership_id)
        if owner is None or owner.shop_id != shop_id or owner.status != "INVITED":
            raise NotFoundError("Pending owner invitation not found")
        url, expires_at = await issue_link(
            db,
            shop_id=shop_id,
            membership_id=owner.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.app_public_url,
        )
        return LinkOut(url=url, expires_at=expires_at)

    # ---------------------------------------------------------------- helpers
    async def _transition(
        self, db: AsyncSession, actor: ActorContext, shop: Shop, target: str, command: str, reason: str | None
    ) -> ShopOut:
        rule = self.use.validate_transition(SHOP, shop.status, target, command, actor)
        shop.status = target
        if target == "ACTIVE" and shop.activated_at is None:
            shop.activated_at = utcnow()  # pilot 30 kuni shundan sanaladi (DEC-119)
        await db.flush()
        await self.use.log_transition(db, entity_id=shop.id, rule=rule, actor=actor, reason=reason)
        await self.audit.record(
            db,
            action=f"shops.shop.{command.lower()}",
            entity_type=SHOP,
            entity_id=shop.id,
            actor=actor,
            entity_version=shop.version,
            reason=reason,
            diff={"status": {"old": rule.from_status, "new": target}},
        )
        return ShopOut.model_validate(shop)

    async def _shop(self, db: AsyncSession, shop_id: UUID | None, for_update: bool = False) -> Shop:
        shop = await db.get(Shop, shop_id, with_for_update=for_update) if shop_id else None
        if shop is None:
            raise NotFoundError("Shop not found")
        return shop

    async def _policy(self, db: AsyncSession, shop_id: UUID | None, for_update: bool = False) -> ShopPolicy:
        policy = await db.get(ShopPolicy, shop_id, with_for_update=for_update) if shop_id else None
        if policy is None:
            raise NotFoundError("Shop policy not found")
        return policy

    async def _branch(self, db: AsyncSession, actor: ActorContext, branch_id: UUID) -> Branch:
        branch = (
            await db.execute(
                select(Branch)
                .where(Branch.id == branch_id, Branch.shop_id == actor.shop_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if branch is None:
            raise NotFoundError("Branch not found")
        return branch

    async def _flush_unique(self, db: AsyncSession, constraints: dict[str, str]) -> None:
        try:
            await db.flush()
        except IntegrityError as exc:
            for constraint, field in constraints.items():
                if constraint in str(exc.orig):
                    raise _not_unique(field) from exc
            raise
