# 7-modul. Hisobotlar — 7a qism: tannarx (sotib olish narxi), backend

> **Holat:** backend bitdi (2026-10-27), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** [db/commerce_cost_price.md](../db/commerce_cost_price.md) va [.dbml](../db/commerce_cost_price.dbml), DEC-146 (taklif).
> Foyda hisoboti va event'lar (`reporting`) keyingi qism — bu qismda faqat tannarxni yig'ish va sotuvga nusxalash.

---

## 1. Nima bitdi

Ega kirimda mahsulotning sotib olish narxini kiritadi. Tizim har mahsulot uchun **o'rtacha tortilgan tannarx**ni o'zi yuritadi (shop bo'yicha, so'mda). Sotuv paytida shu o'rtacha sotuv qatoriga nusxalanadi va foyda o'sha paytda **muzlaydi**.

```
Kirim (ega, tannarx bilan) ──▶ yangi o'rtacha = (eski × oldingi qoldiq + yangi narx × kirim soni) / (qoldiq + kirim soni)
        └─ bir tranzaksiyada: kirim, stock_receipt_costs, sku_costs, sku_cost_changes
Tizimgacha bo'lgan qoldiq ──▶ ega "qo'lda qo'yadi" (izoh majburiy) ──▶ sku_costs + tarix (MANUAL_SET)
Buyurtma "Topshirildi" ──▶ order_lines.unit_cost_uzs_minor = joriy o'rtacha (yo'q bo'lsa NULL)
Tez sotuv yozildi     ──▶ quick_sale_lines.unit_cost_uzs_minor = joriy o'rtacha (yo'q bo'lsa NULL)
Kamomad / hisobdan chiqarish tasdiqlandi ──▶ stock_adjustments.unit_cost_uzs_minor
```

Qoidalar:
- Tannarxni faqat **ega** ko'radi va kiritadi (`commerce.cost.view`, `commerce.cost.edit`). Menejer, operator va omborchiga ruxsat berilmagan; ular tannarx yuborsa ham 403.
- Hech bir mavjud javobda (qoldiq, kirim, buyurtma, tez sotuv, daftar) tannarx maydoni yo'q. Tannarx faqat `/costs` endpoint'larida.
- Sotuv, band qilish va tuzatish o'rtachani o'zgartirmaydi. Faqat tannarxli kirim va qo'lda to'g'rilash o'zgartiradi.
- Tannarx noma'lum mahsulot sotilsa, qatorda `NULL` qoladi (sotuv to'xtamaydi).

---

## 2. Bajarilgan bandlar

