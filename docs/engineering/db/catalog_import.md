# Katalog importi (CSV/XLSX) — ma'lumotlar lug'ati (S1-06)

> **Holat:** taklif, 2026-10-26 — qarorlar qabul qilingan (founder topshirig'i bilan), **founder ko'rib chiqishi kutilmoqda**. Qarorlar oxirida. Diagramma: [`catalog_import.dbml`](catalog_import.dbml).
> **Kim o'qiydi:** founder va dasturchilar.
> **Muhim:** tasdiqlangan [catalog.dbml](catalog.dbml) (DEC-133) o'zgartirilmaydi — bu jadvallar `catalog` schemasiga **qo'shiladi**; bitta natija jadvali — `commerce` da.
> **Batafsil oqim va qoidalar:** [18-catalog-import.md](../18-catalog-import.md).

Misollarda **"TechPC"**: ega **Ali**, menejer **Vali**, omborchi **Bobur**. Fayl — **"prays_oktyabr.xlsx"**, 1 200 qator.

---

## 0. Asosiy g'oya

Import — pilotdagi birinchi va eng uzun qadam: shopning Excel ro'yxati tizimga to'g'ri tushishi kerak, aks holda sayt va AI noto'g'ri narx ko'rsatadi.

```
Fayl (arzon tekshiruv) ──▶ O'QISH (worker, bir marta, `import_source_rows`) ──▶ ustunlarni moslash ──▶ SINOV (hech narsa yozilmaydi) ──▶ ko'rib chiqish: yangi / yangilanadi / xato / kutubxonaga bog'landi
   ──▶ tasdiq ──▶ yozish (fon vazifasi, 500 qatorlik bo'laklar): mahsulot, SKU, narx
   ──▶ qoldiq qatorlari "kutish zali"ga ──▶ commerce o'zi qo'llaydi (kirim yoki tuzatish) ──▶ tayyor + xatolar CSV
```

**Nega qoldiq alohida bosqichda:** faylda ham mahsulot (katalogniki), ham qoldiq (savdo moduliniki) bor. Katalog savdo jadvaliga tegmaydi — qoldiqning yagona yozuvchisi `commerce` (BL-019, BL-022). Katalog qoldiq qatorlarini "kutish zali"ga yozadi, `commerce` ularni event bo'yicha o'z qoidalari bilan qo'llaydi (18 §2, A varianti).

---

## 1. `import_batches` — bitta import

**Nima uchun kerak:** Ali faylni yukladi — import jarayoni qayerda, nechta qator, nima natija.

- **`file_id`** — asl fayl, yopiq omborda (`IMPORT_FILE`), 30 kun.
- **`original_filename`** — tozalangan nom; **`file_format`** — XLSX yoki CSV; **`sheet_name`** — varaq.
- **`status`** (18 §10):
  ```
  Yuklandi (UPLOADED) ──(moslandi)──▶ MAPPED ──(sinov)──▶ VALIDATING ──▶ VALIDATED
  VALIDATED ──(tasdiq, Idempotency-Key)──▶ Yozilmoqda (COMMITTING) ──(katalog qismi tugadi)──▶ Qoldiq kutilmoqda (STOCK_PENDING)
  STOCK_PENDING ──(commerce qo'lladi)──▶ Tayyor (COMPLETED)
  COMMITTING / STOCK_PENDING ──(xato)──▶ FAILED
  VALIDATED ──(bekor qilindi yoki 24 soat)──▶ EXPIRED
  ```
  Qoldiq ustuni bo'lmasa: `COMMITTING → COMPLETED`.
- **`conflict_policy`** — mavjud SKU bilan nima qilish: faqat yangilarini qo'shish / yangilash (standart) / faqat narxni yangilash (18 §6).
- **`mapping`**, **`mapping_id`**, **`detected_columns`** — qaysi ustun qaysi maydon ("Наименование" → `title`); saqlangan shablondanmi.
- **`default_branch_id`** — faylda filial ustuni bo'lmasa, qoldiq shu filialga.
- **`has_stock_rows`** — miqdor ustuni bor **va** tasdiqlagan xodimda qoldiq huquqi bor. Huquq bo'lmasa qoldiq qismi o'tkazib yuboriladi va ogohlantiriladi (18 §13).
- **`total_rows`**, **`processed_rows`** — progress; worker o'chsa to'xtagan joyidan davom etadi.
- **`stats`** — yaratildi, yangilandi, o'tkazildi, xato, qoldiq qo'llandi / tasdiq kutyapti / xato.
- **`error_code`**, **`heartbeat_at`** — worker tirikligi: 10 daqiqa jim bo'lsa, rekonsilyatsiya qayta qo'yadi (06 §6).
- **`created_by`**, **`committed_by`**, vaqtlar, **`expires_at`** (sinovdan keyin 24 soat).

**Unikal:** shopda bir vaqtda bitta **faol** import (sinov, yozish yoki qoldiq bosqichida). Ikkinchisi — `409 IMPORT_ALREADY_RUNNING`.
**Audit:** har o'zgargan SKU va narx `import_batch_id` bilan.
**RLS:** ha (**3-qaror**).

---

## 2. `import_mappings` — saqlangan moslash shabloni

**Nima uchun kerak:** Ali har oy bir xil formatdagi prays-listni yuklaydi. Birinchi moslash "Asosiy prays-list" nomi bilan saqlanadi, keyingi safar avtomatik taklif qilinadi.

- **`name`**, **`mapping`**, **`conflict_policy`**, **`created_by`**, **`version`**.

**Unikal:** shop ichida nom.
**RLS:** ha.

---

## 3. `import_rows` — har qator natijasi

**Nima uchun kerak:** ko'rib chiqish ekrani va xatolar CSV'si. "45-qator: narx `1.250` — noaniq (1250 yoki 1,25?)".

- **`row_number`** — fayldagi qator raqami.
- **`sku_code_normalized`** — registrsiz, bo'sh joysiz kod: faylda bir xil kod ikki marta bo'lsa, `DUPLICATE_IN_FILE`.
- **`row_values`** — normallashtirilgan qiymatlar: nom, toifa, narx (minor), valyuta, miqdor, filial.
- **`action`** — sinov natijasi: yaratiladi / yangilanadi / o'tkaziladi / xato.
- **`errors`** — `[{maydon, kod}]`: `REQUIRED`, `INVALID_NUMBER`, `INVALID_CHOICE`, `UNKNOWN_BRANCH`, `NO_EXCHANGE_RATE`, `UNSAFE_VALUE`, `PUBLISH_REQUIREMENTS` (18 §11).
- **`spec_match`**, **`spec_id`** — kutubxonaga bog'lash: MPN bo'yicha, model bo'yicha, bir nechta nomzod (foydalanuvchi tanlaydi), topilmadi (18 §9). 2-moduldagi ehtiyotkor qoidalar amal qiladi: "4060" va "4060 Ti", 8GB va 16GB aralashmaydi.
- **`selected`** — foydalanuvchi qatorni yozishdan chiqarib qo'yishi mumkin.
- **`result`**, **`product_id`**, **`sku_id`** — yozish natijasi.
- **`image_results`** — rasm havolalari natijasi (yuklandi / xato). Rasm alohida fon vazifasida, SSRF himoyasi bilan yuklanadi (18 §8).

**Saqlash:** 30 kun.
**RLS:** ha.

---

## 3a. `import_source_rows` — faylning o'qilgan qatorlari (5c QA F1, `catalog_0006`)

**Nima uchun kerak:** fayl endi so'rov ichida o'qilmaydi. Yuklashda faqat arzon tekshiruv (tur, ZIP katalogi, varaq o'lchami `<dimension>`, sharedStrings hajmi, CSV kodlashi); import `PARSING` holatida ochiladi. Worker faylni **bir marta**, alohida thread'da va vaqt chegarasi bilan o'qiydi va qatorlarni shu jadvalga yozadi — sinov bo'laklari faylni qayta ochmaydi.

- **`row_number`** — fayldagi qator raqami; **`cells`** — ustun indeksi bo'yicha asl qiymatlar (JSON ro'yxat).
- Asosiy kalit `(shop_id, batch_id, row_number)`; import bilan birga 30 kun saqlanadi; RLS (FORCE).

`import_batches.status` ga **`PARSING`** qo'shildi: `PARSING ──▶ UPLOADED` (o'qildi) yoki `FAILED` (`error_code` = sabab: `TOO_MANY_ROWS`, `TIMEOUT`, `UNSUPPORTED_ENCODING` …); `PARSING` ni bekor qilish mumkin.

