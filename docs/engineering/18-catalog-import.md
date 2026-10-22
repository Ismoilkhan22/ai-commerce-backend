# 18 — Katalog importi (CSV/XLSX)

> **Versiya:** v2 (2026-10-22). Eski `28_CATALOG_IMPORT_SPEC` o'rnini bosadi.
> **Domen:** `catalog` → sub-modul `imports`; qoldiq qismi — `commerce` (`inventory`).
> **Biznes:** M04, M05, M06, BL-011…015, BL-019, BL-022, DEC-011, DEC-107, DEC-121, `../business/13` (shopni ulash).
> **Kim o'qiydi:** backend, frontend (import oynasi), shopni ulaydigan jamoa.

## 1. Muammo

Import — pilotdagi birinchi va eng ko'p vaqt oladigan qadam. Shopning Excel ro'yxati tizimga to'g'ri tushmasa, AI ham, sayt ham noto'g'ri narx va qoldiq ko'rsatadi.

Ikkinchi muammo — arxitekturaviy: faylda **mahsulot va narx** (`catalog` domeni) ham, **qoldiq** (`commerce` domeni) ham bor. Bismuth qoidasi bo'yicha `catalog` `commerce` jadvaliga yoza olmaydi (00 §2, 4-qoida).

## 2. Yechim (qisqacha)

```
Fayl yuklash ──▶ Parse (stream) ──▶ Ustunlarni moslash ──▶ Sinov (dry-run, hech narsa yozilmaydi)
   ──▶ Ko'rib chiqish: yangi / yangilanadi / xato / spec bog'landi
   ──▶ Foydalanuvchi tasdiqlaydi ──▶ Commit (arq: catalog_import)
         ├─ catalog: mahsulot, SKU, narx versiyalari, spec bog'lash  [bitta TX + outbox]
         └─ qoldiq qatorlari catalog.import_stock_rows ga yoziladi (staging)
   ──▶ outbox [catalog.import.completed]
   ──▶ commerce subscriber: qoldiq qatorlarini CatalogQueryPort orqali o'qiydi
         ──▶ har qator: RECEIPT yoki ADJUSTMENT ledger yozuvi (idempotent, FOR UPDATE)
         ──▶ outbox [commerce.import_stock.applied]
   ──▶ catalog subscriber: import holatini yakunlaydi ──▶ Hisobot + xatolar CSV
```

### Nega qoldiq event orqali (va import endpoint'i `commerce` da emas)

| Variant | Afzallik | Kamchilik |
|---|---|---|
| **A ✅ Event:** `catalog` qoldiq qatorlarini staging jadvalga yozadi, `commerce` event bo'yicha qo'llaydi | Foydalanuvchi uchun bitta import oqimi; qoldiq faqat o'z egasi (`commerce`) tomonidan, ledger qoidalari bilan o'zgaradi; bismuth qoidasi istisnosiz | Import ikki bosqichda tugaydi (bir necha soniya); qoldiq qatori xatosi hisobotga kechroq tushadi |
| B: qoldiq ustunlari uchun alohida import endpoint'i `commerce` da | Sinxron | Foydalanuvchi bitta faylni ikki joyga yuklaydi yoki frontend ikki so'rovni muvofiqlashtiradi; mapping takrorlanadi |
| C: `catalog` `commerce` jadvaliga to'g'ridan-to'g'ri yozadi | Oddiy | 4-qoida buziladi — TAQIQ |

Tanlov — **A**. Qoldiqning yagona yozuvchisi `commerce` bo'lib qoladi (BL-019, BL-022).

## 3. Qoidalar

