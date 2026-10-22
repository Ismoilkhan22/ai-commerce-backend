# 28 — Stage 2–3: shoplar tarmog'i va global qidiruv

> **Versiya:** v2 (2026-10-22). Eski `14_GLOBAL_CATALOG_SEARCH_ARCHITECTURE` o'rnini bosadi.
> **Holat:** arxitektura rejasi — **Stage 1 kodi emas**. Stage 1 da bu jadvallar va domenlar yaratilmaydi.
> **Domenlar:** `network` (Stage 2, schema `network`), `marketplace` (Stage 3, schema `marketplace`). `catalog` va `commerce` — xususiy manba bo'lib qoladi.
> **Biznes:** M21–M39, BL-073…108, BR-X07, BR-X08, BR-X12, TC-015…019, TC-024, TC-026.

## 1. Muammo

Stage 2–3 da shopning ma'lumoti birinchi marta **boshqalarga** ko'rinadi. Uchta xavf:
1. **Maxfiylik:** shop rozilik bermagan mahsulot, tannarx yoki xaridor ma'lumoti global qidiruvga chiqib qolishi (BL-081, BL-090).
2. **Qaytarib olish:** shop taklifni qaytarib olgandan keyin qidiruv indeksi kechikib, taklif hali ko'rinib turishi (BR-X07, TC-015).
3. **Noto'g'ri birlashtirish:** "RTX 5060 8GB" va "RTX 5060 Ti" bitta mahsulot deb ko'rsatilishi (BR-X08, TC-016).

Arxitektura cheklovi: yangi domenlar `catalog`/`commerce` jadvallarini o'qiy olmaydi va o'zgartira olmaydi (00 §2, ADR-035).

## 2. Uchta alohida tushuncha

| Tushuncha | Egasi | Mazmuni |
|---|---|---|
| **Shop SKU** | `catalog` (+ qoldiq `commerce`) | Shopning aniq varianti; narx, qoldiq, maxfiylik — shop qaroriga ko'ra. Xususiy |
| **Umumiy mahsulot** (`canonical_product`) | `network` | Platforma tasdiqlagan ishlab chiqaruvchi/model/variant; narx va qoldiq **yo'q** |
| **Ommaviy taklif** (`public_offer`) | `network` | Shopning **aniq roziligi** bilan chiqarilgan SKU: ommaviy narx, holat, kafolat, filial, yangilangan vaqt, mavjudlik belgisi; qaytarib olinadi |

Bitta umumiy mahsulot ↔ ko'p ommaviy taklif. O'xshash nom bir xil mahsulot degani emas.

## 3. Domenlar va ma'lumot oqimi

```
catalog ──catalog.product.published|hidden|archived, catalog.price.changed──┐
commerce ──commerce.stock.changed──────────────────────────────────────────┤──▶ network subscriber'lari
                                                                            │   (faqat shop ommaviy qilgan SKU'lar uchun)
Ega dashboard: "shu SKU ommaviy bo'lsin, shu maydonlar ochiq" ──▶ network ──┘
        │
        ▼
network: public_offers (holat, listing_version, ruxsat etilgan maydonlar)  + outbox
        │  network.public_offer.published|updated|withdrawn
        ▼
marketplace: qidiruv indeksi (read model) ──▶ global qidiruv, global AI, SEO, global Telegram bot
        │
        └── har javobdan oldin: NetworkQueryPort.get_current_offers(ids) — qaytarib olinganlar rad etiladi
```

