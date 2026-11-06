"""Shop: profil, sozlamalar, filiallar (shop paneli) va platforma amallari (DEC-122, FSM-01)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID
from zoneinfo import available_timezones

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.config import AuthConfig
from app.platform.auth.models.orm import AuthSession
from app.platform.shops.models.orm import Branch, Shop, ShopNote, ShopPolicy
from app.platform.shops.platform_schemas import PlatformShopUpdate, ShopNoteIn, ShopNoteOut
from app.platform.shops.schemas import (
    BranchIn,
    BranchOption,
    BranchOut,
    PlatformShopOut,
    PolicyOut,
    PolicyUpdate,
    ShopCreatedOut,
    ShopCreateIn,
    ShopOut,
    ShopOwnerOut,
    ShopProfileUpdate,
)
from app.platform.shops.state_machine import ENTITY as SHOP
from app.platform.staff.models.orm import Membership, PlatformStaff, Principal
from app.platform.staff.schemas import LinkOut
from app.platform.staff.services.links import issue_link
from app.platform.staff.services.staff_service import StaffService
from app.platform.staff.state_machine import ENTITY as MEMBERSHIP
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.contracts.commerce import OrderQueryPort
from app.shared.db.session import set_identity_context
from app.shared.errors.base import (
    BranchClosedError,
    NotFoundError,
    ShopHasOpenOrdersError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext


def _not_unique(field: str) -> ValidationError:
    return ValidationError(
        f"{field} already used", fields=[{"field": field, "code": "not_unique", "params": {}}]
    )


def _field_error(field: str, code: str, message: str, **params: object) -> ValidationError:
    return ValidationError(message, fields=[{"field": field, "code": code, "params": params}])


def _on_shop(actor: ActorContext, shop_id: UUID) -> ActorContext:
    """Platforma shop ustida amal qilsa — o'tishlar jurnali va audit shu shopga bog'lanadi.
    Shunda shop kartochkasidagi tarixda platforma amallari ham ko'rinadi (business/15 §4)."""
    return replace(actor, shop_id=shop_id) if actor.shop_id is None else actor


# Slug sayt subdomeni ({slug}.platforma.uz) va shop panelidagi yo'l (/{slug}/...) bo'ladi
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "cdn",
        "dashboard",
        "help",
        "invite",
        "login",
        "logout",
        "mail",
        "platform",
        "reset-password",
        "shop",
        "static",
        "status",
        "support",
        "www",
    }
)