1. **Dry-run hech narsani yozmaydi** (BL-013). Commit faqat foydalanuvchi tasdig'idan keyin va faqat xatosiz yoki tanlangan qatorlar uchun.
2. Commit — arq vazifasi `catalog_import`; navbatga outbox orqali tushadi (ADR-033). API `202 Accepted` + `status_url` qaytaradi.
3. Katta fayl xotiraga to'liq yuklanmaydi — stream bilan o'qiladi, 500 qatorlik bo'laklarda yoziladi.
4. Bir shop uchun bir vaqtda bitta faol import (`409 IMPORT_ALREADY_RUNNING`).
5. Importda yo'q, lekin tizimda bor SKU'lar **o'chirilmaydi va arxivlanmaydi** — arxivlash alohida aniq amal.
6. Har commit `import_batches` yozuvi bilan; har o'zgargan SKU va ledger yozuvi audit'da `import_batch_id` bilan.
7. Narx o'zgarishi — yangi `price_version` (yuborilgan takliflarga ta'sir qilmaydi, BL-016).
8. Qoldiq hech qachon ustidan yozilmaydi — faqat ledger yozuvi (BL-022).

## 4. Fayl talablari

| Parametr | Qiymat |
|---|---|
| Formatlar | `.xlsx` (birinchi yoki tanlangan varaq), `.csv` (UTF-8; `;` yoki `,` avtomatik; Windows-1251 aniqlansa — ogohlantirish va konvertatsiya) |
| Hajm | ≤ 10 MB, ≤ 20 000 qator (pilot limiti, `billing` tarifida sozlanadi) |
| Sarlavha | Birinchi qator — ustun nomlari |
| Formulalar | XLSX'da formula natijasi o'qiladi; `=`, `+`, `-`, `@` bilan boshlanadigan matn — `UNSAFE_VALUE` (CSV injection) |
| Saqlash | Asl fayl `platform/storage` private bucket'da, 30 kun (`26`) |

## 5. Ustunlar

Ustun nomlari erkin — moslash bosqichida tanlanadi. Tizim keng tarqalgan nomlarni taklif qiladi (`Наименование`, `Nomi`, `Name` → `title`; `Цена`, `Narx` → `price`). Moslash shabloni shop uchun saqlanadi (`catalog.import_mappings`).

| Maydon | Majburiy | Turi / format | Tekshiruv | Egasi |
|---|---|---|---|---|
| `sku_code` | ✅ | matn, ≤ 64 | shop ichida yagona (BL-011); bo'sh joy kesiladi; solishtirish registrsiz | catalog |
| `title` | ✅ | matn, ≤ 200 | bo'sh emas | catalog |
| `category` | ✅ | `CPU`, `MOTHERBOARD`, `RAM`, `GPU`, `PSU`, `CASE`, `CPU_COOLER`, `STORAGE`, `MONITOR`, `PERIPHERAL`, `LAPTOP`, `ASSEMBLED_PC`, `OTHER` | sinonimlar lug'ati (`Видеокарта`, `Videokarta` → `GPU`) | catalog |
| `brand` | ✅ (PC qismlari) | matn | — | catalog |
| `model` | tavsiya | matn | spec bog'lash uchun | catalog |
| `mpn` | tavsiya | matn | spec bog'lashning eng ishonchli yo'li | catalog |
| `condition` | ❌ (`NEW`) | `NEW`, `USED`, `REFURBISHED`, `OPEN_BOX` | — | catalog |
| `price` | ✅ (saytga chiqarish uchun) | `1 250 000`, `1250000`, `1,250,000`, `1 250 000.50` | > 0; minor units (ADR-025) | catalog |
| `currency` | ❌ (shop valyutasi) | `UZS`, `USD` | USD bo'lsa kurs bormi (DEC-121) | catalog |
| `quantity` | ❌ | butun son ≥ 0 | §7 | **commerce** |
| `branch` | ❌ (asosiy filial) | filial nomi yoki kodi | `platform/shops` da bormi | **commerce** |
| `warranty_months` | ❌ | butun son ≥ 0 | buyurtma qatoriga snapshot (DEC-114) | catalog |
| `description` | ❌ | matn, ≤ 5000 | HTML tozalanadi | catalog |
| `image_urls` | ❌ | URL'lar, `;` bilan | §8 | catalog |
| `barcode` | ❌ | EAN/UPC | check digit | catalog |
| `is_published` | ❌ (`false`) | `ha/yo'q`, `1/0`, `true/false`, `да/нет` | saytga chiqarish talablari (BL-012) | catalog |

