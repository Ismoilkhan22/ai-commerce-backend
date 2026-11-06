# `network` sxemasi — umumiy katalog va ommaviy takliflar (Stage 2: M23, M24, M28 asosi)

> **Holat:** dizayn, PROPOSED (2026-11-02, Claude — founder ko'rib chiqadi). Asos: `engineering/28`, BL-076…081, BL-085, BR-X07, BR-X08.
> **Qoida:** `network` `catalog`/`commerce` jadvallarini o'qimaydi — faqat Query Port'lar va event'lar (TC-NET-04).

---

## Jadvallar

### `network.canonical_products` — umumiy mahsulot (platforma darajasi, shop'siz, RLS yo'q)

Ochiq ma'lumot: brend, model, variant. Narx va qoldiq yo'q.

- `id`, `version`, `created_at`, `updated_at`
- `brand` (ko'rsatish), `brand_norm` (normallashtirilgan)
- `mpn_norm` — ishlab chiqaruvchi kodi (normallashtirilgan); `UNIQUE (brand_norm, mpn_norm)` (`mpn_norm` bo'lsa)
- `title`, `category_code`, `attributes` (JSONB, ochiq xususiyatlar)
- `status`: `ACTIVE` | `MERGED` | `RETIRED`; `merged_into_id` (MERGED bo'lsa)
- `source`: `AUTO_MPN` (birinchi taklifdan, aniq kod bilan) | `PLATFORM` (admin yaratgan)

### `network.sku_links` — shop SKU ↔ umumiy mahsulot (shop jadvali, RLS)

- `shop_id`, `sku_id` (PK birga), `version`
- `canonical_id` (NULL — bog'lanmagan)
- `status`: `LINKED` | `PENDING_REVIEW` | `UNLINKED`
- `method`: `EXACT_MPN` | `PLATFORM_REVIEW` | `NONE`
- `reason` — nega ko'rib chiqishga tushdi (`NO_MPN`, `NO_BRAND`, `MPN_CONFLICT`)
- `reviewed_by` (platforma xodimi), `reviewed_at`
- Har o'zgarish — audit (`network.link.changed`) va event `network.canonical_match.changed`

### `network.public_offers` — ommaviy taklif (shop jadvali, RLS + ommaviy o'qish varianti)

Shop aniq yoqqan SKU'ning proyeksiyasi. Tannarx, xaridor, ichki izoh, aniq qoldiq soni — yo'q (BL-081).

- `id`, `shop_id`, `sku_id` (`UNIQUE (shop_id, sku_id)`), `canonical_id` (sku_links'dan nusxa)
- `status`: `ACTIVE` | `WITHDRAWN` | `SUSPENDED` (shop to'xtatilgan / SKU arxivlangan / narx yo'q)
- `listing_version` — monoton; har proyeksiya yangilanishida +1 (BL-085)
- `permitted_fields` — `price`, `condition`, `warranty`, `availability`, `branch` dan tanlangan (standart: hammasi, `branch` dan tashqari)
- Proyeksiya: `title`, `brand`, `category_code`, `price_minor`, `currency`, `price_uzs_minor`, `condition`, `warranty_months`, `availability` (`IN_STOCK` | `LOW_STOCK` | `OUT_OF_STOCK`), `city`
- `last_verified_at` (proyeksiya oxirgi marta manbadan yangilangan), `published_at`, `withdrawn_at`, `withdraw_reason`
- RLS: yozish — faqat o'z shopi; o'qish — o'z shopi YOKI `app.network_public = 'on'` bo'lganda faqat `ACTIVE` qatorlar (Stage 3 qidiruvi shu bilan o'qiydi)

## Oqimlar

```
Ega: "Shu mahsulotlar global qidiruvda ko'rinsin" (faqat ACTIVE shop) ──▶ public_offers ACTIVE
    ──▶ SKU MPN + brend bormi?
          ├─ Ha, shu (brend, MPN) umumiy mahsulot bor ──▶ LINKED (EXACT_MPN)
          ├─ Ha, yo'q ──▶ yangi umumiy mahsulot (AUTO_MPN) + LINKED
          └─ Yo'q / bir nechta ──▶ PENDING_REVIEW (taklif yolg'iz ko'rinadi, platforma admini bog'laydi)
    ──▶ outbox network.public_offer.published

catalog.price.changed / catalog.product.hidden|archived|published / commerce.stock.changed
    ──▶ faqat ommaviy SKU'lar uchun proyeksiya qayta o'qiladi ──▶ listing_version +1 ──▶ updated / withdrawn
Ega "yopish" ──▶ WITHDRAWN bitta tranzaksiyada + outbox (BL-080, read-time deny — Stage 3)
platform.shop.suspended|closed ──▶ shopning barcha takliflari SUSPENDED
```

## Qat'iy qoidalar

- Standartda hammasi yopiq (BL-079). Taklif faqat ega bosganda.
- Avtomatik bog'lash faqat aniq (brend + MPN) bo'yicha; nom o'xshashligi bilan hech qachon (BR-X08, TC-016). Holat farqi (NEW / USED) — taklif darajasida, umumiy mahsulot bitta.
- Narxi yo'q yoki dollar narxi va kursi yo'q SKU ommaviy bo'lmaydi (`SUSPENDED`, `NO_PRICE`).
- Admin bog'lashni bekor qilsa (`UNLINKED`) — tarix auditda; takliflar `canonical_id` siz qoladi.
