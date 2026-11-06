"""Xaridor matnlari: shop o'zgartirgan matn va standart (DEC-139 1-qaror, 20 §5).

Tahrir — yangi versiya (eski versiya `is_active = false` bo'lib qoladi, tarix uchun); "standartga qaytarish" —
faol versiya o'chiriladi. Matnda majburiy o'zgaruvchi qolishi shart, noma'lum o'zgaruvchi — rad (TC-NOT-03).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.customer_templates import (
    CUSTOMER_TEMPLATE_VERSION,
    CUSTOMER_TEMPLATES,
    LOCALES,
    TemplateBodyError,
    check_body,
    default_body,
)
from app.platform.notifications.models.orm import ShopMessageTemplate
from app.platform.notifications.schemas import MessageTemplateList, MessageTemplateOut
from app.shared.errors.base import NotFoundError, ValidationError
from app.shared.types.actor import ActorContext

ENTITY = "platform.shop_message_template"


def _out(key: str, locale: str, row: ShopMessageTemplate | None) -> MessageTemplateOut:
    template = CUSTOMER_TEMPLATES[key]
    default = default_body(key, locale)
    return MessageTemplateOut(
        template_key=key,
        locale=locale,
        body=row.body if row else default,
        default_body=default,
        overridden=row is not None,
        version=row.version if row else None,
        required_variables=sorted(template.required),
        allowed_variables=sorted(template.allowed),
    )


def _known(key: str, locale: str) -> None:
    if key not in CUSTOMER_TEMPLATES or locale not in LOCALES:
        raise NotFoundError("Template not found")


class CustomerTemplateService:
    def __init__(self, audit: AuditService | None = None) -> None:
        self.audit = audit or AuditService()

    async def resolve(self, db: AsyncSession, shop_id: UUID, key: str, locale: str) -> tuple[str, str]:
        """(matn, versiya belgisi): shop matni (xaridor tilida) → standart (o'sha tilda) → standart (uz)."""
        lang = locale if locale in LOCALES else "uz"
        row = await self._active(db, shop_id, key, lang)
        if row is not None:
            return row.body, f"shop:{row.id}:v{row.version}"
        return default_body(key, lang), CUSTOMER_TEMPLATE_VERSION

    async def list(self, db: AsyncSession, actor: ActorContext) -> MessageTemplateList:
        assert actor.shop_id is not None
        rows = (
            (
                await db.execute(
                    select(ShopMessageTemplate).where(
                        ShopMessageTemplate.shop_id == actor.shop_id, ShopMessageTemplate.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        active = {(r.template_key, r.locale): r for r in rows}
        return MessageTemplateList(
            items=[
                _out(key, locale, active.get((key, locale)))
                for key in sorted(CUSTOMER_TEMPLATES)
                for locale in LOCALES
            ]
        )

    async def save(
        self, db: AsyncSession, actor: ActorContext, key: str, locale: str, body: str
    ) -> MessageTemplateOut:
        _known(key, locale)
        assert actor.shop_id is not None and actor.membership_id is not None
        try:
            check_body(key, body)
        except TemplateBodyError as exc:
            raise ValidationError(
                "Template variables are invalid",
                fields=[{"field": "body", "code": exc.code, "params": {"variables": exc.variables}}],
            ) from exc
        await self._lock(db, actor.shop_id, key, locale)
        version = int(
            await db.scalar(
                select(func.coalesce(func.max(ShopMessageTemplate.version), 0)).where(
                    ShopMessageTemplate.shop_id == actor.shop_id,
                    ShopMessageTemplate.template_key == key,
                    ShopMessageTemplate.locale == locale,
                )
            )
            or 0
        )
        await self._deactivate(db, actor.shop_id, key, locale)
        row = ShopMessageTemplate(
            shop_id=actor.shop_id,
            template_key=key,
            locale=locale,
            version=version + 1,
            body=body,
            is_active=True,
            created_by=actor.membership_id,
        )
        db.add(row)
        await db.flush()
        await self.audit.record(
            db,
            action="notifications.template.saved",
            entity_type=ENTITY,
            entity_id=row.id,
            actor=actor,
            diff={"template_key": {"new": key}, "locale": {"new": locale}, "version": {"new": row.version}},
        )
        return _out(key, locale, row)

    async def reset(self, db: AsyncSession, actor: ActorContext, key: str, locale: str) -> MessageTemplateOut:
        _known(key, locale)
        assert actor.shop_id is not None
        await self._lock(db, actor.shop_id, key, locale)
        await self._deactivate(db, actor.shop_id, key, locale)
        await self.audit.record(
            db,
            action="notifications.template.reset",
            entity_type=ENTITY,
            entity_id=actor.shop_id,
            actor=actor,
            diff={"template_key": {"new": key}, "locale": {"new": locale}},
        )
        return _out(key, locale, None)

    @staticmethod
    async def _lock(db: AsyncSession, shop_id: UUID, key: str, locale: str) -> None:
        """Bir vaqtda ikki tahrir bir xil versiya raqamini olmasin (unikal indeks oxirgi himoya)."""
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"tpl:{shop_id}:{key}:{locale}"))))

    @staticmethod
    async def _deactivate(db: AsyncSession, shop_id: UUID, key: str, locale: str) -> None:
        await db.execute(
            update(ShopMessageTemplate)
            .where(
                ShopMessageTemplate.shop_id == shop_id,
                ShopMessageTemplate.template_key == key,
                ShopMessageTemplate.locale == locale,
                ShopMessageTemplate.is_active.is_(True),
            )
            .values(is_active=False)
        )

    @staticmethod
    async def _active(db: AsyncSession, shop_id: UUID, key: str, locale: str) -> ShopMessageTemplate | None:
        return (
            await db.execute(
                select(ShopMessageTemplate).where(
                    ShopMessageTemplate.shop_id == shop_id,
                    ShopMessageTemplate.template_key == key,
                    ShopMessageTemplate.locale == locale,
                    ShopMessageTemplate.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
