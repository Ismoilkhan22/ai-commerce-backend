"""network.canonical_products, sku_links, public_offers — db/network.md (Stage 2: M23, M24)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.db.encryption import EncryptedString
from app.shared.db.mixins import IdMixin, ShopScopedMixin, TimestampMixin, VersionMixin

SCHEMA = "network"
CANONICAL_STATUSES = ("ACTIVE", "MERGED", "RETIRED")
CANONICAL_SOURCES = ("AUTO_MPN", "PLATFORM")
LINK_STATUSES = ("LINKED", "PENDING_REVIEW", "UNLINKED")
LINK_METHODS = ("EXACT_MPN", "PLATFORM_REVIEW", "NONE")
OFFER_STATUSES = ("ACTIVE", "WITHDRAWN", "SUSPENDED")
OFFER_FIELDS = ("price", "condition", "warranty", "availability", "branch")  # branch — M33, standartda yopiq
AVAILABILITY = ("IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK")


class CanonicalProduct(IdMixin, TimestampMixin, VersionMixin, Base):
    """Umumiy mahsulot — ochiq ma'lumot, shop'siz (RLS yo'q). Narx va qoldiq yo'q."""

    __tablename__ = "canonical_products"
    __table_args__ = (
        Index(
            "uq_canonical_products_brand_mpn",
            "brand_norm",
            "mpn_norm",
            unique=True,
            postgresql_where=text("mpn_norm IS NOT NULL AND status = 'ACTIVE'"),
        ),
        CheckConstraint(f"status IN {CANONICAL_STATUSES}", name="status"),
        CheckConstraint(f"source IN {CANONICAL_SOURCES}", name="source"),
        {"schema": SCHEMA},
    )

    brand: Mapped[str | None] = mapped_column(Text)
    brand_norm: Mapped[str | None] = mapped_column(Text)
    mpn_norm: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    category_code: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    merged_into_id: Mapped[UUID | None]
    source: Mapped[str] = mapped_column(Text, server_default="AUTO_MPN")


class SkuLink(ShopScopedMixin, TimestampMixin, VersionMixin, Base):
    """Shop SKU ↔ umumiy mahsulot. Avtomatik faqat aniq (brend + MPN); qolgani — platforma ko'rib chiqadi."""

    __tablename__ = "sku_links"
    __table_args__ = (
        PrimaryKeyConstraint("shop_id", "sku_id"),
        Index("ix_sku_links_status", "status", "updated_at"),
        CheckConstraint(f"status IN {LINK_STATUSES}", name="status"),
        CheckConstraint(f"method IN {LINK_METHODS}", name="method"),
        {"schema": SCHEMA},
    )

    sku_id: Mapped[UUID]
    canonical_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text, server_default="NONE")
    reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None]  # platforma xodimi (platform.platform_members.id)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicOffer(IdMixin, ShopScopedMixin, Base):
    """Ommaviy taklif — shop aniq yoqqan SKU proyeksiyasi (BL-079…081). `listing_version` monoton (BL-085)."""

    __tablename__ = "public_offers"
    __table_args__ = (
        UniqueConstraint("shop_id", "sku_id"),
        Index("ix_public_offers_canonical", "canonical_id", postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_public_offers_status_updated", "status", "updated_at"),
        CheckConstraint(f"status IN {OFFER_STATUSES}", name="status"),
        CheckConstraint(f"availability IS NULL OR availability IN {AVAILABILITY}", name="availability"),
        CheckConstraint("currency IS NULL OR currency IN ('UZS', 'USD')", name="currency"),
        {"schema": SCHEMA},
    )

    sku_id: Mapped[UUID]
    product_id: Mapped[UUID | None]  # shop saytidagi mahsulot sahifasi (Stage 3 "Do'konga o'tish")
    canonical_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    listing_version: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))
    permitted_fields: Mapped[list[str]] = mapped_column(ARRAY(Text))
    title: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    category_code: Mapped[str] = mapped_column(Text)
    price_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(Text)
    price_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)
    condition: Mapped[str | None] = mapped_column(Text)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    availability: Mapped[str | None] = mapped_column(Text)
    # M33: olib ketish filiallari (faqat `branch` ruxsat etilgan bo'lsa): nom, manzil, koordinata, mavjudlik
    branches: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    withdraw_reason: Mapped[str | None] = mapped_column(
        Text
    )  # OWNER | NO_PRICE | NOT_SELLABLE | SHOP_SUSPENDED
    published_by: Mapped[UUID | None]
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Referral(IdMixin, ShopScopedMixin, Base):
    """Stage 3 (M35): global qidiruvdan shop saytiga o'tish. Xaridor shaxsi yo'q — faqat IP xeshi."""

    __tablename__ = "referrals"
    __table_args__ = (
        Index("ix_referrals_shop_id_created_at", "shop_id", "created_at"),
        {"schema": SCHEMA},
    )

    offer_id: Mapped[UUID]
    ip_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