**Narx parsing:** mingliklar ajratgichi (bo'sh joy, vergul, nuqta) aniqlanadi; o'nlik qism faqat USD uchun; `so'm`, `сум`, `$` olib tashlanadi. Noaniq qiymat (`1.250` — 1250 yoki 1,25?) — xato, foydalanuvchi tuzatadi.

## 6. Mavjud SKU bilan to'qnashuv

Moslash bosqichida tanlanadi (`conflict_policy`):

| Siyosat | Natija |
|---|---|
| `CREATE_ONLY` | Faqat yangi `sku_code`; mavjudlari "o'tkazib yuborildi" |
| `UPDATE_EXISTING` (default) | Mavjud SKU yangilanadi: narx — yangi `price_version`; atributlar — versiya bilan |
| `UPDATE_PRICE_ONLY` | Faqat narx va valyuta |

## 7. Qoldiq miqdori (`commerce` tomoni)

**Dry-run paytida:** `catalog` `CommerceQueryPort.get_stock_levels(shop_id, sku_ids)` orqali joriy `on_hand`, `reserved`, `allocated` ni o'qiydi va ko'rib chiqishda farqni ko'rsatadi. Bu — faqat oldindan ko'rish; yakuniy tekshiruv `commerce` da.

**Commit'dan keyin (`commerce` subscriber `on_catalog_import_completed`):**
1. `CatalogQueryPort.get_import_stock_rows(shop_id, batch_id, cursor)` — 500 tadan o'qiladi.
2. Har qator alohida qisqa tranzaksiyada, `stock_balance` qatori `FOR UPDATE` bilan:
   - **Yangi SKU** (balans yo'q): `RECEIPT` ledger yozuvi, `reason = IMPORT_INITIAL`.
   - **Mavjud SKU:** farq hisoblanadi → `ADJUSTMENT`, `reason = IMPORT_SYNC`. Farq 0 bo'lsa — yozuv yo'q.
   - Yangi `on_hand` < `reserved + allocated` → qator xato `STOCK_BELOW_COMMITTED` (tasdiqlangan buyurtmalar bor), qoldiq o'zgarmaydi.
   - Farq shop sozlamasidagi chegaradan katta → tuzatish `PENDING_APPROVAL` holatida yaratiladi (`../business/04` §3, stok tuzatish), qoldiq tasdiqdan keyin o'zgaradi.
3. Idempotency kaliti: `import_stock:{batch_id}:{sku_id}:{branch_id}` — event qayta kelsa ikkinchi marta qo'llanmaydi.
4. Oxirida outbox `commerce.import_stock.applied` (payload: `batch_id`, `applied_count`, `failed_count`, `pending_approval_count`). Xato qatorlari `commerce.import_stock_results` da; hisobot uchun `CommerceQueryPort.get_import_stock_results(batch_id)`.
5. Har qo'llangan qator `commerce.stock.changed` event'ini chiqaradi (storefront keshi uchun) — bitta batch uchun SKU bo'yicha yig'ilgan holda.

## 8. Rasmlar

- URL bo'yicha yuklab olish — alohida arq vazifasi `catalog_image_fetch`, SSRF himoyasi bilan: faqat `https`, ichki va link-local IP manzillar taqiqlangan (DNS javobidan keyin ham tekshiriladi), ≤ 5 MB, faqat `image/jpeg|png|webp` (content sniff), redirect ≤ 3.
- Yuklab bo'lmasa — SKU baribir import qilinadi, rasm xatosi hisobotda.
- Rasmlar `platform/storage` orqali saqlanadi.
- ZIP arxiv bilan rasm yuklash — keyinroq.

## 9. Spec'ga avtomatik bog'lash (DEC-011)

PC qismlari kategoriyalarida har qator dry-run'da `catalog.reference_hardware_specs` bilan solishtiriladi (`17-pc-compatibility-engine.md` §4). Bu `catalog` ichida — domen ichidagi to'g'ridan-to'g'ri murojaat.

| Natija | Ko'rib chiqishda | Commit'dan keyin |
|---|---|---|
| MPN aniq mos | ✅ "Bog'landi (MPN)" | `sku_spec_links` (`AUTO_MPN`) |
| Model nomi aniq mos | ✅ "Bog'landi (model)" | `AUTO_MODEL` |
| Bir nechta nomzod | ⚠️ "Tanlang" — ro'yxat | tanlasa `MANUAL`, aks holda bog'lanmagan |
| Topilmadi | ⚠️ "Spec yo'q" | bog'lanmagan; "yangi model so'rovi" tugmasi |

Bog'lanmagan SKU sotilishi mumkin, lekin PC yig'mada `UNLINKED_PART` → `REVIEW_REQUIRED`.

## 10. Holatlar

```
UPLOADED ──(moslash saqlandi)──▶ MAPPED ──(dry-run)──▶ VALIDATING ──▶ VALIDATED
VALIDATED ──(commit, Idempotency-Key)──▶ COMMITTING ──(catalog qismi tugadi)──▶ STOCK_PENDING
STOCK_PENDING ──(commerce.import_stock.applied)──▶ COMPLETED
COMMITTING / STOCK_PENDING ──(xato)──▶ FAILED
VALIDATED ──(foydalanuvchi bekor qildi yoki 24 soat)──▶ EXPIRED
```
`quantity` ustuni bo'lmasa `COMMITTING → COMPLETED` (stok bosqichi yo'q). `state_machine.py` — `catalog/imports/`.

## 11. Xato hisoboti

Har qator: `CREATED`, `UPDATED`, `SKIPPED`, `ERROR`; qoldiq uchun alohida ustun: `STOCK_APPLIED`, `STOCK_PENDING_APPROVAL`, `STOCK_ERROR`. Xatolar CSV (asl ustunlar + `row_number`, `error_code`, `error_message` — foydalanuvchi tilida, `11-…` tarjimalari) yuklab olinadi, tuzatib qayta yuklash mumkin.

| `error_code` | Ma'nosi |
|---|---|
| `REQUIRED` | Majburiy maydon bo'sh |
| `INVALID_NUMBER` | Narx yoki miqdor son emas yoki noaniq |
| `INVALID_CHOICE` | Kategoriya, valyuta, holat tanilmadi |
| `DUPLICATE_IN_FILE` | Faylda bir xil `sku_code` ikki marta |
| `UNKNOWN_BRANCH` | Filial topilmadi |
| `NO_EXCHANGE_RATE` | USD narx, lekin kurs yo'q |
| `STOCK_BELOW_COMMITTED` | Yangi qoldiq band qilinganidan kam |
| `PUBLISH_REQUIREMENTS` | Saytga chiqarish uchun narx yoki majburiy atribut yetishmaydi |
| `UNSAFE_VALUE` | Formula injection belgisi |

Hisobot CSV'si ham xavfsiz eksport qilinadi (`'` prefiksi bilan).

## 12. Jadvallar (`catalog` schemasi)

| Jadval | Vazifasi |
|---|---|
| `import_batches` | `shop_id`, holat, fayl havolasi, `conflict_policy`, statistikalar, `created_by` |
| `import_mappings` | Shop uchun saqlangan ustun moslash shabloni |
| `import_rows` | Dry-run natijasi (qator raqami, normallashtirilgan qiymatlar, xato kodlari) — 30 kun |
| `import_stock_rows` | Staging: `shop_id`, `batch_id`, `sku_id`, `branch_id`, `quantity` — `commerce` uchun, 30 kun |

`commerce` schemasida: `import_stock_results` (`batch_id`, `sku_id`, `branch_id`, natija, xato kodi).

## 13. API (`shop` surface)

| Endpoint | Vazifasi | Ruxsat |
|---|---|---|
| `POST /api/v1/shop/catalog/imports` (multipart) | Fayl → `import_id`, aniqlangan ustunlar, moslash taklifi | `catalog.import.run` |
| `PUT /api/v1/shop/catalog/imports/{id}/mapping` | Moslash va `conflict_policy` | `catalog.import.run` |
| `POST /api/v1/shop/catalog/imports/{id}/dry-run` | `202`; natija — qator statistikasi, xatolar, spec bog'lash | `catalog.import.run` |
| `GET /api/v1/shop/catalog/imports/{id}` | Holat va ko'rib chiqish (cursor pagination) | `catalog.import.run` |
| `POST /api/v1/shop/catalog/imports/{id}/commit` | `Idempotency-Key`; tanlangan qatorlar; `202` | `catalog.import.commit` (+ `quantity` bo'lsa `commerce.stock.receive`) |
| `GET /api/v1/shop/catalog/imports/{id}/errors.csv` | Xato hisoboti | `catalog.import.run` |

Ruxsatlar `../business/04` ga mos: katalog xodimi, menejer va ega import qila oladi; `quantity` ustuni bilan commit — faqat ombor tuzatish huquqi borlarga (omborchi yoki menejer), aks holda qoldiq qismi o'tkazib yuboriladi va ogohlantiriladi.

## 14. Event'lar

| Event | Kim chiqaradi | Kim tinglaydi |
|---|---|---|
| `catalog.import.completed` | `catalog` (commit tugadi) | `commerce` (qoldiq qatorlari), `reporting` |
| `commerce.import_stock.applied` | `commerce` | `catalog` (import holatini yakunlaydi) |
| `catalog.product.published`, `catalog.price.changed` | `catalog` (har o'zgargan SKU, batch'da yig'ilgan) | `storefront`, `reporting` |
| `commerce.stock.changed` | `commerce` | `storefront`, `reporting` |

## 15. Kuzatuv

- `cos_catalog_import_rows_total{result}`, `cos_catalog_import_duration_seconds{phase=dry_run|commit|stock}`.
- Span: `catalog.import.dry_run`, `catalog.import.commit`, `commerce.import_stock.apply` — bitta `trace_id` (outbox orqali uzatiladi).

## 16. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-IMP-01 | 5000 qatorli XLSX | Xotira chegarasida; dry-run ≤ 60 s (pilot maqsad) |
| TC-IMP-02 | Bir xil commit ikki marta (bir xil `Idempotency-Key`) | Bitta natija |
| TC-IMP-03 | `quantity` band qilinganidan kam | Qator `STOCK_BELOW_COMMITTED`, boshqalari qo'llanadi |
| TC-IMP-04 | Narx `1.250` / `1,250` | Noaniq — xato; `1 250 000` — to'g'ri |
| TC-IMP-05 | `=HYPERLINK(...)` nomli mahsulot | `UNSAFE_VALUE`, eksportda ham xavfsiz |
| TC-IMP-06 | Rasm URL `http://169.254.169.254/` | Yuklanmaydi (SSRF) |
| TC-IMP-07 | `RTX 5060 Ti 16GB` MPN bilan | To'g'ri spec'ga bog'lanadi, `RTX 5060` ga emas |
| TC-IMP-08 | A shop importi B shop SKU'siga tegmaydi | Izolyatsiya (TC-ISO) |
| TC-IMP-09 | `catalog.import.completed` 3 marta keldi | Ledger yozuvlari bir marta |
| TC-IMP-10 | Import paytida operator shu SKU'ga buyurtma tasdiqladi | Qoldiq to'g'ri: ledger + band qilish izchil, manfiy emas |

## Keyingi qadam

→ [17-pc-compatibility-engine.md](17-pc-compatibility-engine.md) — spec kutubxonasi va bog'lash
→ [05-events-and-outbox.md](05-events-and-outbox.md) — event katalogi