## 4. `import_stock_rows` — qoldiq "kutish zali"

**Nima uchun kerak:** katalog qoldiq jadvaliga yozolmaydi, shuning uchun fayldagi miqdorlarni shu yerga qo'yadi. `commerce` ularni 500 tadan o'qib, o'zi qo'llaydi (18 §7).

- **`sku_id`**, **`branch_id`**, **`quantity`** (fayldagi absolyut qoldiq, ≥ 0), **`row_number`**.

**Unikal:** bir importda bir SKU bir filialda bir marta.
**Saqlash:** 30 kun.
**RLS:** ha.

---

## 5. `commerce.import_stock_results` — qoldiq natijasi

**Nima uchun kerak:** har qoldiq qatori nima bo'lgani: qo'llandi, farq yo'q, tasdiq kutyapti yoki xato ("band qilinganidan kam").

- **`result`** — `APPLIED`, `NO_CHANGE`, `PENDING_APPROVAL`, `ERROR`.
- **`error_code`** — masalan `STOCK_BELOW_COMMITTED`: yangi qoldiq tasdiqlangan buyurtmalardagi banddan kam, qoldiq o'zgarmaydi (TC-IMP-03).
- **`receipt_id`** yoki **`adjustment_id`** — qaysi hujjat bilan.

**Qoldiq qanday o'zgaradi** (**1-qaror**) — faqat 3-moduldagi oddiy hujjatlar orqali:
- **Yangi SKU** (bu filialda qoldiq yo'q) → har (import, filial) uchun bitta **kirim hujjati** (`stock_receipts`, izoh "Import #…"). Kirim tasdiqsiz (DEC-136).
- **Mavjud SKU, farq bor** → **tuzatish** (`stock_adjustments`, tur `ADJUSTMENT`, sabab "Import sinxronlash"):
  - import qilgan ega yoki menejer → darhol qo'llanadi;
  - omborchi → tasdiq kutadi, menejer yoki ega tasdiqlaydi (DEC-134).

**Takror himoyasi:** asosiy kalit `(import, SKU, filial)` — `catalog.import.completed` event'i 3 marta kelsa ham, qoldiq bir marta o'zgaradi (TC-IMP-09).
**RLS:** ha.

**Misol:** Bobur faylni yukladi: 1 100 ta yangi SKU va 100 ta mavjud SKU (40 tasida miqdor farq qiladi). Natija: Chilonzor uchun 1 ta kirim hujjati (1 100 qator) — darhol; 40 ta tuzatish so'rovi — Vali tasdiqlashini kutadi. 2 ta qator `STOCK_BELOW_COMMITTED`.

---

## 6. `commerce` jadvallariga takliflar (fayllarga hali tegilmagan)

- **`commerce.stock_receipts.import_batch_id`** (ixtiyoriy) + unikal `(shop_id, import_batch_id, branch_id)` — bitta importdan bitta filialga bitta kirim.
- **`commerce.stock_adjustments.import_batch_id`** (ixtiyoriy) + unikal `(shop_id, import_batch_id, branch_id, sku_id)`.

Bu ikki ustun qo'shimcha takror himoyasi va "bu hujjat importdan" belgisi.

---

## Bog'lanishlar xaritasi

```
import_mappings ──< import_batches ──< import_rows
                          │
                          └──< import_stock_rows ─ ─ (event, CatalogQueryPort) ─ ─▶ commerce.import_stock_results
                                                                                        ├─ ─ ▶ commerce.stock_receipts
                                                                                        └─ ─ ▶ commerce.stock_adjustments
──<  bir → ko'p (FK)      ─ ─▶  FK'siz (boshqa schema)
```

---

## engineering/18 dan farqlar

- **Qoldiq qo'llash:** 18 §7 dagi maxsus ledger sabablari (`IMPORT_INITIAL`, `IMPORT_SYNC`) va "farq chegaradan katta bo'lsa tasdiq" o'rniga — 3-moduldagi kirim va tuzatish hujjatlari, DEC-134/DEC-136 qoidalari bilan (**1-qaror**). Daftar sabablari o'zgarmaydi: `RECEIPT`, `ADJUSTMENT`.
- **`import_rows`:** `sku_code_normalized`, `spec_match`, `spec_id`, `selected`, `product_id`, `sku_id`, `image_results` qo'shildi; qiymatlar ustuni `row_values` (SQL'dagi band so'z `values` emas).
- **`import_batches`:** `detected_columns`, `default_branch_id`, `has_stock_rows`, `processed_rows`, `heartbeat_at`, `error_code`, `committed_by`, `expires_at` qo'shildi.
- **RLS** — 10 §4 katalog jadvallari uchun ixtiyoriy deydi; import jadvallarida yoqiladi (**3-qaror**).

---

## Founder ko'rib chiqishi uchun qarorlar

Founder 2026-10-26 da ishni to'xtatmasdan davom ettirishni topshirgan. Qarorlar qabul qilingan, o'zgarsa kod moslanadi.

**1. Import qoldig'i oddiy kirim va tuzatish hujjatlari orqali.**
- Tanlov: yangi SKU → kirim (tasdiqsiz), mavjud SKU farqi → tuzatish (omborchida tasdiq bilan, ega/menejerda darhol).
- Nega: DEC-134 (omborchi tuzatishi doim tasdiq bilan, limit sozlamasi yo'q) va DEC-136 (kirim tasdiqsiz) bilan bir xil; 18 dagi "chegara" endi yo'q; hamma qoldiq o'zgarishi bir xil ekranlarda ko'rinadi.
- Muqobil: 18 dagi maxsus `IMPORT_INITIAL`/`IMPORT_SYNC` daftar sabablari, hujjatsiz. Afzallik — kamroq yozuv. Kamchilik — import tuzatishlari tasdiq qoidasidan chetda qoladi.

**2. Omborchi importi — mavjud SKU farqlari tasdiqqa tushadi, yangi SKU kirimi darhol.**
- Nega: kamomadni import orqali "jim yashirib" bo'lmaydi (DEC-134 sababi).
- Muqobil: omborchiga qoldiqli import umuman ruxsat etilmaydi. Kamchilik — pilotda boshlang'ich yuklashni omborchi qila olmaydi.

**3. Import jadvallarida RLS yoqiladi.**
- Nega: import qatorlarida shopning to'liq narx ro'yxati bor; 2-modulda ham hamma shop jadvallarida RLS yoqilgan.
- Muqobil: faqat ilova filtri (10 §4 katalog uchun ruxsat beradi).

**4. Bir vaqtda bitta faol import (sinov, yozish yoki qoldiq bosqichida); tasdiqlanmagan sinov 24 soatda eskiradi.**
- Nega: 18 qoidasi; bir faylning ikki importi bir SKU'ni ikki marta yangilamasin.
- Muqobil: parallel importlar — xavfli, kerak emas.