BADGE_LEVELS = ("VERIFIED",)
REPORT_REASONS = ("WRONG_PRICE", "NOT_AVAILABLE", "FAKE_PRODUCT", "FRAUD", "OTHER")
REPORT_STATUSES = ("OPEN", "DISMISSED", "ACTIONED")


class ShopBadge(IdMixin, Base):
    """M29: "Tasdiqlangan do'kon" — faqat dalil bilan va muddatli (BL-087). Platforma darajasi, ochiq."""

    __tablename__ = "shop_badges"
    __table_args__ = (
        Index("ix_shop_badges_shop_id_granted_at", "shop_id", "granted_at"),
        CheckConstraint("level IN ('VERIFIED')", name="level"),
        {"schema": SCHEMA},
    )

    shop_id: Mapped[UUID]
    level: Mapped[str] = mapped_column(Text, server_default="VERIFIED")
    evidence: Mapped[str] = mapped_column(Text)  # nima tekshirildi (hujjat nomi, sana) — shaxsiy ma'lumotsiz
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    granted_by: Mapped[UUID | None]  # platforma xodimi
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class OfferReport(IdMixin, Base):
    """M29: xaridor shikoyati (BL-088) — platforma ko'rib chiqadi; xaridor shaxsi yo'q (IP xeshi)."""

    __tablename__ = "offer_reports"
    __table_args__ = (
        Index("ix_offer_reports_status_created_at", "status", "created_at"),
        CheckConstraint(f"reason IN {REPORT_REASONS}", name="reason"),
        CheckConstraint(f"status IN {REPORT_STATUSES}", name="status"),
        {"schema": SCHEMA},
    )

    offer_id: Mapped[UUID]
    shop_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="OPEN")
    ip_hash: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None]
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


API_SCOPES = ("catalog.read", "stock.read", "prices.write", "stock.write")


class ApiKey(IdMixin, ShopScopedMixin, Base):
    """M30: hamkor API kaliti (BL-089) — faqat xesh saqlanadi, ruxsatlar cheklangan, bekor qilinadi.
    Kalit: `cos_<prefix>_<sir>`; `prefix` bo'yicha topiladi (RLS identity varianti `app.api_key_prefix`)."""

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("prefix"),
        Index("ix_api_keys_shop_id_created_at", "shop_id", "created_at"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # M22: tashqi qoldiq farqi darhol qo'llanadimi (aks holda — ega/menejer tasdig'i, nizo)
    stock_auto_apply: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class StockReport(IdMixin, ShopScopedMixin, Base):
    """M22: kassa/ERP yuborgan qoldiq paketi. `network` qoldiqni yozmaydi — `network.pos_stock.received`
    event'i; `commerce` qo'llaydi va natijani `commerce.pos_stock.applied` bilan qaytaradi (BR-X12)."""

    __tablename__ = "stock_reports"
    __table_args__ = (
        Index("ix_stock_reports_shop_id_received_at", "shop_id", "received_at"),
        CheckConstraint("status IN ('RECEIVED', 'PROCESSED')", name="status"),
        {"schema": SCHEMA},
    )

    key_id: Mapped[UUID]
    items_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="RECEIVED")
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


ALERT_STATUSES = ("ACTIVE", "CANCELLED")


class GlobalBotChat(IdMixin, Base):
    """M39: global Telegram botning xaridor chati (BL-108 — shop botlaridan alohida, ma'lumot aralashmaydi).
    Stage 3 da xaridor identifikatori shu (SMS va parolsiz); chat raqami shifrlangan."""

    __tablename__ = "global_bot_chats"
    __table_args__ = (UniqueConstraint("chat_hash"), {"schema": SCHEMA})

    chat_hash: Mapped[str] = mapped_column(Text)  # HMAC — qidirish uchun
    chat_id_enc: Mapped[str] = mapped_column(EncryptedString)
    language: Mapped[str | None] = mapped_column(Text)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceAlert(IdMixin, Base):
    """M36: narx tushsa xabar (BL-102, BL-103) — xaridor yoqadi, bir bosishda bekor, kuniga ko'pi 1 marta."""

    __tablename__ = "price_alerts"
    __table_args__ = (
        UniqueConstraint("chat_ref", "canonical_id"),
        Index("ix_price_alerts_status_canonical", "status", "canonical_id"),
        CheckConstraint(f"status IN {ALERT_STATUSES}", name="status"),
        {"schema": SCHEMA},
    )

    chat_ref: Mapped[UUID]  # network.global_bot_chats.id
    canonical_id: Mapped[UUID]
    baseline_price_uzs_minor: Mapped[int | None] = mapped_column(
        BigInteger
    )  # oxirgi xabar qilingan eng past narx
    status: Mapped[str] = mapped_column(Text, server_default="ACTIVE")
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