class ShopService:
    def __init__(
        self,
        use: UseService,
        audit: AuditService,
        config: AuthConfig,
        staff: StaffService,
        orders: OrderQueryPort,
    ) -> None:
        self.use = use
        self.audit = audit
        self.config = config
        self.staff = staff
        # Yopishdan oldin ochiq buyurtmalar tekshiruvi (TC-023)
        self.orders = orders

    # ------------------------------------------------------------- shop panel
    async def profile(self, db: AsyncSession, actor: ActorContext) -> ShopOut:
        return ShopOut.model_validate(await self._shop(db, actor.shop_id))

    async def update_profile(
        self, db: AsyncSession, actor: ActorContext, expected_version: int, data: ShopProfileUpdate
    ) -> ShopOut:
        shop = await self._shop(db, actor.shop_id, for_update=True)
        check_version(shop.version, expected_version)
        # PATCH: body'da yo'q maydon o'zgarmaydi (standart qiymatga qaytmaydi)
        wanted = data.model_dump(exclude_unset=True)
        if "timezone" in wanted and wanted["timezone"] not in available_timezones():
            raise _field_error("timezone", "invalid_choice", "Unknown timezone")
        changed = {k: v for k, v in wanted.items() if getattr(shop, k) != v}
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
        active_branches = await db.scalar(
            select(func.count()).where(Branch.shop_id == shop.id, Branch.status == "ACTIVE")
        )
        if not active_branches:  # tekshiruvga kamida bitta ishlayotgan filial bilan yuboriladi
            raise _field_error("branches", "required", "At least one active branch is required")
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
        if data.discount_limit_sales_pct > data.discount_limit_manager_pct:
            # Sotuvchi chegarasi menejernikidan oshmaydi — aks holda tasdiqlash zinapoyasi buziladi
            raise _field_error(
                "discount_limit_sales_pct",
                "max_value",
                "Sales limit exceeds manager limit",
                max=data.discount_limit_manager_pct,
            )
        wanted = data.model_dump(exclude_none=True)
        changed = {k: v for k, v in wanted.items() if getattr(policy, k) != v}
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

    async def branch_options(self, db: AsyncSession, actor: ActorContext) -> list[BranchOption]:
        """Har shop xodimi uchun (operator, omborchi ham): filial tanlash. Biriktirilgan xodim — faqat
        o'z filiallari."""
        query = select(Branch).where(Branch.shop_id == actor.shop_id).order_by(Branch.created_at)
        if actor.branch_ids is not None:
            query = query.where(Branch.id.in_(actor.branch_ids))
        return [BranchOption.model_validate(b) for b in (await db.execute(query)).scalars()]

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
        if data.slug in RESERVED_SLUGS:
            raise _not_unique("slug")  # panel yo'llari va subdomenlar bilan to'qnashmasin
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
            db,
            action="shops.shop.created",
            entity_type=SHOP,
            entity_id=shop.id,
            actor=_on_shop(actor, shop.id),
        )
        await db.refresh(shop)
        return ShopCreatedOut(
            shop=ShopOut.model_validate(shop),
            owner_membership_id=owner.id,
            owner_invite=LinkOut(url=url, expires_at=expires_at),
        )

    async def get_shop(self, db: AsyncSession, shop_id: UUID) -> PlatformShopOut:
        shop = await self._shop(db, shop_id)
        await set_identity_context(db, shop_id=shop_id)
        rows = await db.execute(
            select(Membership, Principal)
            .join(Principal, Principal.id == Membership.principal_id)
            .where(Membership.shop_id == shop_id, Membership.role == "OWNER")
            .order_by(Membership.created_at)
        )
        owners = [
            ShopOwnerOut(membership_id=m.id, full_name=p.full_name, phone=p.phone, status=m.status)
            for m, p in rows
        ]
        return PlatformShopOut(**ShopOut.model_validate(shop).model_dump(), owners=owners)

    async def platform_transition(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, command: str, reason: str | None
    ) -> ShopOut:
        target = {"ACTIVATE": "ACTIVE", "SUSPEND": "SUSPENDED", "REACTIVATE": "ACTIVE", "CLOSE": "CLOSED"}[
            command
        ]
        shop = await self._shop(db, shop_id, for_update=True)
        if target == "CLOSED":
            # Mavjud buyurtmalar oxiriga yetkaziladi (FSM-01, TC-023): ochiq buyurtmali shop yopilmaydi
            counts = await self.orders.open_order_counts(db, shop.id)
            if counts:
                raise ShopHasOpenOrdersError(
                    "Shop has open orders", open_orders=counts, total=sum(counts.values())
                )
        result = await self._transition(db, _on_shop(actor, shop.id), shop, target, command, reason)
        if target == "CLOSED":
            # Yopilgan shopda hech kim ishlamaydi: barcha sessiyalar darhol tugaydi.
            # SUSPENDED da sessiyalar qoladi — shop ichki ishini davom ettiradi (business/13)
            await set_identity_context(db, shop_id=shop.id)
            await db.execute(
                update(AuthSession)
                .where(AuthSession.shop_id == shop.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=utcnow(), revoked_reason="SHOP_CLOSED")
            )
        return result

    async def platform_update(
        self,
        db: AsyncSession,
        actor: ActorContext,
        shop_id: UUID,
        expected_version: int,
        data: PlatformShopUpdate,
    ) -> PlatformShopOut:
        """Platforma shop ma'lumotini tuzatadi: sabab majburiy, slug o'zgarmaydi (business/15 §3)."""
        reason = data.reason.strip()
        if not reason:
            raise _field_error("reason", "required", "Reason required")
        if len(reason) < 3:  # holat o'zgartirish sababi bilan bir xil qoida (ReasonIn)
            raise _field_error("reason", "min_length", "Reason too short", min=3)
        shop = await self._shop(db, shop_id, for_update=True)
        check_version(shop.version, expected_version)
        wanted = data.model_dump(exclude={"reason"}, exclude_unset=True)
        old = {key: getattr(shop, key) for key in wanted}
        changed = {key: value for key, value in wanted.items() if old[key] != value}
        if changed:
            for key, value in changed.items():
                setattr(shop, key, value)
            await self._flush_unique(db, {"uq_shops_tin": "tin"})
            # STIR qiymati audit'ga yozilmaydi (yakka tadbirkorda shaxsiy bo'lishi mumkin) — faqat "o'zgardi"
            diff: dict[str, Any] = {
                key: {"changed": True} if key == "tin" else {"old": old[key], "new": value}
                for key, value in changed.items()
            }
            await self.audit.record(
                db,
                action="shops.shop.updated",
                entity_type=SHOP,
                entity_id=shop.id,
                actor=_on_shop(actor, shop.id),
                entity_version=shop.version,
                reason=reason,
                diff=diff,
            )
        return await self.get_shop(db, shop.id)

    async def add_note(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, data: ShopNoteIn
    ) -> ShopNoteOut:
        """Ichki izoh faqat qo'shiladi. Matn auditga yozilmaydi (shaxsiy ma'lumot bo'lishi mumkin)."""
        await self._shop(db, shop_id)
        author = (
            await db.execute(
                select(PlatformStaff, Principal)
                .join(Principal, Principal.id == PlatformStaff.principal_id)
                .where(PlatformStaff.principal_id == actor.actor_id)
            )
        ).one_or_none()
        if author is None:
            raise NotFoundError("Platform team member not found")
        staff, principal = author
        note = ShopNote(shop_id=shop_id, author_id=staff.id, body=data.body)
        db.add(note)
        await db.flush()
        await db.refresh(note)
        await self.audit.record(
            db,
            action="platform.shop.note_added",
            entity_type="platform.shop_note",
            entity_id=note.id,
            actor=_on_shop(actor, shop_id),
        )
        return ShopNoteOut(
            id=note.id, body=note.body, author_name=principal.full_name, created_at=note.created_at
        )

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
        return await self.staff.password_reset_link(db, _on_shop(actor, shop_id), membership)

    async def owner_invite_link(
        self, db: AsyncSession, actor: ActorContext, shop_id: UUID, membership_id: UUID
    ) -> LinkOut:
        """Ega taklifini qayta berish: shop yaratish takrorlanganda yoki 72 soat o'tib ketganda.
        Eski havola bekor bo'ladi."""
        await set_identity_context(db, shop_id=shop_id)
        owner = await db.get(Membership, membership_id)
        if owner is None or owner.shop_id != shop_id or owner.role != "OWNER" or owner.status != "INVITED":
            raise NotFoundError("Pending owner invitation not found")
        url, expires_at = await issue_link(
            db,
            shop_id=shop_id,
            membership_id=owner.id,
            purpose="INVITE",
            ttl=self.config.invite_ttl,
            app_url=self.config.app_public_url,
        )
        await self.audit.record(
            db,
            action="shops.owner.invite_reissued",
            entity_type=MEMBERSHIP,
            entity_id=owner.id,
            actor=_on_shop(actor, shop_id),
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
