"""storefront.sites, storefront.pages — db/storefront.dbml (DEC-135).

Sayt o'zi deyarli hech narsa saqlamaydi: mahsulot, narx, qoldiq va buyurtma — boshqa schemalarda.
Bu yerda faqat saytning o'ziga tegishli narsa: ko'rinishi, kontaktlari, holati, ma'lumot sahifalari.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

SITE_STATUSES = ("DRAFT", "LIVE", "PAUSED")
THEME_MODES = ("LIGHT", "DARK")
PAGE_KINDS = ("ABOUT", "DELIVERY_PAYMENT", "WARRANTY_RETURNS")
DEFAULT_ACCENT = "#7C3AED"


class Site(TimestampMixin, VersionMixin, Base):
    """Har shopga bitta yozuv; ega birinchi marta saqlaganda yaratiladi. Yozuv yo'q — sayt DRAFT."""

    __tablename__ = "sites"
    __table_args__ = (
        CheckConstraint(f"status IN {SITE_STATUSES}", name="status"),
        CheckConstraint(f"theme_mode IN {THEME_MODES}", name="theme_mode"),
        CheckConstraint("accent_color ~ '^#[0-9A-Fa-f]{6}$'", name="accent_color"),
        {"schema": "storefront"},
    )

    shop_id: Mapped[UUID] = mapped_column(primary_key=True)  # platform.shops.id — FK'siz (07 §6.3)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    logo_file_id: Mapped[UUID | None]  # platform.stored_files.id (SITE_LOGO, ochiq)
    accent_color: Mapped[str] = mapped_column(Text, server_default=DEFAULT_ACCENT)
    theme_mode: Mapped[str] = mapped_column(Text, server_default="LIGHT")
    tagline: Mapped[str | None] = mapped_column(Text)
    seo_description: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)  # E.164; LIVE qilishdan oldin majburiy
    contact_email: Mapped[str | None] = mapped_column(Text)
    telegram_username: Mapped[str | None] = mapped_column(Text)  # faqat username — havolani tizim yasaydi
    instagram_username: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[UUID | None]  # platform.memberships.id


class Page(IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Uchta tayyor sahifa (DEC-135); matn — Markdown, HTML qabul qilinmaydi (XSS)."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("shop_id", "id"),
        UniqueConstraint("shop_id", "kind"),  # har turdan bitta (matn bitta tilda — DEC-135)
        ForeignKeyConstraint(["shop_id"], ["storefront.sites.shop_id"], ondelete="RESTRICT"),
        CheckConstraint(f"kind IN {PAGE_KINDS}", name="kind"),
        {"schema": "storefront"},
    )

    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_by: Mapped[UUID | None]
