"""storefront tinglovchisi: sayt keshini event bilan eskirtirish (08 §4.3, S0-06).

Katalog (mahsulot holati va matni, variant, rasm, narx, kurs) yoki qoldiq o'zgarsa — shopning
`index_version` oshadi: ro'yxat va
mahsulot kalitlari birdan eskiradi, keyingi so'rov yangisini quradi. Oldin faqat TTL (60 s) bilan edi.
Inline (05 §5.1): arzon, faqat o'z keshiga tegadi; takror kelsa — bir marta ko'proq oshadi, zararsiz.
`catalog` va `commerce` kodi import qilinmaydi — faqat event turi va shop_id.
"""

from __future__ import annotations

from app.domains.storefront.common import index_version_key
from app.shared.cache import Cache
from app.shared.events.registry import EventContext, subscriber


@subscriber(
    "storefront.cache_invalidate",
    "catalog.product.published",
    "catalog.product.hidden",
    "catalog.product.archived",
    "catalog.product.updated",
    "catalog.sku.changed",
    "catalog.media.changed",
    "catalog.price.changed",
    "catalog.exchange_rate.updated",
    "commerce.stock.changed",
    schema="storefront",
    inline=True,
)
async def invalidate_site_cache(ctx: EventContext) -> None:
    if ctx.envelope.shop_id is None:
        return
    cache: Cache = ctx.services.cache
    await cache.incr(index_version_key(ctx.envelope.shop_id))
