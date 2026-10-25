"""commerce ruxsatlari va rollar (10 §6.3, business/04, DEC-108, DEC-110, DEC-131).

Rol ruxsati — faqat birinchi qatlam. Ikkinchi qatlam service'da (10 §6.8):
- **own** (SALES): faqat o'ziga biriktirilgan buyurtma (+ biriktirilmagan navbatni ko'radi va oladi);
- **br** (filial doirasi): `actor.branch_ids` bo'lsa — faqat shu filiallar qoldig'i va buyurtmalari;
- chegirma limiti — `shop_policies` (DEC-110).
Lead va PC taklifi (`commerce.lead.*`, `commerce.quote.*`) — 6-modul bilan qo'shiladi.
"""

from __future__ import annotations

from collections.abc import Mapping

STOCK_VIEW = "commerce.stock.view"
STOCK_RECEIVE = "commerce.stock.receive"
ADJUST_REQUEST = "commerce.stock.adjust_request"
ADJUST_APPROVE = "commerce.stock.adjust_approve"
QUICK_SALE = "commerce.quick_sale.create"
ORDER_VIEW = "commerce.order.view"
ORDER_CREATE = "commerce.order.create_draft"
ORDER_CONFIRM = "commerce.order.confirm"
ORDER_PROCESS = "commerce.order.process"
ORDER_COMPLETE = "commerce.order.complete"
ORDER_CANCEL = "commerce.order.cancel"
ORDER_ASSIGN = "commerce.order.assign"  # menejer operatorni biriktiradi (DEC-108)
ORDER_PAID_MARK = "commerce.order.paid_mark"
ORDER_NOTE = "commerce.order.note"
DISCOUNT_APPLY = "commerce.discount.apply"
DISCOUNT_REQUEST = "commerce.discount.request"
DISCOUNT_APPROVE = "commerce.discount.approve"
# Katalog ruxsati (catalog domeni e'lon qiladi): SKU tanlash ro'yxati — `GET /shop/skus`
CATALOG_VIEW = "catalog.product.view"

_MANAGER = frozenset(
    {
        STOCK_VIEW,
        STOCK_RECEIVE,
        ADJUST_REQUEST,
        ADJUST_APPROVE,
        QUICK_SALE,
        ORDER_VIEW,
        ORDER_CREATE,
        ORDER_CONFIRM,
        ORDER_PROCESS,
        ORDER_COMPLETE,
        ORDER_CANCEL,
        ORDER_ASSIGN,
        ORDER_PAID_MARK,
        ORDER_NOTE,
        DISCOUNT_APPLY,  # limitgacha (shop_policies.discount_limit_manager_pct)
        DISCOUNT_APPROVE,
    }
)
_SALES = frozenset(
    {
        STOCK_VIEW,
        QUICK_SALE,
        ORDER_VIEW,
        ORDER_CREATE,
        ORDER_CONFIRM,
        ORDER_PROCESS,
        ORDER_COMPLETE,
        ORDER_PAID_MARK,
        ORDER_NOTE,
        DISCOUNT_REQUEST,  # operator chegirma bermaydi, faqat so'raydi (DEC-110)
    }
)
_WAREHOUSE = frozenset(
    {STOCK_VIEW, STOCK_RECEIVE, ADJUST_REQUEST, QUICK_SALE, ORDER_VIEW, ORDER_PROCESS, ORDER_NOTE}
)

COMMERCE_PERMISSIONS = sorted(_MANAGER | _SALES | _WAREHOUSE)

COMMERCE_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": _MANAGER,  # ega — hammasi, chegirma cheksiz
    "MANAGER": _MANAGER,
    "SALES": _SALES,
    "WAREHOUSE": _WAREHOUSE,
}
