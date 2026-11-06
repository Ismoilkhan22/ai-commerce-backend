"""Katalog importi: qoldiq qatorlari catalog → commerce (18 §7, db/catalog_import.md §4–§5).

Faylda mahsulot ham (catalog), qoldiq ham (commerce) bor. Qoldiqning yagona yozuvchisi — commerce (BL-019,
BL-022): catalog miqdorlarni o'z "kutish zali"ga (`catalog.import_stock_rows`) yozadi, commerce ularni shu
port orqali o'qib, o'z hujjatlari bilan qo'llaydi; natijani catalog boshqa port orqali o'qiydi (xatolar
hisoboti). Domenlar bir-birining kodini import qilmaydi (ADR-032) — ulanish `app/dependencies.py` da.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

ImportStockResultCode = Literal["APPLIED", "NO_CHANGE", "PENDING_APPROVAL", "ERROR"]


@dataclass(frozen=True)
class ImportStockRow:
    sku_id: UUID
    branch_id: UUID
    quantity: int  # fayldagi absolyut qoldiq (≥ 0)
    row_number: int  # xato hisobotini fayl qatoriga bog'lash uchun


@dataclass(frozen=True)
class ImportStockOutcome:
    sku_id: UUID
    branch_id: UUID
    result: ImportStockResultCode
    error_code: str | None


@dataclass(frozen=True)
class StockLevel:
    on_hand: int
    committed: int  # band + ajratilgan — qoldiq bundan pastga tushmaydi (TC-CON-12)


class ImportStockSource(Protocol):
    async def stock_rows(
        self,
        db: AsyncSession,
        shop_id: UUID,
        batch_id: UUID,
        after: tuple[UUID, UUID] | None,
        limit: int,
    ) -> list[ImportStockRow]:
        """Importning qoldiq qatorlari `(branch_id, sku_id)` tartibida, `after` dan keyingilari."""
        ...


class ImportStockResults(Protocol):
    async def results(
        self, db: AsyncSession, shop_id: UUID, batch_id: UUID, sku_ids: Sequence[UUID] | None = None
    ) -> list[ImportStockOutcome]:
        """Commerce qo'llagan natijalar (hisobot va ko'rib chiqish ekrani uchun)."""
        ...

    async def current_stock(
        self, db: AsyncSession, shop_id: UUID, keys: Sequence[tuple[UUID, UUID]]
    ) -> dict[tuple[UUID, UUID], int]:
        """Joriy qoldiq (on_hand) `(sku_id, branch_id)` bo'yicha — sinovda "joriy → yangi" ko'rsatish uchun.
        Qatori yo'q — natijada yo'q (yangi)."""
        ...

    async def stock_levels(
        self, db: AsyncSession, shop_id: UUID, keys: Sequence[tuple[UUID, UUID]]
    ) -> dict[tuple[UUID, UUID], StockLevel]:
        """Joriy qoldiq va band qilingan miqdor `(sku_id, branch_id)` bo'yicha — sinovda
        "buyurtmalarga band qilinganidan kam" ogohlantirishi uchun (QA F10)."""
        ...
