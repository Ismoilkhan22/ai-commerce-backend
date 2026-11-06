# `reporting` schemasi — hisobot read model'lari

> **Holat:** taklif, 2026-10-27. Qarorlar qabul qilingan, chunki founder ishni to'xtatmasdan davom ettirishni topshirgan. **Founder ko'rib chiqishi kutilmoqda.** Qarorlar oxirida. Diagramma: [`reporting.dbml`](reporting.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → maydonlar va nega → manba → misol.
> **Asos:** [19-reporting-metrics.md](../19-reporting-metrics.md) (metrika registri, ruxsatlar, so'rov kontrakti) — bu fayl uning §3 dagi jadvallarini to'liq loyihalaydi va qolgan hisobotlarni qo'shadi. Event'lar — [05](../05-events-and-outbox.md) §8, texnik jadvallar — [jobs.md](jobs.md), tannarx — [commerce_cost_price.md](commerce_cost_price.md).
> **Hajm:** S5-01 — sotuv, operatorlar, ombor qiymati, AI xarajati, foyda, kafolat, Instagram izohlari kayfiyati.

Misollarda **"TechPC"**: ega **Ali**, menejer **Vali**, operator **Dilshod**. Filiallar — **Chilonzor**, **Yunusobod**.

---

## 0. Oddiy so'z bilan

- **Hisobot boshqa domenlarning jadvallarini o'qimaydi.** Har domen "buyurtma topshirildi", "xabar yuborildi" kabi event chiqaradi. Reporting ularni tinglab, o'zining sodda jadvallariga yozadi. Ali "kecha nechta buyurtma?" desa, javob shu jadvallardan keladi va savdo ishiga xalal bermaydi.
- **Shaxsiy ma'lumot yo'q** (19 §3, 4-qoida). Jadvallarda faqat ID, kod, son, summa va vaqt bor. Xaridor ismi, telefoni, xabar va izoh matni hech qachon tushmaydi. Xodim ismi so'rov paytida platform'dan olinadi.
- **"Kecha" — Toshkent vaqti bo'yicha.** Har jadvalda sana ustuni (`*_day`) shop vaqtida yozilgan, shuning uchun 23:30 dagi buyurtma kechaga tushadi (M18 qabul mezoni).
- **Event 3 marta kelsa ham natija bir xil.** Har qator versiya bilan yangilanadi: eski versiya yangisini bosib o'tmaydi.
- **Ma'lumot qachon yangilangan** — `projection_checkpoints`. Har javobda "ma'lumot 09:10 holatiga" deb ko'rsatiladi (BL-066).

---

## 1. So'ralgan hisobotlar qaysi jadvaldan

- **Sotuv** — topshirilgan buyurtmalar va tez sotuvlar, kun, filial, toifa va manba bo'yicha:
  `order_facts` (son, summa, manba, kanal, filial), `order_line_facts` + `quick_sale_facts` (toifa, SKU, dona). Manbalar: AI, sayt, xodim, taklif va `OFFLINE` (tez sotuv).
- **Operator samaradorligi** — javob vaqti, uzatishlar, AI va inson:
  `message_facts` (har javobning kutish vaqti, kim javob berdi), `handoff_facts` (kutish va olish vaqti, sabab), `conversation_facts` (birinchi javob, AI/inson ulushi, konversiya).
- **Ombor qiymati** — `stock_facts` (hozir), `stock_value_daily` (kunlik tarix); sotuv narxida va tannarxda.
- **AI ishlatilishi va xarajati** — `ai_usage_daily` (`platform.ai_usage` dan yig'ma).
- **Foyda** — `order_line_facts` / `quick_sale_facts` dagi tannarx nusxasi ([commerce_cost_price.md](commerce_cost_price.md)), qaytarishlar — `support_case_facts`.
- **Kafolat** — `support_case_facts`. **Instagram izohlari kayfiyati** — `comment_facts`.

Registrga (19 §7) qo'shiladigan metrikalar:
- `sales_by_category_amount`, `sales_by_source_amount` (buyurtma + tez sotuv);
- `staff_reply_time_p50`, `staff_reply_time_p90`, `staff_replies_count`, `handoff_wait_time_p50`, `ai_reply_share` (AI javoblari / barcha javoblar);
- `stock_value_at_price`, `stock_value_at_cost`, `stock_quarantine_units`;
- `gross_profit_amount`, `gross_margin_percent`, `cost_coverage_percent` (tannarxi ma'lum sotuv ulushi), `write_off_value`;
- `returns_refund_amount`, `support_cases_by_sku`;
- `ig_comments_by_sentiment`, `ig_plus_replies_count`, `ig_comment_to_conversation_rate`.

Yangi sifat belgisi: **`PARTIAL_COST_DATA`** — foyda faqat tannarxi ma'lum sotuvlardan, qamrov foizi bilan. Tannarx umuman yo'q bo'lsa — eski `NO_COST_DATA`, raqam aytilmaydi (M18).

---

## 2. Sotuv jadvallari

### `order_facts` — bir buyurtma, bir qator
**Nima uchun:** "kecha nechta buyurtma topshirildi va qancha summa?", "qaysi kanal ko'proq sotadi?".
- **`status`, `source`, `channel`** — holat, kim yaratdi (AI, sayt, xodim, taklif), qaysi kanaldan. Suhbatsiz sayt buyurtmasi — `STOREFRONT`, suhbatsiz xodim buyurtmasi — `OFFLINE`.
- **`branch_id`, `assigned_staff_id`, `lead_id`** — filial, mas'ul operator (operator faqat o'zinikini ko'radi, `row_scope = OWN`), lead.
- **`total_minor`** — jami, so'mda. **`created_day`, `completed_day`, `cancelled_day`** — shop vaqtidagi sanalar.
- **`cancel_reason_code`, `cancel_from_status`** — bekor qilish kodi, matnsiz. **`paid_mark_at`** — "to'landi" belgisi, tekshirilmagan (DEC-100a).
- **`aggregate_version`** — eski event yangisini bosib o'tmaydi.

**Manba:** `commerce.order.*`. **Misol:** #1042, COMPLETED, AI, TELEGRAM, Chilonzor, 9 870 000 so'm, `completed_day = 2026-10-26`.

### `order_line_facts` — topshirilgan buyurtma qatorlari
**Nima uchun:** "qaysi videokarta ko'p sotildi?", "toifalar bo'yicha savdo", foyda.
- **`category_id`** — sotuv paytidagi toifa. Keyin mahsulot boshqa toifaga ko'chirilsa ham, o'tgan oy hisoboti o'zgarmaydi.
- **`qty`, `line_total_minor`** — dona va chegirmali summa.
- **`unit_cost_uzs_minor`, `cost_total_minor`** — tannarx nusxasi. Bo'sh bo'lsa, qator foydaga kirmaydi va qamrov foizi kamayadi.

**Manba:** `commerce.order.completed` `lines[]`.

### `quick_sale_facts` — do'kondagi tez sotuv qatorlari
Xuddi shunday, kanal — `OFFLINE`, **`sold_by_staff_id`** — kim sotdi. **Manba:** `commerce.quick_sale.recorded`.
**Misol:** Chilonzor, RTX 4060 × 1, 4 800 000 so'm, tannarx 3 900 000 → foyda 900 000.

### `support_case_facts` — kafolat murojaatlari
"Ochiq murojaatlar nechta?", "qaysi mahsulot ko'p buziladi?", "qancha pul qaytarildi?". **`refund_amount_minor`** sof sotuv va foydadan ayiriladi ([support.md](support.md) Q7). **Manba:** `support.case.*`.

---

## 3. Mahsulot va ombor

### `product_dim` — mahsulot o'lchami
Nom, toifa va joriy narx: hisobot "MSI RTX 4060" deb yozishi va toifa bo'yicha guruhlashi uchun. **`price_uzs_minor`** — joriy narx so'mda, ombor qiymati sotuv narxida shundan. Nom va toifa event kelganda katalogdan bir marta o'qiladi.

### `sku_cost_dim` — joriy o'rtacha tannarx
**Manba:** yangi `commerce.sku_cost.changed`. Faqat `reporting.margin.read` ruxsati bor metrikalar o'qiydi (ega; menejer — ruxsat bilan, 19 §6).

### `stock_facts` — hozirgi qoldiq
Har filial × SKU: qoldiq, band, ajratilgan, sotuvga mavjud, **tekshiruvda** (karantin) va eng eski band. **Manba:** `commerce.stock.changed` (absolyut qiymatlar), `commerce.reservation.*`.

### `stock_value_daily` — kunlik ombor qiymati
**Nima uchun:** Ali "omborimda qancha pul turibdi va bu oy qanday o'zgardi?" deb so'raydi. Joriy qiymat `stock_facts` dan olinadi, tarix uchun esa har kecha kun oxiridagi holat yoziladi.
- **`value_at_price_minor`** — qoldiq × joriy sotuv narxi (19 §7.4 dagi ta'rif).
- **`value_at_cost_minor`** — qoldiq × o'rtacha tannarx, faqat tannarxi ma'lum mahsulotlar. **`units_without_cost`** qamrovni ko'rsatadi.
- **`quarantine_units`** — tekshiruvdagi donalar, qiymatga kirmaydi.

**Misol:** 2026-10-26, Chilonzor: 140 dona, sotuv narxida 412 mln, tannarxda 351 mln (12 dona tannarxsiz).

---

## 4. Suhbat, operator va voronka

### `conversation_facts` — suhbat bo'yicha yig'ma
19 §3 dagi ustunlar va qo'shimchalar: **`first_reply_staff_id`**, **`inbound_count`**, **`staff_reply_count`**, **`has_order`**, **`has_lead`** (konversiya uchun), **`from_ig_comment`** (izohdan boshlangan suhbat). **`pending_inbound_since`** — ichki maydon: javobsiz birinchi kiruvchi xabar vaqti, javob vaqtini hisoblash uchun.

### `message_facts` — har xabar, matnsiz
**Nima uchun:** operator samaradorligi. "Dilshod xaridorga o'rtacha necha daqiqada javob beradi?", "AI qancha javobni o'zi berdi?".
- **`author`**, **`staff_id`** — kim yozdi: xaridor, AI, operator yoki tizim.
- **`response_seconds`** — javobsiz kiruvchi xabardan shu javobgacha. Salom va xabarnomalarda bo'sh: ular javob hisoblanmaydi.
- **`day`, `hour`** — "qaysi soatlarda yuklama ko'p".

**Saqlash:** 13 oy. Shop kuniga yuzlab xabar oladi — bu jadval uchun kichik hajm.
**Misol:** Jasur 10:02 da yozdi, Dilshod 10:06 da javob berdi → `response_seconds = 240`, `author = STAFF`.

### `handoff_facts` — operatorga uzatish
**Nima uchun:** "operator kerak" bo'lganda xaridor qancha kutdi. **`opened_at → taken_at`** — kutish, **`taken_at → first_staff_reply_at`** — javob. **`reason`** — AI ishonchsiz, shikoyat, kafolat va hokazo. **`in_inbox_hours`** — ish vaqtidan tashqaridagi uzatish kutish vaqtini buzmasin.
**Manba:** yangi `messaging.handoff.opened` va `handed_off` ga `handoff_id` (§6).

### `lead_facts`, `quote_facts`
Voronka: lead → taklif → buyurtma. 19 §3 ustunlari, vaqtlar, byudjet, kim tuzgani. **Manba:** `commerce.lead.*`, `commerce.quote.*`.

---

## 5. AI va izohlar

### `ai_usage_daily` — AI xarajati kunlik
**Nima uchun:** Ali "AI bu oy qancha turdi va nimaga sarflandi?" deb so'raydi. Manba event emas: har soatda rejali ish `platform.ai_usage` dan bugungi va kechagi kunni qayta yig'adi (bitta platform xizmati, 19 §2). `platform.ai_usage` 13 oyda tozalanadi, bu yig'ma esa qoladi.
- **`purpose`** — AI sotuvchi, xulosa, tasnif, izohlar kayfiyati (yangi `COMMENT_CLASSIFY`), hisobot yordamchisi.
- **`cost_micros`** — xom xarajat (USD). Egaga tarif bo'yicha limit foizi ko'rsatiladi (DEC-119), xom dollar faqat `reporting.ai_cost.read` bilan.

### `comment_facts` — Instagram izohlari
Har izoh: post, sana, «+» yoki narx so'rovi, kayfiyat (AI yoki xodim tuzatgani), avtomatik javob natijasi, Direct'da suhbatga aylandimi. Matn va muallif yo'q. Hisobotda "AI bahosi" belgisi bilan ko'rsatiladi (DEC-132). **Manba:** `messaging.ig_comment.*` ([instagram_comments.md](instagram_comments.md)).

---

## 6. Event'larga kerakli qo'shimchalar

05 ni tegishli muallif yangilaydi. Hammasi moslashuvchan (yangi maydon, `schema_version` o'zgarmaydi), yangi event'lar alohida:
- `commerce.order.completed` `lines[]` — `product_id`, `unit_cost_uzs_minor?`;
- `commerce.quick_sale.recorded` `lines[]` — `line_total_minor`, `unit_cost_uzs_minor?`; payload'ga `sold_by`;
- `commerce.stock.changed` — `quarantine_qty`;
- yangi `commerce.sku_cost.changed` — `sku_id`, `avg_unit_cost_uzs_minor`, `cost_version`;
- yangi `messaging.handoff.opened` — `handoff_id`, `conversation_id`, `channel`, `reason`, `requested_by`, `in_inbox_hours`; `messaging.conversation.handed_off` ga `handoff_id`;
- `messaging.message.sent` va `received` — `channel` (`received` da bor, `sent` ga qo'shiladi);
- `support.case.*` — [support.md](support.md) §5; `messaging.ig_comment.*` — [instagram_comments.md](instagram_comments.md) §6.

**Qayta qurish:** `CommerceQueryPort.list_orders_for_backfill`, `MessagingQueryPort.list_conversations_for_backfill` bor (05 §8.9). Qo'shiladi: `list_quick_sales_for_backfill`, `list_stock_for_backfill`, `SupportQueryPort.list_cases_for_backfill`, `MessagingQueryPort.list_comments_for_backfill`. `message_facts` qayta qurilmaydi (xabarlar 12 oyda o'chadi), faqat oldinga yoziladi.

---

## 7. Ishlash va saqlash

- Stage 1 da tayyor kunlik yig'ma jadval yo'q: shop ma'lumoti kichik, metrikalar fakt jadvallaridan so'rov paytida hisoblanadi. So'rov p95 > 1 s bo'lsa, kunlik yig'ma qo'shiladi. Istisno — `stock_value_daily` va `ai_usage_daily`: ular tarixni saqlaydi.
- Saqlash: `message_facts` — 13 oy; qolganlari — shop yopilguncha (`platform.privacy.shop_purge_requested` bilan tozalanadi).
- Xaridor ma'lumotini o'chirish so'rovi reporting'ga ta'sir qilmaydi: bu yerda shaxsiy ma'lumot yo'q (26).

---

## Bog'lanishlar xaritasi

```
commerce.order.* ─────────────▶ order_facts
commerce.order.completed ─────▶ order_line_facts ◀── product_dim (toifa nusxasi)
commerce.quick_sale.recorded ─▶ quick_sale_facts ◀── product_dim
commerce.stock.* / reservation.* ─▶ stock_facts ──(har kecha)──▶ stock_value_daily ◀── product_dim, sku_cost_dim
commerce.sku_cost.changed ────▶ sku_cost_dim
commerce.lead.* / quote.* ────▶ lead_facts, quote_facts
messaging.message.* ──────────▶ message_facts, conversation_facts
messaging.handoff.* ──────────▶ handoff_facts
messaging.ig_comment.* ───────▶ comment_facts
support.case.* ───────────────▶ support_case_facts
platform.ai_usage ──(har soat)─▶ ai_usage_daily
hammasi ──▶ projection_checkpoints (data_as_of)
```

Jadvallar orasida FK yo'q: har biri mustaqil proyeksiya, qayta qurish tartibi muhim emas.

---

## engineering/19 §3 va 07 §4.9 dan farqlar

- Qo'shildi: `message_facts`, `handoff_facts`, `sku_cost_dim`, `stock_value_daily`, `ai_usage_daily`, `comment_facts`.
- Hamma fakt jadvallarida shop vaqtidagi `*_day` ustunlari.
- `quick_sale_facts` — qator darajasida (bir sotuvda bir necha SKU, 05 §8.2).
- `order_line_facts` va `quick_sale_facts` ga tannarx, `stock_facts` ga karantin.
- `ai_cost_amount` endi `ai_usage_daily` dan (19 §7.3 da to'g'ridan platform xizmatidan edi): 13 oydan eski davrlar ham ishlaydi.

---

## Founder ko'rib chiqishi uchun qarorlar

**R1. Hisobot jadvallari qanday to'ldiriladi?**
- **Tanlov:** event'lardan (read model); `ai_usage_daily` va `stock_value_daily` — rejali ish bilan.
- **Nega:** 19 va DEC-126; savdo jadvallariga yuk yo'q, domenlar mustaqil.
- **Kamchilik:** raqamlar bir necha soniya orqada bo'ladi; `data_as_of` ko'rsatiladi.
- **Muqobil:** hisobot to'g'ridan commerce jadvallaridan o'qiydi. Tezroq quriladi, lekin domen chegarasi buziladi.

**R2. Tayyor kunlik yig'malar.**
- **Tanlov:** Stage 1 da yo'q (ikki istisno bilan), so'rov paytida hisoblanadi.
- **Muqobil:** `sales_daily` va boshqalar. Tez, lekin har formula o'zgarishida qayta hisoblash kerak.

**R3. Operator javob vaqti qanday o'lchanadi?**
- **Tanlov:** har xabar bo'yicha `message_facts` (matnsiz), 13 oy.
- **Nega:** p50/p90 ni operator, kun va soat bo'yicha aniq hisoblash mumkin.
- **Muqobil:** faqat birinchi javob vaqti (`conversation_facts`). Kichikroq, lekin suhbat ichidagi sekin javoblar ko'rinmaydi.

**R4. Ombor qiymati.**
- **Tanlov:** ikkalasi: sotuv narxida (ruxsati bor hamma rolga) va tannarxda (faqat `margin` ruxsati bilan), kunlik tarix bilan.
- **Muqobil:** faqat sotuv narxida (19). Tannarx kiritilgach ham "qancha pul turibdi" savoliga javob yo'q.

**R5. Tannarx qisman bo'lganda foyda.**
- **Tanlov:** tannarxi ma'lum sotuvlardan hisoblanadi, `PARTIAL_COST_DATA` va qamrov foizi bilan. Umuman yo'q bo'lsa raqam aytilmaydi.
- **Nega:** BL-063: formula aniq; ega raqamning to'liq emasligini ko'radi.
- **Muqobil:** biror qator tannarxsiz bo'lsa foyda umuman ko'rsatilmaydi. Tizimga o'tish davrida foyda oylab ko'rinmaydi.

**R6. Sotuv toifasi qachon olinadi?**
- **Tanlov:** sotuv paytida nusxa (`category_id`).
- **Muqobil:** joriy toifa bo'yicha. Toifalar qayta tuzilsa, o'tgan oylar raqami o'zgaradi.

**R7. AI xarajati egaga qanday ko'rinadi?**
- **Tanlov:** egaga — limit foizi va so'rovlar soni; xom USD — faqat `reporting.ai_cost.read` (ega).
- **Muqobil:** hamma rolga xom xarajat. Tarif narxi bilan chalkashadi.

**R8. Qaytarishlar sotuvdan ayiriladimi?**
- **Tanlov:** "sof sotuv" va foyda metrikalarida ayiriladi; "topshirilgan buyurtmalar summasi" (19) o'zgarmaydi.
- **Muqobil:** ayirilmaydi. Qaytarish ko'p bo'lsa foyda oshirib ko'rsatiladi.
