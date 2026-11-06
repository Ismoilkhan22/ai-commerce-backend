# 5c. Katalog importi (CSV/XLSX) — backend

> **Sana:** 2026-10-26. **Reja bandi:** S1-06 ([27](../27-roadmap-and-tasks.md)). **Batafsil qoidalar:** [18-catalog-import.md](../18-catalog-import.md), baza — [db/catalog_import.md](../db/catalog_import.md) (DEC-140, taklif).
> **Holat:** backend tayyor, `make check` yashil (575 test). Frontend — alohida agent (shu fayl oxirida "Frontend uchun").

## 1. Nima bitdi — qisqacha

Shop Excel yoki CSV prays-listini yuklaydi. Tizim ustunlarni o'zi taniydi, avval **sinov** qiladi (hech narsa yozilmaydi), qaysi qator yangi, qaysi yangilanadi, qaysi xato ekanini ko'rsatadi. Xodim tasdiqlagach, mahsulotlar **qoralama** bo'lib yoziladi, narx — yangi narx versiyasi, qoldiq — oddiy kirim yoki tuzatish hujjati.

```
Fayl (POST /shop/files?purpose=IMPORT_FILE) ──▶ import ochiladi (ustunlar + moslash taklifi)
   ──▶ moslash (ustun → maydon, siyosat) ──▶ SINOV (fonda, 1000 qatorlik bo'laklar)
   ──▶ ko'rib chiqish: yangi / yangilanadi (eski → yangi) / o'tkaziladi / xato + qoldiq "joriy → yangi"
   ──▶ tasdiq ──▶ YOZISH (fonda, 500 qatorlik bo'laklar): qoralama mahsulot, SKU, narx, kutubxonaga bog'lash
   ──▶ qoldiq qatorlari "kutish zali"ga ──▶ catalog.import.completed
   ──▶ commerce: kirim (yangi filial qoldig'i) yoki tuzatish (farq) ──▶ commerce.import_stock.applied
   ──▶ import TAYYOR + xodimga xabar + xatolar CSV'si
```

**Holatlar:**
```
UPLOADED ──(moslash)──▶ MAPPED ──(sinov)──▶ VALIDATING ──▶ VALIDATED ──(qayta moslash)──▶ MAPPED
VALIDATED ──(tasdiq)──▶ COMMITTING ──▶ STOCK_PENDING ──(commerce qo'lladi)──▶ COMPLETED
COMMITTING ──(qoldiq yo'q)──▶ COMPLETED
VALIDATING / COMMITTING / STOCK_PENDING ──(xato)──▶ FAILED
UPLOADED / MAPPED / VALIDATED ──(xodim bekor qildi)──▶ CANCELLED
VALIDATED ──(24 soat tasdiqlanmadi)──▶ EXPIRED
```

## 2. Rejadagi bandlar