- [x] Migratsiya `commerce_0009_cost_price` (dev bazaga qo'llandi): `stock_receipt_costs`, `sku_costs`, `sku_cost_changes` — RLS FORCE; `stock_receipt_costs` va `sku_cost_changes` faqat qo'shiladi (UPDATE/DELETE olingan), `sku_costs` da DELETE olingan. `order_lines`, `quick_sale_lines`, `stock_adjustments` ga `unit_cost_uzs_minor` (NULL).
- [x] Kirim qatori: ixtiyoriy `unit_cost_minor` + `cost_currency` (`UZS` yoki `USD`). Dollar shopning joriy kursi bilan so'mga o'giriladi (`CatalogQueryPort.current_rate`, mavjud `to_uzs_minor`); kurs va qiymati `stock_receipt_costs` da saqlanadi.
- [x] O'rtacha hisobi kirim tranzaksiyasida: avval qoldiq qulflanadi, kirimdan oldingi qoldiq (hamma filial + tekshiruvda) o'qiladi, so'ng kirim qo'llanadi. Natija eng yaqin tiyinga (0.5 yuqoriga).
- [x] Ega endpoint'lari (`/api/v1/shop`):
  - `GET /costs` — joriy o'rtachalar (sahifalangan);
  - `GET /costs/{sku_id}` — bitta mahsulot (tannarx noma'lum bo'lsa 404);
  - `GET /costs/{sku_id}/history` — "nega o'zgardi" tarixi;
  - `PUT /costs/{sku_id}` — qo'lda qo'yish: `avg_unit_cost_uzs_minor` + majburiy `reason` (Idempotency-Key bilan).
- [x] Sotuvdagi nusxa: `OrderLifecycleService.complete`, `QuickSaleService.create`, tasdiqlangan kamomad/hisobdan chiqarish.
- [x] Event payload'lariga qo'shildi: `commerce.order.completed` qatorlariga `unit_cost_uzs_minor`; `commerce.quick_sale.recorded` qatorlariga `line_total_minor`, `unit_cost_uzs_minor` va `sold_by`.
- [x] Testlar: `tests/integration/test_commerce_cost.py` (o'rtacha formulasi, dollar, sotuvdagi nusxa va muzlash, noma'lum tannarx, qo'lda qo'yish, ruxsatlar, javoblarda tannarx yo'qligi, RLS).
- **Ataylab keyinga:**
  - `commerce.sku_cost.changed` event'i va `reporting.sku_cost_dim` — hisobot qismida;
  - `LATE_ENTRY` ("tannarxsiz kirimga keyin tannarx qo'shish") va `IMPORT` (katalog importidagi "tannarx" ustuni) — sabab turlari bazada tayyor, endpoint yo'q;
  - frontend ekranlari ("Tannarxni kiritish", kirim formasida tannarx maydoni).

---

## Founder ko'rib chiqishi uchun qarorlar

**Q1. Tannarxni kim ko'radi va kiritadi?**
- **Tanlov:** faqat ega. Spetsifikatsiyada "menejer — ega ruxsat bersa" deyilgan, lekin hozir menejerga ruxsat berilmagan.
- **Nega:** topshiriq shunday. Ruxsatlar rol bo'yicha beriladi, shop darajasida "ruxsat berish" mexanizmi hali yo'q.
- **Muqobil:** `commerce.cost.view/edit` ni menejerga ham berish (bitta qator o'zgaradi).

**Q2. Tannarx kirimda qanday kiritiladi?**
- **Tanlov:** tannarxni faqat kirimni ega o'zi kiritganda yozish mumkin. Omborchi tannarxsiz kirim qiladi; keyin tannarx faqat qo'lda qo'yish (`PUT /costs/{sku_id}`) orqali.
- **Nega:** `LATE_ENTRY` hali qurilmagan; omborchi narx yuborsa, rad etiladi (jim e'tiborsiz qoldirilmaydi).
- **Muqobil:** `LATE_ENTRY` endpoint'i — tannarxsiz kirimga keyin tannarx qo'shish.

**Q3. Dollar kursi eski bo'lsa-chi?**
- **Tanlov:** kurs umuman yo'q bo'lsa kirim rad etiladi (422). Kurs 3 kundan eski bo'lsa ham qabul qilinadi.
- **Nega:** sotuv narxidagi kabi bloklash (BL-018) ega o'z xaridini kiritishiga halal bermasligi kerak. Kurs va sana tannarx qatorida saqlanadi.
- **Muqobil:** eski kursda ham rad etish.

**Q4. O'rtacha qoldig'iga nima kiradi?**
- **Tanlov:** hamma filialdagi qoldiq va tekshiruvdagilar; band qilinganlar qoldiqning ichida (hali sotilmagan).
- **Muqobil:** faqat sotuvga mavjud qoldiq.

**Q5. Bir kirimda bir mahsulot ikki qatorda bo'lsa?**
- **Tanlov:** qatorlar birlashadi, narx miqdor bo'yicha o'rtachalanadi. Ba'zi qatorlarda tannarx bor, ba'zilarida yo'q yoki valyutalar har xil bo'lsa — 422.
- **Nega:** `stock_receipt_costs` da bir kirim × bir mahsulot = bitta qator.

**Q6. Kamomad tannarxi.**
- **Tanlov:** nusxa faqat kamaytiruvchi tuzatishda (kamomad `ADJUSTMENT` −, `WRITE_OFF`) va tasdiqlash paytida olinadi. Karantinga o'tkazish va qayta omborga qaytarish yo'qotish emas, shuning uchun tannarx yozilmaydi.

---

# 7c qism: hisobot read model'lari va hisobot API, backend

> **Holat:** 2026-10-27, backend tayyor, commit qilinmagan, founder ko'rib chiqishi kutilmoqda. Spetsifikatsiya: [reporting.md](../db/reporting.md), [19](../19-reporting-metrics.md), DEC-146.

## 7c.1. Nima bitdi

- **`reporting` schemasi** (`reporting_0002`): sotuv (`order_facts`, `order_line_facts`, `quick_sale_facts`), kafolat (`support_case_facts`), ombor (`product_dim`, `stock_facts`, `stock_value_daily`), suhbat (`conversation_facts`, `message_facts`, `handoff_facts`), `ai_usage_daily`, `projection_checkpoints`, `consumer_receipts`. Hamma shop jadvalida RLS (ENABLE + FORCE). Shaxsiy ma'lumot yo'q.
- **Proyeksiyalar:** 4 ta tinglovchi (`reporting.sales_facts`, `stock_facts`, `support_facts`, `conversation_facts`). Takror event natijani o'zgartirmaydi: katta versiya g'olib, qator to'plamlari o'chirilib qayta yoziladi, xabar sanagichlari faqat yangi qator qo'shilganda oshadi.
- **Soatlik ishlar:** `reporting_stock_value` (ombor qiymati, sotuv narxida va tannarxda), `reporting_ai_usage` (`platform.ai_usage` dan kunlik yig'ma).
- **Qayta qurish:** `make reporting-backfill` (yoki `python -m app.workers.reporting_backfill --shop <id>`). Mavjud jadvallardan sintetik event'lar yasaydi va jonli proyeksiya kodidan o'tkazadi, shuning uchun natija bir xil. Dev bazada ishga tushirilgan (12 shop).
- **API** (`/api/v1/shop/reporting/...`, ruxsat `reporting.view`: ega va menejer, tannarx/foyda/AI xarajati — faqat ega (`reporting.margin.read`, QA tuzatishlari F1); parametrlar `from`, `to`, `branch_id`, `source`):
  - `GET /sales/summary` (filial va manba bo'yicha taqsimot bilan), `/sales/daily`, `/sales/top-products`, `/sales/by-category`;
  - `GET /profit` (`PARTIAL_COST_DATA` va qamrov foizi bilan);
  - `GET /stock-value`, `/operators`, `/ai-usage`, `/warranty`;
  - `GET /export?report=<nom>` (CSV, shaxsiy ma'lumotsiz, formula belgisidan himoyalangan).
- **Qoidalar:** kun Toshkent vaqti bo'yicha (23:30 dagi buyurtma o'sha kunga tushadi); foyda buyurtma topshirilgan paytdagi tannarx nusxasidan; tannarxi ma'lum qatorlar bo'yicha foyda va qamrov foizi, tannarx umuman yo'q bo'lsa foyda raqami aytilmaydi (`null`, `NO_COST_DATA`).
- **Mavjud event'larga kichik qo'shimcha:** `commerce.stock.changed` ga `quarantine_qty`, `support.case.*` ga `refund_amount_minor`. Eski o'quvchilarga ta'sir qilmaydi.
- **Port:** `CatalogQueryPort.sku_report_dims` (nom, toifa, narx) va yangi `ReportingSourcePort` (qayta qurish manbasi va tannarx).

## 7c.2. Keyinga qoldirilgan

- Lead, taklif (`lead_facts`, `quote_facts`) va Instagram izohlari (`comment_facts`) jadvallari va hisobotlari.
- `commerce.sku_cost.changed` event'i va `sku_cost_dim`: ombor qiymati tannarxi hozir soatlik ishda to'g'ridan tannarx port'idan olinadi.
- `handoff_facts` da `first_staff_reply_at`, ish vaqtidan tashqari uzatish (`in_inbox_hours`), `conversation_facts` da konversiya belgilari.
- Qaytarishlarni sof sotuv va foydadan ayirish (R8): hozir faqat alohida `refunds_amount_minor` ko'rsatiladi.
- Operator statistikasi filial bo'yicha emas (xabarlarda filial yo'q).
- Kunlik qoldiq surati faqat soatlik ish ishlagan kunlar uchun bor; o'tgan tarix manbadan tiklanmaydi.
- Javob vaqti hisobi bir suhbatdagi event'lar ketma-ket qayta ishlanishiga tayanadi; parallel worker'larda kamdan-kam noaniqlik bo'lishi mumkin.
- Shop vaqt zonasi `platform.shops.timezone` dan olinadi (standart `Asia/Tashkent`).

## Founder ko'rib chiqishi uchun qarorlar

**H1. Foyda va AI xarajatiga kim ruxsatli?**
- **Tanlov (QA7 dan keyin):** faqat ega. `reporting.view` — ega va menejer (tannarxsiz maydonlar), `reporting.margin.read` — faqat ega (tannarx, foyda, AI xarajati pul qiymatida).
- **Nega:** DEC-146: tannarxni faqat ega ko'radi. Menejer tannarxni ko'rmasligi kerak.
- **Muqobil:** ilgarigi tanlov — bitta `reporting.view`, menejer ham ko'radi (QA topdi: bu DEC-146 ga zid, shuning uchun almashtirildi). Ega xohlasa menejerga `reporting.margin.read` berish keyin qo'shilishi mumkin (hozir rol bo'yicha, shop bo'yicha emas).

**H2. Qayta qurish boshqa domen jadvallarini to'g'ridan o'qiydi.**
- **Tanlov:** `app/db/reporting_sources.py` (composition root) SQL bilan o'qiydi, domen kodini import qilmaydi.
- **Nega:** Query Port backfill metodlari hali yo'q; bir martalik vosita.
- **Muqobil:** har domen o'z port metodini yozadi (to'g'riroq, ko'proq ish).

**H3. Qaytarishlar foydadan ayirilmaydi.**
- **Tanlov:** alohida raqam sifatida ko'rsatiladi.
- **Nega:** qaytarilgan tovar karantinga tushadi, tannarxini qaytarish qoidasi hali belgilanmagan.
- **Muqobil:** R8 dagidek sof sotuvdan ayirish.

**H4. Stage 1 doirasi.**
- **Tanlov:** lead, taklif va Instagram izohlari hisobotlari keyinga qoldirildi.
- **Muqobil:** ularni ham shu bosqichda qurish (taxminan yana bir modul hajmi).

**H5. Operator xodimi identifikatori.**
- **Tanlov:** xabar va uzatishda xodim event aktorining `principal` ID'si; ism so'rov paytida platform'dan olinadi.
- **Muqobil:** `membership` ID. Xodim bir necha shopda ishlasa ham to'g'ri, lekin event'larga membership qo'shish kerak.

**H6. Birinchi tannarxli kirim va tannarxsiz eski qoldiq.**
- **Hozirgi xatti-harakat:** SKU'da tannarxsiz qoldiq bor (`sku_costs` qatori yo'q), keyin birinchi tannarxli kirim keladi. O'rtacha = shu kirim narxi, "qoldiq" = eski qoldiq + yangi kirim. Ya'ni eski tannarxsiz donalar ham kirim narxi bilan hisoblanadi.
- **Nega shunday qoldirildi:** "noma'lum" donani 0 so'm deb hisoblash foydani oshirib yuboradi, kirim narxi esa eng yaqin real taxmin. Ega xohlasa `MANUAL_SET` bilan to'g'rilaydi (tarixda izoh bilan qoladi).
- **DEC-146 bilan farqi:** DEC-146 "kiritilmasa o'sha mahsulot sotuvi foydaga kirmaydi" deydi. Bu faqat SKU'ga umuman tannarx kiritilmagan paytga tegishli. Birinchi tannarxli kirimdan keyin hisobot eski donalarni ham tannarxli deb ko'rsatadi.
- **Muqobil:** eski tannarxsiz donalarni alohida "noma'lum" qoldirish (partiya/qatlam hisobi kerak, murakkabroq). Founder qarori kutilmoqda.

---

## QA tuzatishlari

QA7 sinovidan keyingi tuzatishlar (commit qilinmagan):

- **F1 (yuqori) — menejer tannarx va foydani ko'rmasin:**
  - ruxsat ikkiga bo'lindi: `reporting.view` (ega, menejer), `reporting.margin.read` (faqat ega);
  - `/profit` va `/export?report=profit` menejerga 403;
  - `/stock-value`: `value_at_cost_minor` (jami, filial, kunlik qator) menejerga `null`; CSV da tannarx ustuni yo'q;
  - `/ai-usage`: `cost_micros` (jami, kun, maqsad) menejerga `null`; CSV da ustun yo'q. Chaqiruv va token sonlari ochiq;
  - frontend: "Foyda" tabi va tannarx ustunlari `usePermission("reporting.margin.read")` bo'lmasa yashiriladi;
  - H1 qarori "faqat ega" ga o'zgartirildi, engineering/10 yangilandi.
- **F2 — eski event:** `lines` kaliti yo'q (legacy) `commerce.order.completed` mavjud qator faktlarini o'chirmaydi. `lines: []` esa hamon "qator yo'q" degani.
- **F3 — kafolat qaytarish summasi:**
  - summa sotilgan qator summasidan (son x dona narxi, sotuv nusxasidan) oshsa 422 `refund_amount_minor` / `max_value`;
  - sotuv qatori noma'lum (tizimgacha sotuv, EXTERNAL) bo'lsa summani faqat menejer/ega kiritadi (sanity chegara 10^13 saqlanadi);
  - kelajakdagi `sold_at` — 422 `sold_at` / `in_future`.
- **F4 — validator:** garantiya, 100% kafolat, umrbod/lifetime/пожизненная, "30 kunlik qaytarish kafolati", "кафолат беряпмиз", "заказ создан", "buyurtma yaratildi/berildi", "buyurtmani rasmiylashtirdim", "to'lovni qabul qildik", "деньги получили", "payment received", "дисконт", "promo kod" endi bloklanadi. SKU dagi "kafolat muddati 12 oy" ruxsat.
- **F5 — PRICE_MISMATCH:** telefon raqami (+998, mahalliy), mAh/soat/GB/TB/MHz/W/Hz birligi va "Model 12345" / "Indeks 100000" yorliqli sonlar pul emas. Valyuta yonidagi o'ylab topilgan summa hamon ushlanadi.
- **F6 — redaction:**
  - 7+ raqamli son faqat telefonga o'xshasa yashiriladi: `+`/davlat kodi, mahalliy 9 raqamli format yoki "tel/raqam" konteksti;
  - `3500000 so'm`, `1 200 000 - 3 500 000 so'm` yashirilmaydi;
  - o'nlik (`lat 41.3110 lon 69.2405`) va daraja-minut-soniya (`41°18'39.9"N`) koordinatalar `LOCATION` bo'ladi.
- **F7 — Instagram webhook:**
  - juda katta `created_time` (va DM `timestamp`) — 200, hodisa e'tiborsiz;
  - matnda NUL bo'lsa faqat shu izoh tushadi, butun yetkazib berish 200;
  - izoh matni 2200 belgigacha qisqartiriladi;
  - kayfiyat ishonchi 0..1 oralig'iga qisiladi, NaN/Infinity e'tiborsiz; chegara (0.70) yaxlitlanmagan qiymat bilan solishtiriladi.
- **F8:**
  - dona tannarxi eng ko'pi 10^12 minor (kirim va qo'lda kiritish);
  - tannarx umuman yo'q bo'lsa `/profit` da `cost_minor: null` (0 emas);
  - birinchi tannarxli kirim xatti-harakati H6 sifatida hujjatlandi.

**Qayta ishga tushirish:** backend serverini qayta ishga tushirish kerak (yangi ruxsat `reporting.margin.read` ro'yxatdan o'tadi). Migratsiya yo'q.
