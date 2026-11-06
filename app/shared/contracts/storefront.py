"""SitePort — boshqa domenlar (commerce: saytdan buyurtma so'rovi) sayt holatini shu orqali biladi (ADR-032).

Shop URL'dagi `slug` dan aniqlanadi; xaridor uchun holat — shop holati (platforma) va sayt holati birga
(storefront.md §0). `storefront` kodini import qilish — TAQIQ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.errors.base import SiteNotAvailableError

SiteState = Literal["LIVE", "COMING_SOON", "PAUSED"]


@dataclass(frozen=True)
class SiteAccess:
    shop_id: UUID
    slug: str
    shop_name: str
    shop_status: str  # platform.shops.status
    site_status: str  # DRAFT | LIVE | PAUSED (yozuv yo'q — DRAFT)
    state: SiteState  # xaridor nima ko'radi
    preview: bool  # ega "ko'rib chiqish" havolasi bilan ochdi — buyurtma formasi o'chiq


class SitePort(Protocol):
    async def resolve(self, db: AsyncSession, slug: str, *, preview_token: str | None = None) -> SiteAccess:
        """Shopni topadi va tranzaksiyaga shu shop kontekstini o'rnatadi (RLS).

        Bunday slug yo'q yoki shop yopilgan — `NotFoundError`. Holatni chaqiruvchi tekshiradi
        (`ensure_open`): buyurtma so'rovi faqat `LIVE` va ko'rib chiqish rejimida emas.
        """
        ...


def ensure_open(access: SiteAccess, *, for_order: bool = False) -> None:
    """Sayt ochiqmi: o'qish — LIVE yoki egasining ko'rib chiqishi; buyurtma — faqat LIVE, ko'rib chiqishda
    emas (storefront.md §0). Aks holda 409 `SITE_NOT_AVAILABLE` va `details.state`."""
    if access.state == "LIVE" or (access.preview and not for_order):
        return
    raise SiteNotAvailableError("Site is not available", state=access.state, preview=access.preview)
