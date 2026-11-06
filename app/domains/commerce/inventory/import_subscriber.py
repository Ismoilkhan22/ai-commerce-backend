"""commerce: katalog importi qoldig'ini qo'llash (18 §7, §14).

`catalog.import.completed` (qoldiq qatorlari bor bo'lsa) va `commerce.import_stock.continue` (keyingi bo'lak).
Tranzaksiyasiz: har bo'lak o'z tranzaksiyasida; takror ishlasa natija jadvali qatorni qayta qo'llamaydi.
"""

from __future__ import annotations

from uuid import UUID

from app.domains.commerce.providers import CommerceServices
from app.shared.events.registry import EventContext, subscriber


def _uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value else None


@subscriber(
    "commerce.import_stock",
    "catalog.import.completed",
    "commerce.import_stock.continue",
    schema="commerce",
    transactional=False,
)
async def apply_import_stock(ctx: EventContext) -> None:
    commerce: CommerceServices = ctx.services.commerce
    payload = ctx.envelope.payload
    assert ctx.envelope.shop_id is not None
    if ctx.envelope.event_type == "catalog.import.completed" and not int(payload.get("stock_rows", 0)):
        return
    after_branch, after_sku = _uuid(payload.get("after_branch_id")), _uuid(payload.get("after_sku_id"))
    await commerce.import_stock.apply_chunk(
        ctx.database,
        ctx.envelope.shop_id,
        UUID(str(payload["batch_id"])),
        _uuid(payload.get("committed_by")),
        (after_branch, after_sku) if after_branch and after_sku else None,
    )


@subscriber("commerce.pos_stock", "network.pos_stock.received", schema="commerce")
async def apply_pos_stock(ctx: EventContext) -> None:
    """M22: kassa/ERP qoldig'i (BR-X12) — eski yoki band qilinganidan kam bo'lsa ustidan yozilmaydi."""
    commerce: CommerceServices = ctx.services.commerce
    assert ctx.envelope.shop_id is not None
    await commerce.pos_stock.apply(ctx.session, ctx.envelope.shop_id, dict(ctx.envelope.payload))
