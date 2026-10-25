"""Toifalar — platforma ma'lumotnomasi (DEC-133): platforma yuritadi, shop faqat tanlaydi."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.products.models.orm import Category
from app.domains.catalog.products.schemas import CategoryIn, CategoryList, CategoryOut, CategoryUpdate
from app.platform.audit.services.audit_service import AuditService
from app.shared.errors.base import NotFoundError, ValidationError
from app.shared.types.actor import ActorContext

ENTITY = "catalog.category"


def _field_error(field: str, code: str, message: str) -> ValidationError:
    return ValidationError(message, fields=[{"field": field, "code": code, "params": {}}])


class CategoryService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def all(self, db: AsyncSession) -> dict[str, Category]:
        rows = await db.execute(select(Category).order_by(Category.position, Category.code))
        return {c.code: c for c in rows.scalars()}

    async def listing(self, db: AsyncSession) -> CategoryList:
        return CategoryList(items=[CategoryOut.model_validate(c) for c in (await self.all(db)).values()])

    async def get(self, db: AsyncSession, code: str) -> CategoryOut:
        category = await db.get(Category, code)
        if category is None:
            raise NotFoundError("Category not found")
        return CategoryOut.model_validate(category)

    async def usable(self, db: AsyncSession, code: str) -> Category:
        """Yangi mahsulot yoki toifa almashtirish uchun: mavjud va faol bo'lishi shart."""
        category = await db.get(Category, code)
        if category is None or not category.is_active:
            raise _field_error("category_code", "invalid_choice", "Unknown or inactive category")
        return category

    async def create(self, db: AsyncSession, actor: ActorContext, data: CategoryIn) -> CategoryOut:
        if await db.get(Category, data.code) is not None:
            raise _field_error("code", "not_unique", "Category code already used")
        if data.parent_code is not None:
            await self._parent(db, data.parent_code, data.code)
        category = Category(**data.model_dump())
        db.add(category)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise _field_error("code", "not_unique", "Category code already used") from exc
        await db.refresh(category)
        await self.audit.record(
            db,
            action="catalog.category.created",
            entity_type=ENTITY,
            entity_id=None,
            actor=actor,
            diff={"code": {"new": category.code}},
        )
        return CategoryOut.model_validate(category)

    async def update(
        self, db: AsyncSession, actor: ActorContext, code: str, data: CategoryUpdate
    ) -> CategoryOut:
        wanted = data.model_dump(exclude_unset=True)
        # Toifa va yangi ota toifa bir xil tartibda (kod bo'yicha) qulflanadi: "A → B" va "B → A" bir
        # vaqtda kelsa, biri ikkinchisini kutadi va keyin aylanani ko'radi — deadlock bo'lmaydi (12 §3)
        codes = sorted({code, wanted.get("parent_code") or code})
        locked = await db.execute(
            select(Category).where(Category.code.in_(codes)).order_by(Category.code).with_for_update()
        )
        category = next((c for c in locked.scalars() if c.code == code), None)
        if category is None:
            raise NotFoundError("Category not found")
        for name in ("name_uz", "name_ru", "name_en", "position", "is_active"):
            if name in wanted and wanted[name] is None:
                raise _field_error(name, "required", "Field cannot be empty")
        if wanted.get("parent_code") is not None:
            await self._parent(db, wanted["parent_code"], code)
        changed = {k: v for k, v in wanted.items() if getattr(category, k) != v}
        for key, value in changed.items():
            setattr(category, key, value)
        await db.flush()
        await db.refresh(category)
        if changed:
            await self.audit.record(
                db,
                action="catalog.category.updated",
                entity_type=ENTITY,
                entity_id=None,
                actor=actor,
                diff={"code": {"new": code}, "changed": sorted(changed)},
            )
        return CategoryOut.model_validate(category)

    async def _parent(self, db: AsyncSession, parent_code: str, code: str) -> None:
        """Ota toifa mavjud va aylana yo'q (A → B → A bo'lmasin)."""
        categories = await self.all(db)
        if parent_code not in categories:
            raise _field_error("parent_code", "invalid_choice", "Unknown parent category")
        cursor: str | None = parent_code
        while cursor is not None:
            if cursor == code:
                raise _field_error("parent_code", "invalid", "Category cannot be its own ancestor")
            cursor = categories[cursor].parent_code if cursor in categories else None
