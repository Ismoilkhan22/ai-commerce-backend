"""storefront API sxemalari: shop paneli (`/shop/storefront/*`) va ommaviy sayt (`/storefront/{slug}/*`).

Ommaviy javoblar — **faqat ruxsat etilgan maydonlar** (TC-SEC-09): tannarx, MPN, model nomi, SKU kodi, ichki
izoh, xodim va xaridor ma'lumoti bu sxemalarda umuman yo'q. Narx — doim so'mda, tiyinda (DEC-121).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.contracts.commerce import StockStatus
from app.shared.contracts.storefront import SiteState
from app.shared.text import CleanText, Text

SiteStatus = Literal["DRAFT", "LIVE", "PAUSED"]
ThemeMode = Literal["LIGHT", "DARK"]
PageKind = Literal["ABOUT", "DELIVERY_PAYMENT", "WARRANTY_RETURNS"]
StockDisplay = Literal["EXACT", "STATUS_ONLY"]
PublicSortParam = Literal["newest", "price_asc", "price_desc"]

ACCENT = r"^#[0-9A-Fa-f]{6}$"
TELEGRAM_USERNAME = r"^[A-Za-z][A-Za-z0-9_]{4,31}$"  # t.me qoidasi: 5–32 belgi
INSTAGRAM_USERNAME = r"^[A-Za-z0-9._]{1,30}$"
_EMAIL = re.compile(r"[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
# Markdown'da HTML teg va `javascript:` havola — qabul qilinmaydi (XSS); "a < b" kabi matn o'tadi
_HTML_TAG = re.compile(r"<[A-Za-z/!?]")
_UNSAFE_LINK = re.compile(r"\]\(\s*(javascript|data|vbscript):", re.IGNORECASE)


# ================================================================== shop paneli


class LogoOut(BaseModel):
    file_id: UUID
    url: str


class SiteProblem(BaseModel):
    """Saytni ochishga nima yetishmaydi (masalan telefon) — `field` va `code` 11 §6.3 dagidek."""

    field: str
    code: str


class SiteOut(BaseModel):
    status: SiteStatus
    state: SiteState = Field(description="Xaridor hozir nima ko'radi: shop holati va sayt holati birga")
    slug: str
    site_url: str
    shop_status: str
    logo: LogoOut | None
    accent_color: str
    theme_mode: ThemeMode
    tagline: str | None
    seo_description: str | None
    contact_phone: str | None
    contact_email: str | None
    telegram_username: str | None
    instagram_username: str | None
    published_at: datetime | None
    status_changed_at: datetime | None
    publish_problems: list[SiteProblem]
    version: int = Field(description='0 — sayt hali saqlanmagan: birinchi saqlashda `If-Match: "v0"`')
    updated_at: datetime | None


class SiteUpdate(BaseModel):
    """Yuborilmagan maydon o'zgarmaydi; `null` — tozalash."""

    model_config = ConfigDict(extra="forbid")

    logo_file_id: UUID | None = None
    accent_color: str | None = Field(default=None, pattern=ACCENT)
    theme_mode: ThemeMode | None = None
    tagline: CleanText | None = Field(default=None, max_length=120)
    seo_description: CleanText | None = Field(default=None, max_length=160)
    contact_phone: str | None = Field(default=None, max_length=32, description="+998 71 200 00 00")
    contact_email: Text | None = Field(default=None, max_length=254)
    telegram_username: str | None = Field(default=None, pattern=TELEGRAM_USERNAME)
    instagram_username: str | None = Field(default=None, pattern=INSTAGRAM_USERNAME)

    @field_validator("contact_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL.fullmatch(value):
            raise ValueError("invalid email")
        return value.lower() if value else value

    @field_validator("telegram_username", "instagram_username", mode="before")
    @classmethod
    def _username(cls, value: Any) -> Any:
        # "@techpc_uz" ham qabul qilinadi — saqlanadi faqat username
        return value.strip().removeprefix("@") if isinstance(value, str) else value


class PageOut(BaseModel):
    kind: PageKind
    title: str
    body_md: str
    is_published: bool
    version: int = Field(description='0 — sahifa hali yozilmagan: birinchi saqlashda `If-Match: "v0"`')
    updated_at: datetime | None


class PageList(BaseModel):
    items: list[PageOut]


class PageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: CleanText = Field(min_length=1, max_length=80)
    # Ko'rinmas belgilar (yo'nalish, nol kenglik) tozalanadi — qator va formatlash qoladi (QA M04 U11)
    body_md: CleanText = Field(max_length=20_000)
    is_published: bool

    @field_validator("body_md")
    @classmethod
    def _markdown_only(cls, value: str) -> str:
        if _HTML_TAG.search(value) or _UNSAFE_LINK.search(value):
            raise ValueError("html not allowed")
        return value


class PreviewTokenOut(BaseModel):
    token: str
    expires_at: datetime
    preview_url: str = Field(description="Sayt manzili `?preview=<token>` bilan — 30 daqiqa amal qiladi")


# ================================================================== ommaviy sayt


class PublicShop(BaseModel):
    name: str
    slug: str
    url: str = Field(description="Saytning kanonik manzili (`STOREFRONT_PUBLIC_URL`): canonical, OG, sitemap")


class PublicTheme(BaseModel):
    accent_color: str
    accent_text_color: str = Field(description="Tugma ustidagi matn rangi — kontrasti yuqorisi")
    theme_mode: ThemeMode


class PublicContacts(BaseModel):
    phone: str | None
    email: str | None
    telegram_url: str | None
    instagram_url: str | None


class PublicPageLink(BaseModel):
    kind: PageKind
    title: str


class PublicConsent(BaseModel):
    version: str
    text: str


class PublicLegal(BaseModel):
    legal_name: str | None
    tin: str


class PublicSite(BaseModel):
    """Sayt ochiq bo'lmasa (`state` LIVE emas, ko'rib chiqish ham emas) — faqat `state`, `preview`, `shop`."""

    state: SiteState
    preview: bool
    shop: PublicShop
    theme: PublicTheme | None = None
    logo_url: str | None = None
    tagline: str | None = None
    seo_description: str | None = None
    contacts: PublicContacts | None = None
    pages: list[PublicPageLink] = Field(default_factory=list)
    delivery_enabled: bool | None = None
    stock_display: StockDisplay | None = None
    pickup_branch_count: int | None = None
    consent: PublicConsent | None = None
    legal: PublicLegal | None = None
    chat_enabled: bool | None = None  # sayt chati yoqilgan (5b) — sayt chat tugmasini shunga qarab ko'rsatadi


class PublicCategoryOut(BaseModel):
    code: str
    parent_code: str | None
    name: dict[str, str] = Field(description="{uz, ru, en}")
    product_count: int


class PublicCategoryList(BaseModel):
    items: list[PublicCategoryOut]


class PublicProductCardOut(BaseModel):
    id: UUID
    slug: str
    title: str
    brand: str | None
    category_code: str
    image_url: str | None
    price_from_uzs_minor: int
    variant_count: int
    stock_status: StockStatus
    available: int | None = Field(description="Faqat shop aniq sonni ko'rsatsa (DEC-128), aks holda null")


class PublicProductList(BaseModel):
    items: list[PublicProductCardOut]
    next_cursor: str | None
    has_more: bool
    as_of: datetime = Field(description="Narx va mavjudlik shu vaqt holatiga (60 s gacha eski, BL-026)")


class PublicBranchStock(BaseModel):
    branch_id: UUID
    name: str
    stock_status: StockStatus
    available: int | None


class PublicVariantOut(BaseModel):
    sku_id: UUID
    name: str | None
    condition: str
    warranty_months: int | None
    attributes: dict[str, Any]
    price_uzs_minor: int
    stock_status: StockStatus
    available: int | None
    branches: list[PublicBranchStock] | None = Field(
        description="Faqat shopda 2 va undan ko'p ochiq olib ketish joyi bo'lsa (DEC-135)"
    )


class PublicProductOut(BaseModel):
    id: UUID
    slug: str
    canonical_path: str = Field(description="/p/{id}/{slug} — nom o'zgarsa ham id bo'yicha topiladi")
    title: str
    brand: str | None
    description: str | None
    category_code: str
    images: list[str]
    variants: list[PublicVariantOut]
    as_of: datetime


class PublicPageOut(BaseModel):
    kind: PageKind
    title: str
    body_md: str


class PublicBranchOut(BaseModel):
    id: UUID
    name: str
    address: str
    phone: str | None
    working_hours: dict[str, Any]
    latitude: float | None
    longitude: float | None


class PublicBranchList(BaseModel):
    items: list[PublicBranchOut]


class PrivacySection(BaseModel):
    key: str
    text: str


class PublicPrivacy(BaseModel):
    version: str
    title: str
    sections: list[PrivacySection]