AD_STATUSES = ("PENDING_REVIEW", "ACTIVE", "PAUSED", "REJECTED", "ENDED")


class AdCampaign(IdMixin, ShopScopedMixin, Base):
    """M37: reklama o'rni (BL-099, BL-104) — oddiy natijalardan alohida, "Reklama" deb belgilanadi, oddiy
    saralash va AI maslahatchiga ta'sir qilmaydi. Platforma tasdiqlaydi; to'lov — hisob orqali (DEC-100)."""

    __tablename__ = "ad_campaigns"
    __table_args__ = (
        Index("ix_ad_campaigns_status_ends_at", "status", "ends_at"),
        CheckConstraint(f"status IN {AD_STATUSES}", name="status"),
        CheckConstraint("ends_at > starts_at", name="period"),
        {"schema": SCHEMA},
    )

    sku_id: Mapped[UUID]  # ommaviy taklif SKU'si
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text))  # bo'sh — taklif nomi bo'yicha
    status: Mapped[str] = mapped_column(Text, server_default="PENDING_REVIEW")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    clicks: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_by: Mapped[UUID | None]
    reviewed_by: Mapped[UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


BUYER_LOCALES = ("uz", "ru", "en")
ADVISOR_ROLES = ("user", "assistant")


class Buyer(IdMixin, Base):
    """Xaridor akkaunti (SMS kod bilan kirish) — platforma darajasi, RLS yo'q. Telefon: HMAC (qidirish) +
    shifrlangan qiymat. Akkauntni o'chirish hamma bolalarni ham o'chiradi (cascade)."""

    __tablename__ = "buyers"
    __table_args__ = (
        UniqueConstraint("phone_hash"),
        CheckConstraint(f"locale IN {BUYER_LOCALES}", name="locale"),
        {"schema": SCHEMA},
    )

    phone_hash: Mapped[str] = mapped_column(Text)
    phone_enc: Mapped[str] = mapped_column(EncryptedString)
    name: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, server_default="uz")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyerLoginCode(IdMixin, Base):
    """Bir martalik SMS kod so'rovi (signup_requests kabi). `phone_enc` — kod tasdiqlanganda akkaunt ochish
    uchun; tasdiqdan keyin tozalanadi."""

    __tablename__ = "buyer_login_codes"
    __table_args__ = (
        Index("ix_buyer_login_codes_phone_created", "phone_hash", "created_at"),
        {"schema": SCHEMA},
    )

    phone_hash: Mapped[str] = mapped_column(Text)
    phone_enc: Mapped[str | None] = mapped_column(EncryptedString)
    code_hash: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sends: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyerSession(IdMixin, Base):
    """Token `<session_id>.<sir>`; bazada faqat sirning sha256 xeshi. Muddat 60 kun, sirpanuvchi."""

    __tablename__ = "buyer_sessions"
    __table_args__ = (Index("ix_buyer_sessions_buyer", "buyer_id"), {"schema": SCHEMA})

    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("network.buyers.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyerView(Base):
    """Ko'rilgan mahsulot: (xaridor, mahsulot) bo'yicha bitta qator, eng yangi 200 ta."""

    __tablename__ = "buyer_views"
    __table_args__ = (PrimaryKeyConstraint("buyer_id", "canonical_id"), {"schema": SCHEMA})

    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("network.buyers.id", ondelete="CASCADE"))
    canonical_id: Mapped[UUID]
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyerSearch(IdMixin, Base):
    """Qidiruv tarixi: eng yangi 100 ta; oxirgisi bilan bir xil bo'lsa yozilmaydi."""

    __tablename__ = "buyer_searches"
    __table_args__ = (Index("ix_buyer_searches_buyer_at", "buyer_id", "searched_at"), {"schema": SCHEMA})

    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("network.buyers.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyerFavorite(Base):
    """Saqlangan mahsulot; `saved_price_uzs_minor` — saqlagan paytdagi eng past narx. Ko'pi bilan 200 ta."""

    __tablename__ = "buyer_favorites"
    __table_args__ = (PrimaryKeyConstraint("buyer_id", "canonical_id"), {"schema": SCHEMA})

    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("network.buyers.id", ondelete="CASCADE"))
    canonical_id: Mapped[UUID]
    saved_price_uzs_minor: Mapped[int | None] = mapped_column(BigInteger)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyerAdvisorMessage(IdMixin, Base):
    """Maslahatchi suhbati tarixi (xaridor xabari va javob, manbalar bilan): eng yangi 200 ta."""

    __tablename__ = "buyer_advisor_messages"
    __table_args__ = (
        Index("ix_buyer_advisor_messages_buyer_at", "buyer_id", "created_at"),
        CheckConstraint(f"role IN {ADVISOR_ROLES}", name="role"),
        {"schema": SCHEMA},
    )

    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("network.buyers.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    text: Mapped[str] = mapped_column(Text)  # `text()` funksiyasini soyalaydi — shuning uchun oxirida
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
