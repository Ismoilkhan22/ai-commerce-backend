"""commerce ruxsatlari va rollar (10 §6.3, business/04, DEC-108, DEC-110, DEC-131).

Rol ruxsati — faqat birinchi qatlam. Ikkinchi qatlam service'da (10 §6.8):
- **own** (SALES): faqat o'ziga biriktirilgan buyurtma (+ biriktirilmagan navbatni ko'radi va oladi);
- **br** (filial doirasi): `actor.branch_ids` bo'lsa — faqat shu filiallar qoldig'i va buyurtmalari;
- chegirma limiti — `shop_policies` (DEC-110).
Lead va PC taklifi (6a, DEC-142 taklif): operator o'z leadi va taklifini yuritadi va tasdiqlangan taklifni
yuboradi; tasdiqlash — menejer/ega (o'zi tuzganini emas, DEC-109); omborchi ko'rmaydi.
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
LEAD_VIEW = "commerce.lead.view"
LEAD_MANAGE = "commerce.lead.edit"  # yaratish, tahrirlash, biriktirish, yo'qotildi deb yopish
LEAD_ASSIGN = "commerce.lead.assign"  # boshqa xodimga biriktirish (menejer)
QUOTE_VIEW = "commerce.quote.view"
QUOTE_EDIT = "commerce.quote.draft"  # qoralama, qatorlar, tekshiruvga yuborish, PC yig'ish sahifasi
QUOTE_APPROVE = "commerce.quote.approve"
QUOTE_SEND = "commerce.quote.send"  # tasdiqlangan taklifni xaridorga yuborish (AI emas, DEC-142 Q4)
# Tannarx (DEC-146): faqat ega. Menejer, operator va omborchi tannarxni API javobida ham ko'rmaydi (BL-065)
COST_VIEW = "commerce.cost.view"
COST_EDIT = "commerce.cost.edit"  # kirimga tannarx yozish va o'rtachani qo'lda qo'yish
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
        LEAD_VIEW,
        LEAD_MANAGE,
        LEAD_ASSIGN,
        QUOTE_VIEW,
        QUOTE_EDIT,
        QUOTE_APPROVE,
        QUOTE_SEND,
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
        LEAD_VIEW,
        LEAD_MANAGE,
        QUOTE_VIEW,
        QUOTE_EDIT,
        QUOTE_SEND,
    }
)
_WAREHOUSE = frozenset(
    {STOCK_VIEW, STOCK_RECEIVE, ADJUST_REQUEST, QUICK_SALE, ORDER_VIEW, ORDER_PROCESS, ORDER_NOTE}
)

_OWNER = _MANAGER | {COST_VIEW, COST_EDIT}

COMMERCE_PERMISSIONS = sorted(_OWNER | _SALES | _WAREHOUSE)

COMMERCE_ROLE_GRANTS: Mapping[str, frozenset[str]] = {
    "OWNER": _OWNER,  # ega — hammasi, chegirma cheksiz
    "MANAGER": _MANAGER,
    "SALES": _SALES,
    "WAREHOUSE": _WAREHOUSE,
}
