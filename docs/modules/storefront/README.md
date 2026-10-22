# storefront

**Qatlam:** domain · **Schema:** `storefront` · **Slice:** S1 · **Egasi:** ___
**Biznes modullar:** M07 · **Qoidalar:** BL-024, BL-025, BL-026, DEC-115 · **Holatlar:** o'z FSM'i yo'q (shop holati — FSM-01, mahsulot — FSM-02)

## 1. Nima qiladi

Har shop uchun ommaviy sayt: `{shop}.<platforma>.uz` ([21](../../engineering/21-frontend.md)). Sayt sozlamalari va sahifalarni saqlaydi. Xaridorga faqat shu shopning saytga chiqarilgan mahsulotlarini, ommaviy maydonlari bilan ko'rsatadi (BL-024).

Bu domen qilmaydi:
- **Buyurtma so'rovi va kuzatuv** — `commerce` domenining `storefront` surface router'i (`POST /storefront/{slug}/order-requests`).
- **Sayt chati** — `messaging`.
- **Narx va qoldiqning haqiqiy qiymati** — saytdagi ma'lumot taxminiy. Buyurtmada `commerce` qayta tekshiradi (BL-026, ADR-019).

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `sites` | Sayt sozlamalari (subdomen, tema, logo, kontaktlar, tillar), sahifalar | `sites` (`UNIQUE (subdomain)`), `pages` (`UNIQUE (shop_id, slug, locale)`) |
| `public_catalog` | Saytdagi katalog ro'yxati va mahsulot sahifasi | `public_products` — event'lardan proyeksiya; faqat ommaviy maydonlar, tannarx yo'q; qoldiq — shop sozlamasi `stock_display` bo'yicha (`EXACT` — son, `STATUS_ONLY` — "bor / kam qoldi / yo'q") ([07](../../engineering/07-data-layer.md) §4.7, [08](../../engineering/08-cache-and-realtime.md) §4.5) |

## 3. Holatlar

Domenning o'z holatlar ketma-ketligi yo'q. Saytda ko'rinish boshqa domenlar holatiga bog'liq:
- **Shop `ACTIVE` bo'lmasa** — sayt yopiq.
- **Shop `SUSPENDED` bo'lsa** — yangi buyurtma so'rovi qabul qilinmaydi.
- **Mahsulot `HIDDEN` yoki `ARCHIVED` bo'lsa** — ko'rinmaydi. Bu o'qish paytida ham tekshiriladi ([08](../../engineering/08-cache-and-realtime.md) §4.3).

## 4. Event'lar

### Chiqaradi

- `storefront.site.updated` — sayt sozlamalari (logo, kontaktlar, mavzu) o'zgarganda; o'z keshini tozalaydi ([05](../../engineering/05-events-and-outbox.md) §8.8).

### Tinglaydi

| Event | Kimdan | Nima qiladi |
|---|---|---|
| `catalog.product.published` / `hidden` / `archived` | catalog | `public_products` yangilanadi, kesh `index_version` oshadi |
| `catalog.price.changed`, `catalog.exchange_rate.updated` | catalog | Narx proyeksiyasi va kesh yangilanadi |
| `catalog.hardware_spec.updated`, `catalog.import.completed` | catalog | Kesh tozalanadi (import — to'liq) |
| `commerce.stock.changed` | commerce | `stock_status` (va `EXACT` bo'lsa `available_qty`) hamda kesh yangilanadi |
| `platform.shop.activated` / `suspended` | platform | Sayt yoqiladi / yangi buyurtmalar yopiladi |
| `platform.shop.policy_changed` | platform | `stock_display` o'zgarsa — `public_products` qayta hisoblanadi, kesh tozalanadi |

## 5. Query Port

**Beradi:** yo'q.

**Ishlatadi:**
- `CatalogQueryPort.get_public_projection`, `CommerceQueryPort.get_stock_levels` — faqat proyeksiyani qayta qurish (rebuild) uchun ([05](../../engineering/05-events-and-outbox.md) §8.9). Oddiy ishda sayt `public_products` proyeksiyasidan o'qiydi.
- `platform/shops` — ommaviy shop ma'lumoti: nom, filiallar, ish vaqti.

## 6. API

| Surface | Metod va yo'l | Ruxsat | Idempotency |
|---|---|---|---|
| shop | `GET` / `PATCH /shop/site`, `GET` / `POST` / `PATCH /shop/site/pages` | `storefront.site.edit` | If-Match / Idem |
| storefront | `GET /storefront/{slug}/site`, `GET …/products`, `GET …/products/{product_slug}`, `GET …/pages/{page_slug}` | Ommaviy | — |

Manba: [11](../../engineering/11-api-conventions-errors-i18n.md) §9.7.

**Rate limit:** storefront o'qish — IP + shop bo'yicha 120 so'rov/daqiqa ([08](../../engineering/08-cache-and-realtime.md) §5.1).

## 7. Ruxsatlar

| Kod | Kimda bor |
|---|---|
| `storefront.site.edit` | Faqat ega ([10](../../engineering/10-security-tenancy-rbac.md)) |

Saytni ochadigan xaridor anonim, ruxsat kodi yo'q. Ommaviy o'qish xususiy jadvallarga kirmaydi.

## 8. Kesh

| Ma'lumot | TTL | Invalidatsiya |
|---|---|---|
| Katalog ro'yxati | 60 s + jitter | `index_version` hisoblagichi |
| Mahsulot sahifasi | 60 s | `DEL` |
| Sayt sozlamalari | 300 s | — |
| `slug → shop_id` | 600 s | — |

- Kalit: `cos:v1:shop:{shop_id}:storefront:...`.
- Stampede himoyasi bor ([08](../../engineering/08-cache-and-realtime.md) §4).

**Fon va rejali ishlar:** yo'q. Subscriber'lar inline ishlaydi (`05` §5.1).

## 9. Metrikalar

`09` ro'yxatida `storefront` uchun alohida metrika yo'q. Umumiy `cos_api_*` va `cos_api_rate_limited_total` ishlatiladi. Saytdan kelgan buyurtmalar `cos_commerce_order_drafted_total{source="storefront"}` bilan sanaladi.

## 10. Testlar

- UAT-M07 ("Yashirilgan mahsulot havolasi → mavjud emas"; "B shop mahsuloti A shop saytida hech qachon ko'rinmaydi")
- TC-ISO — kesh kalitida shop prefiksi bor
- Buyurtma so'rovida narx yoki qoldiq o'zgargan → 409 (`commerce` tomonida, [12](../../engineering/12-concurrency-and-transactions.md))

## 11. Ochiq savollar

1. **Shop o'z domeni** (BL-025) — Stage 1 da faqat platforma subdomeni (A-06). Qachon qo'shiladi?