| Domen | Sub-modullar | Nima qiladi |
|---|---|---|
| `network` (Stage 2) | `onboarding` (o'zi ro'yxatdan o'tish, M21), `integrations` (kassa/ERP, M22, M30), `canonical` (umumiy mahsulot va moslash, M23, M28), `offers` (ommaviy takliflar, M24), `trust` (tasdiqlangan shop belgisi, shikoyatlar, M29) | Shop rozilik bergan ma'lumotdan ommaviy proyeksiya quradi |
| `marketplace` (Stage 3) | `search` (qidiruv, filtr, xarita, M31–M33), `advisor` (global AI, M34), `referrals` (M35), `buyers` (saqlangan qidiruv, ogohlantirish, M36), `ranking` (oddiy va reklama, M37), `seo` (M38), `global_bot` (M39) | Faqat ommaviy ma'lumotni o'qiydi |

M25 (ko'p filialli ombor) — `commerce` ichida; M26 (tariflar) — `platform/billing`; M27 (AI bilim markazi) — `sales_ai`.

## 4. Qoidalar

1. **Standart holatda hammasi yopiq** (BL-079). Ommaviy taklif faqat ega aniq yoqqanda va faqat tanlangan maydonlar bilan.
2. **Proyeksiyaga hech qachon tushmaydi:** tannarx, marja, xaridor, suhbat, ichki izoh, aniq qoldiq soni (shop ruxsat bermasa — faqat "bor / kam / yo'q") (BL-081).
3. **`network` faqat event'lardan quradi.** `catalog`/`commerce` jadvaliga JOIN yo'q. Payload'da kerakli maydon bo'lmasa — `catalog`/`commerce` Query Port'idan **o'sha SKU uchun** o'qiladi (`CatalogQueryPort.get_public_projection(shop_id, sku_id)` — faqat ommaviy bo'lishi mumkin bo'lgan maydonlar).
4. **Qaytarib olish darhol** (BL-080): ega "yopish" bossa, `network.public_offers.status = WITHDRAWN` bitta tranzaksiyada + outbox. Indeks keyin tozalanadi, lekin `marketplace` har javobdan oldin `NetworkQueryPort` orqali joriy holatni tekshiradi — **read-time deny**. Indeks kechikishi taklifni qayta ko'rsatmaydi.
5. **Eski yangilanish yangisini bosmaydi** (BL-085): har taklifda monoton `listing_version`; indeks faqat kattaroq versiyani qabul qiladi.
6. **Shubhada birlashtirilmaydi** (BL-076…078): aniq identifikator yoki odam tekshiruvi; har bog'lash tarixi bilan, bekor qilinadi.
7. **Shop yopilsa yoki to'xtatilsa** (`platform.shop.suspended`, BL-070) — barcha takliflari darhol `WITHDRAWN`.
8. **Global AI ≠ shop AI** (BL-097, BL-098, BL-108): `marketplace/advisor` faqat ommaviy indeks va `NetworkQueryPort` bilan ishlaydi; `sales_ai` tool'lari va shop ma'lumotlari unga ochiq emas. Global Telegram bot — alohida principal.
9. **Kassa/ERP qoldig'i** (BR-X12): `network/integrations` `commerce` jadvaliga yozmaydi — `network.pos_stock.received` event'ini chiqaradi; `commerce` maydon ustuvorligi (BL-073) bo'yicha qo'llaydi yoki nizo sifatida odamga beradi (TC-019).
10. **Yo'naltirish** (BL-100, BL-101): xaridor roziligidan keyin `marketplace.referral.consented` → `commerce` lead yaratadi (minimal ma'lumot bilan).

## 5. Moslash (canonical matching)

```
Shop SKU ommaviy qilindi ──▶ brend / MPN / GTIN normallashtiriladi
   ──▶ qat'iy atributlar: hajm, holat, avlod, Ti/oddiy
   ──▶ aniq identifikator bormi?
         ├─ Ha ──▶ nomzod umumiy mahsulot
         └─ Yo'q ──▶ FTS/trigram (+ keyin embedding) bilan nomzodlar ──▶ nomzod
   ──▶ cheklov filtri + qayta saralash
   ──▶ ishonch yuqori va nizo yo'q?
         ├─ Ha ──▶ vaqtinchalik bog'lash + manba ──▶ ommaviy taklif proyeksiyasi
         └─ Yo'q / nizo ──▶ odam tekshiruvi; bog'lanmagan holda qoladi
```

**Qat'iy taqiqlar:** model suffiksi farqi (Ti), 8GB va 16GB, yangi va ishlatilgan/qayta tiklangan, to'plam va yakka, kit soni, kafolat shartlari farqi. Noto'g'ri birlashtirish xavfi qamrovdan muhimroq.

Stage 1 dagi `catalog.reference_hardware_specs` (DEC-011) — umumiy mahsulotlar uchun boshlang'ich manba: `network/canonical` uni `CatalogQueryPort.list_reference_specs()` orqali o'qiydi (spec kutubxonasining egasi `catalog` bo'lib qoladi yoki Stage 2 da `network` ga ko'chiriladi — alohida ADR).

## 6. Ommaviy taklif tarkibi

```json
{
  "offer_id": "…", "shop_id": "…", "sku_id": "…", "canonical_id": "…",
  "listing_version": 17, "status": "ACTIVE",
  "price": {"amount_minor": 384000000, "currency": "UZS", "price_version_id": "…"},
  "condition": "NEW", "warranty_months": 12,
  "branch": {"branch_id": "…", "city": "Toshkent", "lat": 41.31, "lon": 69.28},
  "availability": "IN_STOCK",
  "last_verified_at": "2026-10-22T09:10:00Z",
  "permitted_fields": ["price", "condition", "warranty", "branch", "availability"]
}
```

## 7. Qidiruv oqimi (Stage 3)

```
Xaridor ──(qidiruv: byudjet, joylashuv)──▶ marketplace/search
   ──▶ indeks: matn + atributlar ──▶ nomzod umumiy mahsulotlar va takliflar
   ──▶ NetworkQueryPort.get_current_offers(ids) ──▶ qaytarib olinganlar, eskirganlar chiqarib tashlanadi
   ──▶ narx, kafolat, holat, joy, yangilangan vaqt
   ──▶ (ixtiyoriy) marketplace/advisor: faqat shu faktlar bilan izoh va saralash, har da'vo taklifga havola bilan
   ──▶ xaridorga: shaffof solishtirish
```

## 8. Saralash va oshkoralik

- Oddiy tartib: matn va atribut mosligi, aniq moslik ishonchi, mavjudlik yangiligi, masofa (ruxsat bo'lsa, BL-095, BL-096), kafolat, shop ishonchliligi — mezonlar ochiq e'lon qilinadi (BL-105).
- Reklama o'rinlari — alohida va aniq "Reklama" belgisi bilan; oddiy tartibga va AI tavsiyasiga ta'sir qilmaydi (BL-099, BL-104, TC-024).
- "Eng arzon" — faqat jami narx (yetkazish, xizmat haqi) ma'lum va solishtirsa bo'ladigan bo'lsa (BL-092, BL-093, TC-017). Valyuta va birliklar normallashtiriladi.
- Yopiq filialga ishora qiluvchi taklifda olib ketish ko'rsatilmaydi (TC-026).

## 9. Indeks, yangilik, texnologiya

- Stage 1: har shop ichida PostgreSQL FTS/trigram (`catalog`).
- Stage 2: moslash uchun pgvector — faqat benchmark sifatni oshirsa.
- Stage 3: alohida qidiruv servisi — faqat kechikish va hajm benchmark'idan keyin (ADR kerak).
- Indeks — `marketplace` read model'i, `network` event'laridan qayta quriladi; o'zgarishlar outbox orqali.
- Eskirgan taklif (BL-086): `last_verified_at` shop sozlamasidan eski bo'lsa — yashiriladi yoki "tekshirilmagan" belgisi; xaridor shopga o'tganda manba qayta tekshiriladi.

## 10. Xarita, SEO, global Telegram

- Filial koordinatalari faqat shop ruxsati bilan; PostGIS yoki litsenziyali geo servis; begona joylashuv ma'lumotlari yig'ilmaydi.
- SEO: umumiy mahsulot sahifalari, structured data (product/offer), canonical URL, takroriy sahifalar indeksga kirmaydi; qaytarib olingan takliflar sitemap'dan chiqariladi (BL-106, BL-107).
- Global Telegram bot — alohida xavfsizlik principal'i, faqat ommaviy qidiruv tool'lari.

## 11. Event'lar (Stage 2–3, taklif)

| Event | Kim chiqaradi | Kim tinglaydi |
|---|---|---|
| `network.public_offer.published` / `updated` / `withdrawn` | `network` | `marketplace` (indeks, SEO keshi) |
| `network.canonical_match.changed` | `network` | `marketplace` (qayta indekslash) |
| `network.pos_stock.received` | `network/integrations` | `commerce` (ustuvorlik bo'yicha qo'llash yoki nizo) |
| `marketplace.referral.consented` | `marketplace` | `commerce` (lead) |
| Tinglaydi: `catalog.product.*`, `catalog.price.changed`, `commerce.stock.changed`, `platform.shop.suspended` | — | `network` |

## 12. Sifat va kuzatuv

- Oltin to'plam: faol shoplardan 500–1000 ta tekshirilgan bir xil / bir xil emas SKU juftligi (Ti va oddiy, RAM kit hajmi, NVMe avlodi, holat).
- O'lchanadi: noto'g'ri birlashtirish aniqligi (qat'iy chegara — boshlang'ich o'lchovdan keyin), qamrov, taklif yangiligi, **qaytarib olingan taklif ko'rinishi (maqsad — nol)**, qidiruv p95, solishtirish CTR, noto'g'ri narx holatlari.
- Ishga tushirishdan oldin bog'lashni bekor qilish (split/merge rollback) mashqi.

## 13. Bosqich chegarasi

Stage 3 ommaga e'lon qilinmaydi, toki: yetarli shop qamrovi, tekshirilgan bir xil mahsulot solishtirishlari, rozilik, yangilik talablari, reklama oshkoraligi va yo'naltirish auditi tayyor bo'lmaguncha (`../business/10` §4).

## 14. Testlar (asosiylari)

| ID | Sinov | Natija |
|---|---|---|
| TC-015 | Shop taklifni qaytarib oldi, indeks hali yangilanmagan | Xaridorga darhol ko'rinmaydi (read-time deny) |
| TC-016 | RTX 5060 8GB va RTX 5060 Ti | Birlashtirilmaydi, odam ko'radi |
| TC-019 | Kassa eski qoldiqni yubordi | Ustidan yozilmaydi, nizo |
| TC-NET-01 | Ommaviy qilinmagan SKU | Proyeksiyada yo'q |
| TC-NET-02 | `listing_version` 5 dan keyin 4 keldi | Indeks 5 da qoladi |
| TC-NET-03 | Shop to'xtatildi | Barcha takliflari darhol yo'q |
| TC-NET-04 | import-linter | `network`, `marketplace` — `catalog`/`commerce` ni import qilmaydi |

## Keyingi qadam

→ [27-roadmap-and-tasks.md](27-roadmap-and-tasks.md) — `N1` / `G1` bo'laklari
→ [01-architecture-overview.md](01-architecture-overview.md) §9 — Stage 2–3 qanday qo'shiladi