- [x] CSV (UTF-8, BOM, Windows-1251 — ogohlantirish bilan; `;` `,` tab avtomatik) va XLSX (faqat qiymatlar, tashqi havolasiz).
- [x] Hajm ≤ 10 MB, ≤ 20 000 qator; zip-bomba va makrosli fayl rad etiladi.
- [x] Ustunlarni avtomatik tanish (uz/ru/en nomlari) va shop uchun saqlangan shablon.
- [x] Sinov fonda, hech narsa yozilmaydi (BL-013); qatorlar: CREATE / UPDATE / SKIP / ERROR, maydon bo'yicha xato kodlari.
- [x] Faylda takror artikul — `DUPLICATE_IN_FILE`; formula belgisi — `UNSAFE_VALUE`; noaniq narx `1.250` — `AMBIGUOUS_NUMBER`.
- [x] Kutubxonaga bog'lash ko'rinishi (MPN / model / bir nechta nomzod / topilmadi) — 2-moduldagi ehtiyotkor qoidalar bilan.
- [x] Tasdiq — `Idempotency-Key` bilan; yozish bo'laklab, to'xtagan joydan davom etadi; mahsulot doim qoralama.
- [x] Narx o'zgarsa — yangi narx versiyasi (BL-016); bir xil narx — versiya yozilmaydi.
- [x] Qoldiq — commerce o'zi, kirim va tuzatish hujjatlari bilan (DEC-140, 1-qaror); omborchi importida farq tasdiqqa (2-qaror).
- [x] Shopda bitta faol import (`409 IMPORT_ALREADY_RUNNING`); sinov 24 soatda eskiradi; 30 kundan eski qatorlar tozalanadi.
- [x] Xatolar CSV'si — yopiq fayl, imzoli havola; har katak formula sifatida o'qilmaydi (`'` prefiksi).
- [x] Xabarnoma (sinov tayyor / import tugadi / to'xtadi) va realtime signal `import.changed`.
- [x] RLS (FORCE) — beshala yangi jadvalda.

**Ataylab keyinga qoldirildi:**
- **Rasm havolalarini yuklab olish** (18 §8, SSRF himoyasi bilan) — havolalar `row_values.image_urls` da saqlanadi, yuklash keyingi bosqichda. Sabab: tashqi tarmoq chaqiruvi va SSRF himoyasi alohida ish; pilotda rasmlar qo'lda qo'shiladi.
- **`is_published` ustuni** e'tiborsiz — importdan mahsulot hech qachon saytga avtomatik chiqmaydi (topshiriq qoidasi).
- **Dev seed'da namuna import** qilinmadi — seed fon bosqichlarisiz ishlaydi, foydasi kam.
- **Bekor qilingan yozish (rollback)** yo'q — yozish idempotent: xato qatorlarni tuzatib, faylni qayta yuklash yetarli (mavjud SKU'lar endi UPDATE yoki SKIP bo'ladi).

## 3. Fayllar xaritasi

```
app/domains/catalog/imports/
├── models/orm.py              import_batches, import_mappings, import_rows, import_stock_rows
├── parsing.py                 fayl o'qish (CSV/XLSX), zip tekshiruvi, ustun lug'ati, qiymatlarni tozalash
├── state_machine.py           holatlar (15 strelka)
├── schemas.py                 API kontrakti
├── services/planning.py       qator rejasi: yangi / yangilanadi / o'tkaziladi / xato (sinov va yozish uchun bir xil)
├── services/import_service.py yuklash, moslash, sinov, ko'rib chiqish, tasdiq, bekor, hisobot, fon bo'laklari
├── subscribers.py             catalog.import.chunk, commerce.import_stock.applied, rejali ish
└── api/routes.py              /shop/catalog/imports/*
app/domains/catalog/query_port.py          + ImportStockSourceImpl (commerce staging'ni shu orqali o'qiydi)
app/domains/catalog/products/services/product_service.py   + import_create, import_update
app/domains/catalog/pc_specs/services/link_service.py      + preview_match (sinovda bog'lash ko'rinishi)
app/domains/commerce/inventory/services/import_stock.py    qoldiqni qo'llash (kirim / tuzatish, bo'laklab)
app/domains/commerce/inventory/import_subscriber.py        catalog.import.completed, commerce.import_stock.continue
app/domains/commerce/query_port.py                         + ImportStockResultsImpl (natija va joriy qoldiq)
app/shared/contracts/imports.py            ImportStockSource / ImportStockResults portlari
app/platform/staff/services/actors.py      fon vazifasi xodim nomidan (ruxsatlar bazadan)
app/platform/storage/services/file_service.py  + IMPORT_FILE (XLSX/CSV, 10 MB), store_document (EXPORT_FILE)
app/db/migrations/catalog/versions/catalog_0005_import_tables.py
app/db/migrations/commerce/versions/commerce_0005_import_stock.py
tests/unit/test_catalog_import_parsing.py          19 test
tests/integration/test_catalog_import.py           4 katta test (to'liq oqim)
```

## 4. Qaysi faylda nima bor

### 4.1 `parsing.py` — bazasiz

- `read_table` — tur fayl ichidan: ZIP + `xl/workbook.xml` — XLSX, aks holda matn — CSV. Sarlavha, qatorlar soni, ogohlantirishlar. Limitlar shu yerda.
- `_check_zip` — openpyxl'dan oldin: bo'laklar soni, ochilgandagi umumiy hajm (≤ 150 MB), siqish nisbati (≤ 200×), `vbaProject.bin` (makros).
- `iter_data_rows` — bo'lak oynasi (offset, limit): fayl har bo'lakda qayta o'qiladi, xotiraga to'liq olinmaydi.
- `suggest_mapping` — saqlangan shablon (sarlavha nomi bo'yicha) birinchi, keyin uz/ru/en lug'ati.
- `normalize_row` — har maydon: matn (ko'rinmas belgilar olib tashlanadi, formula belgisi — xato), narx, butun son, valyuta, holat, xususiyatlar (`xotira: 16; rang = qora`), shtrix-kod, rasm havolalari. Asl qiymatlar `raw` da — xatolar CSV'si uchun.
- `parse_price` — mingliklar ajratgichi aniqlanadi; bitta ajratgich + 3 raqam (`1.250`) — noaniq; `0.5` — o'nlik.
- `csv_safe` — eksport katagi `=`, `+`, `-`, `@`, tab bilan boshlansa — `'` prefiksi.

### 4.2 `services/planning.py`

- `load_context` — bo'lak uchun bir marta: faol toifalar va sinonimlar, xodim doirasidagi ochiq filiallar, kurs bormi, fayldagi artikullar bo'yicha mavjud SKU + joriy narx.
- `plan_row` — siyosat bo'yicha reja. Yozishda reja **qayta** tuziladi: sinovdan keyin SKU paydo bo'lgan yoki narx o'zgargan bo'lsa ham to'g'ri ishlaydi. Bo'sh katak mavjud qiymatni o'chirmaydi.

### 4.3 `services/import_service.py`

- `create` — `IMPORT_FILE` faylini o'qiydi, import ochadi; bitta filialli shopda u standart filial.
- `set_mapping` — ustun indekslari, majburiy maydonlar siyosatga qarab, ombor huquqi; ogohlantirishlar `STOCK_SKIPPED_NO_PERMISSION`, `STOCK_REQUIRES_APPROVAL`; `save_as` — shablon.
- `start_dry_run`, `commit` — holat va birinchi bo'lak event'i bitta tranzaksiyada (outbox). Faol import unikal indeks bilan himoyalangan.
- `run_chunk` — bo'lak: nazorat nuqtasi `processed_rows` mos kelmasa — o'tkazib yuboradi (takror). Kutilmagan xato — `FAILED` + xabar.
- `_apply_row` — har qator SAVEPOINT ichida: xato bo'lakni buzmaydi. Har o'zgargan SKU auditda `catalog.import.row_applied` (`import_batch_id` bilan).
- `errors_report` — xato qatorlari CSV'si (BOM bilan, Excel uchun), xato izohi foydalanuvchi tilida.
- `maintain` — rejali ish: 24 soatlik sinov `EXPIRED`, 10 daqiqa jim bo'lgan bo'lak qayta qo'yiladi, 30 kunlik tozalash.

### 4.4 `commerce/inventory/services/import_stock.py`

- Qatorlar `(filial, SKU)` tartibida, 300 tadan. Filialda qoldiq qatori yo'q — kirim (100 qatordan); bor — farq bo'lsa tuzatish `StockService.create_adjustment` orqali, shuning uchun omborchi importi o'zi tasdiqqa tushadi (vazifa va xabar bilan).
- Yangi qoldiq band qilinganidan kam — `STOCK_BELOW_COMMITTED`; arxivdagi mahsulot — `PRODUCT_NOT_AVAILABLE`; yopiq filial — `BRANCH_CLOSED`; doiradan tashqari — `OUT_OF_SCOPE`.
- `import_stock_results` asosiy kaliti — takror event qatorni qayta qo'llamaydi (TC-IMP-09).

## 5. Testlar

`make check`: **575 passed** (oldin 552), ruff, mypy strict, import-linter toza.

- **Unit (19):** narx formatlari (12 holat), CSV BOM va `;`, Windows-1251, XLSX oyna, makros va zip-bomba, limitlar va bo'sh fayl, formula belgisi va tozalash, toifa sinonimlari va `csv_safe`.
- **Integratsiya (4):**
  - to'liq oqim: 8 qatorli CSV — CREATE, UPDATE (narx eski → yangi, qoldiq 5 → 8), 6 xil xato; sinov hech narsa yozmaydi; tasdiq va takroriy tasdiq (bir xil kalit) — bitta natija; mahsulot qoralama, narx yangi versiya, kirim va tuzatish; takroriy `catalog.import.completed` — qoldiq ikki marta o'zgarmaydi; xatolar CSV'sida `'=HYPERLINK`;
  - omborchi: katalog siyosati rad, `STOCK_ONLY` + `STOCK_REQUIRES_APPROVAL`; farq — tasdiq kutadi, yangi filial — kirim;
  - XLSX, bitta faol import (409), bekor qilish (`CANCELLED`), 24 soatlik eskirish, eskirgandan keyin tasdiq — 409;
  - shoplar izolyatsiyasi (404), boshqa shop fayli (422), SALES — 403, ikkilik fayl — 415, o'qib bo'lmaydigan fayl — `IMPORT_FILE_INVALID`, shablon.

## 6. Jarayonda topilgan muammolar

- **Kirim hujjatini keyin o'zgartirib bo'lmaydi** (jadval faqat qo'shiladi) — `import_batch_id` hujjat yaratilayotganda beriladi (`create_receipt` / `create_adjustment` ga ixtiyoriy parametr).
- **Bitta SKU bir necha filialda** qoldiq importida "takror" deb belgilanardi — qoldiq importida takror kaliti artikul + filial.
- **Bitta filialga bir nechta kirim** — bo'lak va 100 qatorlik chegara tufayli; shuning uchun `(import, filial)` kirim indeksi unikal emas, takror himoyasi natija jadvalida.

## 7. Keyingi modulga meros

- Fon bosqichini bo'laklab bajarish namunasi: holat + nazorat nuqtasi + keyingi bo'lak event'i (outbox) + rejali ish jim qolganini qayta qo'yadi.
- `staff_actor` — fon vazifasi xodim nomidan ishlashi kerak bo'lsa (ruxsatlar bazadan).
- Domenlar orasida ma'lumot almashish — faqat `app/shared/contracts` portlari (bu yerda `ImportStockSource` / `ImportStockResults`).

## 8. Founder ko'rib chiqishi uchun qarorlar

DEC-140 dagi 4 qarorga qo'shimcha (kod shu bo'yicha, o'zgarsa moslanadi):

1. **Yangi siyosat `STOCK_ONLY` (omborchi importi).** Omborchi faqat mavjud SKU qoldig'ini import qiladi, katalogga tegmaydi. Muqobil: omborchiga import umuman yo'q.
2. **Bitta qator — bitta mahsulot + bitta SKU.** Bir mahsulotning bir nechta variantini fayldan guruhlash yo'q. Muqobil: "nom bo'yicha guruhlash" — xato guruhlash xavfi bor.
3. **Bo'sh katak mavjud qiymatni o'chirmaydi** (yangilashda). Muqobil: bo'sh — tozalash; xavfli, prays-listlarda ustunlar ko'pincha bo'sh.
4. **Faylda takror artikul — barcha qatorlari xato** (qoldiq importida artikul + filial). Muqobil: oxirgisi g'olib.
5. **Dollar narxi, shop kursi yo'q — qator xato** (18 §11 `NO_EXCHANGE_RATE`). Muqobil: narx yoziladi, faqat saytga chiqarish to'xtaydi.
6. **UZS narxida tiyin ruxsat** (2 xonagacha) — katalog qoidasi bilan bir xil. 18 §5 "o'nlik faqat USD" deydi.
7. **Noaniq son alohida kod `AMBIGUOUS_NUMBER`** (18 §11 da `INVALID_NUMBER` ichida edi) — UI aniqroq tushuntiradi.
8. **Bekor qilish — `CANCELLED`, 24 soat — `EXPIRED`** (DBML'da ikkalasi `EXPIRED` edi) — frontend talabi.
9. **Fon bosqichi kutilmagan xatoda `FAILED`** (qayta urinmasdan); qayta urinish — faylni yana yuklash (yozish idempotent).
10. **Import xabarnomasi — faqat xabar, vazifa emas** ("sinov tayyor", "tugadi", "to'xtadi").

## Frontend uchun

- **Yuklash:** `POST /shop/files?purpose=IMPORT_FILE&filename=…` (tana — fayl baytlari, `Idempotency-Key`) → `POST /shop/catalog/imports {file_id}` (201, `Idempotency-Key`). O'qib bo'lmasa — 422 `IMPORT_FILE_INVALID`, `details.reason`: `EMPTY`, `NO_HEADER`, `NOT_TABLE`, `MACRO`, `ZIP_BOMB`, `TOO_MANY_ROWS`.
- **O'qish:** `GET /shop/catalog/imports` (oxirgi 20, `created_by_name` bilan), `GET .../{id}` (ETag), `GET .../{id}/rows?action=&errors_only=&cursor=&limit=`, `GET .../mappings`, `GET .../template?format=xlsx|csv`.
- **Moslash:** `PUT .../{id}/mapping` (`If-Match`) — `{mapping: {maydon: ustun_indeksi}, conflict_policy, default_branch_id?, save_as?}`. Siyosatlar: `UPDATE_EXISTING` (standart), `CREATE_ONLY`, `UPDATE_PRICE_ONLY`, `STOCK_ONLY` (omborchi faqat shu).
- **Sinov:** `POST .../{id}/dry-run` (`If-Match`, 202) → `import.changed` signali → `VALIDATED`.
- **Ko'rib chiqish:** qatorda `action`, `errors[{field, code}]`, `values`, `changes` (`fields: {nom: {old, new}}`, `price: {old, old_currency, new, currency}`), `stock` (`{branch_id, current, new}`), `spec_match`, `selected`. `PATCH .../{id}/rows/{row_number} {selected?, spec_id?}` — faqat `VALIDATED` da.
- **Tasdiq va bekor:** `POST .../{id}/commit` (`If-Match` + `Idempotency-Key`, 202), `POST .../{id}/cancel` (`If-Match`).
- **Hisobot:** `POST .../{id}/error-report` → `{file_id, url, url_expires_at, rows}` (imzoli havola 5 daqiqa).
- **Ogohlantirishlar:** `CSV_CP1251`, `STOCK_SKIPPED_NO_PERMISSION`, `STOCK_REQUIRES_APPROVAL`.
- **Yangi kodlar:** `IMPORT_ALREADY_RUNNING` (409); qator kodlari: `REQUIRED`, `INVALID_NUMBER`, `AMBIGUOUS_NUMBER`, `INVALID_CHOICE`, `INVALID_FORMAT`, `TOO_LONG`, `UNSAFE_VALUE`, `DUPLICATE_IN_FILE`, `UNKNOWN_BRANCH`, `NO_EXCHANGE_RATE`, `NOT_FOUND`, `ARCHIVED`; qoldiq: `STOCK_BELOW_COMMITTED`, `PRODUCT_NOT_AVAILABLE`, `BRANCH_CLOSED`, `OUT_OF_SCOPE`, `IMPORTER_INACTIVE`.
- **Ruxsat:** `catalog.import.run` — ega, menejer, omborchi (omborchi faqat `STOCK_ONLY` va `commerce.stock.receive` bilan).

## 9. Frontend (2026-10-26)

### 9.1 Nima bitdi — qisqacha

Shop panelida Katalog → **Import** tabi. Ega va menejer prays-listni yuklaydi, omborchi faqat qoldiqni (`STOCK_ONLY`).

```
/catalog/import: fayl (sudrab tashlash yoki tanlash, XLSX/CSV, 10 MB) ──▶ /catalog/import/{id}
   UPLOADED / MAPPED ──▶ ustunlarni moslash (taklif serverdan, saqlangan shablon sarlavha nomi bo'yicha) ──▶ "Sinovni boshlash"
   VALIDATING ──▶ progress (realtime `import.changed` + 2 s so'rov)
   VALIDATED ──▶ ko'rib chiqish: yangi / yangilanadi / o'zgarmaydi / xato kartochkalari, qatorlar (narx eski → yangi, qoldiq joriy → yangi),
                 qatorni yozishdan chiqarish, xatolar CSV'si, ustunlarni qayta moslash, bekor qilish ──▶ "Katalogga yozish"
   COMMITTING / STOCK_PENDING ──▶ progress
   COMPLETED ──▶ natija + havolalar: qoralamalar, tasdiq kutayotgan tuzatishlar, kirimlar
   FAILED / EXPIRED / CANCELLED ──▶ sabab + "Yangi import"
```

### 9.2 Fayllar xaritasi

```
apps/shop-dashboard/src/
├── lib/imports.ts                         turlar (OpenAPI'dan), holatlar, ruxsatlar, API chaqiruvlari
├── app/[shop]/catalog/import/page.tsx     yuklash, faol import ogohlantirishi, tarix
├── app/[shop]/catalog/import/[id]/page.tsx  holatga qarab bosqich
└── components/catalog/import/
    ├── common.tsx         kim nima qila oladi, holat belgisi, bosqichlar
    ├── upload-card.tsx    fayl yuklash, server namunasi (XLSX/CSV), o'qib bo'lmaydigan fayl sababi
    ├── mapping-step.tsx   ustun → maydon, siyosat, standart filial, shablon saqlash
    ├── progress-card.tsx  progress, bekor qilish
    ├── review-step.tsx    sinov natijasi, qatorlar, chiqarish, xatolar CSV'si, tasdiq
    ├── result-card.tsx    yakuniy natija va havolalar
    └── history-list.tsx   importlar tarixi
e2e/catalog-import.spec.ts                 2 ta test
```

### 9.3 Muhim qarorlar

- **Ruxsat:** tab `catalog.import.run` bilan. `catalog.product.edit` yo'q bo'lsa (omborchi) — faqat `STOCK_ONLY`: siyosat tanlovi ko'rinmaydi, maydonlar SKU, miqdor, filial.
- **Majburiy maydonlar siyosatga qarab** (forma darajasida): katalog — SKU, nom, toifa; faqat narx — SKU, narx; faqat qoldiq — SKU, miqdor. Yakuniy tekshiruv — serverda.
- **Qatorni chiqarish serverda saqlanadi** (`PATCH rows/{n}`), sahifa yangilansa ham qoladi.
- **`MAPPED` holati moslash ekraniga qaytadi** (sinovni boshlash so'rovi o'tmagan bo'lsa ham foydalanuvchi qotib qolmaydi).
- **Namuna fayl serverdan** (`/template?format=xlsx|csv`) — ustun nomlari server taniydigan ko'rinishda.
- **O'qib bo'lmaydigan fayl** sababi (`EMPTY`, `NO_HEADER`, `NOT_TABLE`, `MACRO`, `ZIP_BOMB`, `TOO_MANY_ROWS`) yuklash maydoni ostida, toast emas.
- **Katalog ro'yxati `?status=DRAFT` ni o'qiydi** — natijadagi "qoralamalarni ko'rish" havolasi shu tabni ochadi.

### 9.4 Tekshiruv

- `pnpm check` toza.
- `e2e/catalog-import.spec.ts` — 2/2:
  - ega: CSV (mavjud SKU yangilanadi, yangi SKU, xato qator) → moslash avtomatik → sinov: 1/1/1, narx va qoldiq "5 → 8" ko'rinadi, hali hech narsa yozilmagan → yozish → yangi mahsulot qoralama, qoldiq 8, kirim bor → qayta tasdiq 409, mahsulot ikkilanmaydi → tarixda;
  - omborchi (390px): `STOCK_ONLY`, siyosat tanlovi yo'q, tasdiq ogohlantirishi, "5 → 2" → yozish → qoldiq o'zgarmagan, tuzatish `PENDING`; gorizontal aylantirish yo'q.
- To'liq e2e: 21/23. Ikkala yiqilgan test — `messaging.spec.ts`, sabab backend: e2e muhitida `POST /shop/channels/webchat` 500 qaytaradi (import bilan bog'liq emas).

### 9.5 Ochiq qolganlar

- Ko'rib chiqishda "bir nechta mos model"dan kutubxona modelini tanlash (`PATCH rows/{n} {spec_id}`) — backend tayyor, UI hali yo'q.
- `errors_only` filtri ishlatilmagan (xato tabi `action=ERROR` bilan).

## 10. QA tekshiruvi va tuzatishlar (2026-10-26)

Mustaqil QA importni buzishga urindi: 3 ta jiddiy, 4 ta o'rtacha, 11 ta kichik topilma va bitta bir marta ko'ringan holat (O1). Hammasi tuzatildi, har biriga test yozildi.

### 10.1 Jiddiy topilmalar

- **F1 — kichik fayl butun API'ni ~20 soniya qotirardi (DoS).** Fayl endi so'rov ichida o'qilmaydi.
  - Yuklashda faqat arzon tekshiruv (`parsing.precheck`, alohida thread'da): ZIP katalogi, makros, siqish nisbati, varaq o'lchami `<dimension>` (20 001 qatordan ko'p — darhol `TOO_MANY_ROWS`), sharedStrings hajmi (30 MB) va satrlar soni (300 000), varaq XML hajmi (100 MB), CSV kodlashi va "sarlavha + kamida bitta qator".
  - Import `PARSING` holatida ochiladi (yangi holat, `catalog_0006`). Worker faylni BIR marta, alohida thread'da, 60 soniyalik chegara bilan o'qiydi; `iter_rows(max_row, max_col)` — bo'sh qatorlar va ustunlar to'ldirilmaydi.
  - O'qilgan qatorlar yangi `catalog.import_source_rows` jadvaliga yoziladi; sinov bo'laklari faylni qayta ochmaydi, shu jadvaldan o'qiydi.
  - 2 KB'lik "o'lcham bombasi" endi < 1 soniyada 422 bilan rad etiladi; o'lchamsiz varaqdagi 1 048 576-qator o'qishni to'xtatmaydi.
- **F2 — `1,000` miqdor 1 bo'lib yozilardi.** Miqdor va kafolat narx bilan bir xil qoida: `1,000` / `2.000` — `AMBIGUOUS_NUMBER`, `10.5` — `INVALID_NUMBER`, `1 000` (bo'shliq) — 1000, `10.0` — 10.
- **F3 — omborchi bir faylni ikki marta import qilsa tuzatishlar ustma-ust tushardi.** Import tuzatishida fayldagi ABSOLYUT qoldiq saqlanadi (`stock_adjustments.target_on_hand`, `commerce_0006`); farq tasdiq paytida joriy qoldiqdan hisoblanadi. Shu SKU+filial uchun yangi import eski kutilayotgan import tuzatishini rad etadi. Tasdiqlovchi "maqsad X (hozir Y)" ni ko'radi.

### 10.2 O'rtacha topilmalar

- **F4 —** xatolar CSV'sida sarlavha qatori ham formula prefiksi bilan (`'`).
- **F5 —** import yozuvi `NOWAIT` bilan qulflanadi: fon bosqichi yangilayotgan paytda bekor qilish/moslash darhol `409 IMPORT_BUSY` (yangi kod), 5 soniyalik kutish va 500 yo'q. Worker bo'lak davomida yozuvni qulflamaydi — bitta bo'lakni bitta worker bajarishini advisory lock ta'minlaydi.
- **F6 —** buzilgan kursor (bool, int4 dan tashqari) va `row_number` (1…20 001 dan tashqari) — 422.
- **F7 —** ko'rib chiqishda qo'lda tanlangan kutubxona modeli (har qanday qatorda) yozishda MANUAL bog'lanish yaratadi.

### 10.3 Kichik topilmalar

- **F8 —** qatorning qoldiq natijasi (SKU, filial) bo'yicha — ko'rib chiqishda ham, xatolar CSV'sida ham.
- **F9 —** qoldiq o'zgarmagan, katalog ham o'zgarmagan qator — sinovda `SKIP`, yozishda `SKIPPED`.
- **F10 —** sinov band qilingan qoldiqni o'qiydi: miqdor band qilinganidan kam — qator xatosi `STOCK_BELOW_COMMITTED`.
- **F11 —** narxdagi belgi va valyuta ustuni zid (`$250` + `UZS`) — `CURRENCY_CONFLICT`.
- **F12 —** asl qiymatlar ustun indeksi bo'yicha saqlanadi: bir xil nomli ikki ustun ham hisobotda.
- **F13 —** moslash taklifi — sarlavhalari eng ko'p mos kelgan shablon (oxirgisi emas); `PUT …/mapping` da `mapping_id` — saqlangan shablonni shu faylga qo'llash.
- **F14 —** faqat `\r` bilan tugaydigan CSV o'qiladi.
- **F15 —** XLSX'da birinchi KO'RINADIGAN varaq.
- **F16 —** import egasi o'chirilgan bo'lsa, `FAILED` xabari ega va menejerlarga; `error_code` — mahsulot kodi (`IMPORT_FAILED`, `TIMEOUT` …), drayver ichki nomi emas.
- **F17 —** BOM'li UTF-16 (Excel "Unicode text") qabul qilinadi; BOM'siz — `UNSUPPORTED_ENCODING`.
- **F18 —** xatolar CSV'si sarlavhalari va izohlari `app/shared/i18n/locales` da (`import.report.*`, `import.row_errors.*`, `import.file_reasons.*`), import qilgan xodim tilida.
- **O1 —** dublikatlarni belgilash ikki qadam: oyna funksiyasi bilan raqamlar topiladi, keyin asosiy kalit bo'yicha yangilanadi. Statistikasi yo'q yangi jadvalda 20 000 qator — < 3 soniya (eski so'rov 5 soniyalik chegaradan oshgan edi).

### 10.4 Qarorlar (founder ko'rib chiqadi)

- Miqdor/kafolatda `10.0` — 10 (kasr nol va 3 xonali emas); `1,000` doim noaniq.
- Import tuzatishi maqsadda bo'lsa (farq 0) — tasdiq daftarga yozuvsiz yopiladi.
- `PARSING` faol importlar sanog'iga kirmaydi: o'qish paytida boshqa importni ham yuklash mumkin; sinov va yozish baribir bittadan.
- 20 001-qatordan keyingi qatorlar o'qilmaydi; Excel `<dimension>` yozganda bunday fayl yuklashda rad etiladi.
- Varaq tanlash interfeysi qo'shilmadi — birinchi ko'rinadigan varaq; kerak bo'lsa keyin.

### 10.5 Migratsiyalar va testlar

- `catalog_0006_import_parsing`: `PARSING` holati, `import_source_rows` (RLS FORCE).
- `commerce_0006_adjustment_target`: `stock_adjustments.target_on_hand` (+ CHECK).
- Testlar: `tests/integration/test_catalog_import_qa_fixes.py` (10 ta), `tests/unit/test_catalog_import_qa_fixes.py` (25 ta); eski import testlari yangi oqimga moslandi (`PARSING` → `UPLOADED`).
- Worker kodi o'zgardi — dev worker'ni qayta ishga tushirish kerak.

### 10.6 Frontend

- `PARSING` holati: import sahifasi "Fayl o'qilmoqda" progressini ko'rsatadi, holat realtime signal va so'rov bilan yangilanadi; `PARSING` ni bekor qilish mumkin.
- Fonda o'qishda chiqqan sabab (`FAILED`, `error_code` — `TOO_MANY_ROWS`, `TIMEOUT`, `UNSUPPORTED_ENCODING` …) natija kartasida tushunarli matn bilan; yuklashdagi 422 sabablari ro'yxati kengaydi (`TOO_LARGE`, `UNSUPPORTED_ENCODING`, `TIMEOUT`, `FILE_MISSING`).
- Saqlangan shablon qo'llansa, moslash `mapping_id` bilan yuboriladi.
- Tuzatishlar sahifasida import tuzatishi uchun "Maqsad: X (hozir: Y)".
- Yangi matnlar uch tilda: `importStatus.PARSING`, `imports.parsingTitle/Text`, `importIssue.CURRENCY_CONFLICT`, `errors.codes.IMPORT_BUSY`, `stock.targetCurrent`.
- E2E: `"1,000"` miqdorli qator xato; omborchining takroriy importi eski kutilayotgan tuzatishni almashtiradi, tasdiq qoldiqni fayldagi raqamga keltiradi.
