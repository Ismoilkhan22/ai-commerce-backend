# Fon ishlari — outbox, event qabul qilish, rejali ishlar (S0-06)

> **Holat:** taklif, 2026-10-26 — qarorlar qabul qilingan (founder topshirig'i bilan), **founder ko'rib chiqishi kutilmoqda**. Qarorlar oxirida. Diagramma: [`jobs.dbml`](jobs.dbml).
> **Kim o'qiydi:** founder va dasturchilar.
> **Batafsil mexanizm:** [05-events-and-outbox.md](../05-events-and-outbox.md), [06-background-jobs.md](../06-background-jobs.md). Bu fayl — bazadagi jadvallar va 2–4-modullarda "fon ishlari bilan keyin" deb qoldirilgan ishlar qanday ulanishi.

---

## 0. Nima uchun kerak — oddiy so'z bilan

Hozirgacha tizim faqat "so'rov keldi → javob berdi" ishlaydi. Lekin ko'p ish hech kim so'rov yubormasa ham bajarilishi kerak:

- buyurtma 24 soat tasdiqlanmasa — operator va menejerga eslatma;
- mahsulot saytdan yashirilsa — sayt keshi darhol tozalanishi;
- Telegram'ga xabar yuborish xato bersa — qayta urinish;
- har kecha ombor daftari qoldiq bilan solishtirilishi.

Asosiy xavf — ishni **yo'qotish**. Masalan, operator buyurtmani tasdiqladi, tizim "xaridorga xabar yubor" deb eslab qolmoqchi, shu lahzada server o'chdi. Buning oldini olish uchun "keyin qilinadigan ish" biznes o'zgarishi bilan **bitta tranzaksiyada** bazaga yoziladi (outbox). Alohida jarayon uni olib, bajaradi.

```
Service:        buyurtma tasdiqlandi + outbox qatori ──COMMIT──▶ (ikkalasi bor yoki ikkalasi yo'q)
outbox_worker:  outbox ──▶ har tinglovchi uchun vazifa (Redis navbati) ──▶ PUBLISHED
task_worker:    tinglovchi o'z tranzaksiyasida: "bajarildi" belgisi + o'z o'zgarishi ──COMMIT
scheduler:      har 15 daqiqa "24 soatdan eski tasdiqlanmagan buyurtma bormi?" ──▶ vazifa yaratadi
```

Uchta jarayon, bitta Docker image: `outbox-worker`, `task-worker`, `scheduler` (06 §2).

---

## 1. `outbox_events` — "keyin qilinadigan ish" yozuvi

**Har domen schemasida bir xil jadval** (platform, catalog, commerce, messaging, storefront; keyin sales_ai, support, reporting). Event biznes o'zgarishi bilan bitta schema ichida yoziladi — schemalar orasida tranzaksiya kerak bo'lmaydi.

- **`event_id`** — event raqami (UUIDv7), takrordan himoya kaliti.
- **`event_type`** — nima bo'ldi: `commerce.order.confirmed`, `catalog.product.hidden`.
- **`shop_id`** — qaysi shop. Tinglovchi shu bilan shop kontekstini o'rnatadi.
- **`aggregate_type`**, **`aggregate_id`**, **`aggregate_version`** — qaysi obyekt va uning versiyasi. Event'lar tartibsiz kelsa, tinglovchi eski versiyani e'tiborsiz qoldiradi (narx 10, keyin 8 kelsa — 10 qoladi).
- **`envelope`** — to'liq event: kim qildi, trace, payload. **Payload'da faqat ID va minimal fakt** — ism, telefon, manzil, chat matni, token YO'Q (05 §3.1). Buni test tekshiradi.
- **`status`** — `PENDING` → `PUBLISHED`; dasturiy xato bo'lsa `DEAD`.
- **`attempts`**, **`next_attempt_at`**, **`last_error`** — Redis ishlamasa: 2, 4, 8 … soniya, ko'pi bilan 5 daqiqa kutib qayta uriniladi. Redis sabab hech qachon `DEAD` bo'lmaydi.
- **`occurred_at`**, **`created_at`**, **`published_at`**.

**Qanday olinadi:** `outbox_worker` 100 tadan `FOR UPDATE SKIP LOCKED` bilan oladi — ikki nusxa bir qatorni olmaydi.
**Saqlash:** `PUBLISHED` — 14 kun (**2-qaror**), `DEAD` — qo'lda hal qilinguncha.
**RLS:** yo'q — faqat tizim jarayonlari o'qiydi, ichida PII yo'q.

**Misol:** Vali RTX 4060 ni saytdan yashirdi. Bitta tranzaksiyada: mahsulot `HIDDEN` + `catalog.outbox_events` ga `catalog.product.hidden` qatori. Bir lahzadan keyin `outbox_worker` uni oldi, `storefront` tinglovchisi sayt keshini tozaladi.

---

## 2. `consumer_receipts` — "bu event'ni bajarganman" belgisi

**Nima uchun kerak:** event bir necha marta kelishi mumkin (at-least-once). Tinglovchi har safar avval shu jadvalga `(consumer, event_id)` yozadi; qator allaqachon bo'lsa — ish qilinmaydi. Belgi va ishning o'zi bitta tranzaksiyada — ikkalasi birga bo'ladi yoki birortasi ham (TC-022).

- **`consumer`** — tinglovchi nomi, o'zgarmas (`storefront.on_product_hidden`). Nom o'zgarsa himoya buziladi.
- **`event_id`**, **`applied_at`**.

**Joyi:** tinglovchining o'z schemasida.
**Saqlash:** 7 kun (07 §5.3).

---

## 3. `platform.dead_letters` — bajarib bo'lmagan ishlar

**Nima uchun kerak:** tinglovchi 8 marta urinib ham ishni bajara olmasa (dasturiy xato), ish yo'qolib ketmasligi kerak. Yozuv shu yerga tushadi, platforma jamoasi ko'radi va xato tuzatilgach **qayta yuboradi** (05 §7).

- **`event_id`**, **`source_schema`**, **`event_type`**, **`consumer`**, **`shop_id`** — nima va kim uchun.
- **`attempts`**, **`last_error`** (PII'siz), **`first_failed_at`**, **`last_failed_at`**.
- **`status`** — ochiq → qayta yuborildi / ataylab qoldirildi; **`resolved_by`**, **`resolved_at`**, **`resolution_note`**.

Qayta yuborish xavfsiz: `consumer_receipts` tufayli bajarilgan qism takrorlanmaydi. Ruxsat — `platform.dead_letter.replay`, audit bilan. Shop xodimlariga ko'rinmaydi.

---

## 4. `platform.job_runs` — rejali ishlar jurnali

**Nima uchun kerak:** "24 soatlik eslatma oxirgi marta qachon ishladi?" degan savolga javob. Grafana monitoringi hali yo'q (deploy bosqichida), shuning uchun platforma paneli va alert shu jadvalni ko'radi (**4-qaror**).

- **`job_name`**, **`status`** (ishlayapti, OK, xato, o'tkazildi — boshqa nusxa ishlatayotgan edi).
- **`started_at`**, **`finished_at`**.
- **`processed`**, **`affected`** — nechta obyekt ko'rildi va nechta vazifa yaratildi / qator o'chirildi.
- **`details`** — faqat sonlar va kodlar (masalan, kechki solishtiruvda nechta farq chiqqani). PII yo'q.
- **`error`**.

**Saqlash:** 30 kun.
**Alert:** ish oxirgi muvaffaqiyatdan beri jadvaldagi oralig'idan 3 baravar ko'p vaqt o'tgan bo'lsa (06 §8).

---

## 5. Rejali ishlar va 2–4-modullardagi "keyin" belgilari qanday ulanadi

Rejali ishlar kodda e'lon qilinadi (`DomainManifest.scheduled_jobs`), bazada jadval emas. Scheduler bitta "leader" nusxada ishlaydi (PostgreSQL advisory lock), har ish qo'shimcha `job:<nom>` qulfi bilan (06 §5.1). Har ish **holat bo'yicha** tanlaydi ("24 soatdan eski va hali eslatma yo'q"), shuning uchun scheduler o'chiq turgan bo'lsa ham keyingi ishga tushishda yetib oladi.

**Kodda qoldirilgan `TODO(S0-06)` lar:**

- **Katalog event'lari** (`catalog.product.published/hidden/archived`, `catalog.price.changed`, `catalog.exchange_rate.updated`) — 2-modul service'larida `write_outbox` chaqiruvi qo'shiladi.
- **Sayt keshi** — `storefront` inline tinglovchisi yuqoridagi event'lar va `commerce.stock.changed` bo'yicha shop `index_version` ni oshiradi. Hozirgi 60 soniyalik kesh tabiiy ravishda darhol yangilanadigan bo'ladi.
- **Kutubxona modeli tasdiqlandi** (`catalog.hardware_spec.updated`) — har shop uchun SKU'larni avtomatik qayta bog'lash vazifasi (2-modulda qo'lda "Qayta tekshirish" tugmasi bilan qolgan edi).
- **Buyurtma eslatmalari** — `order_confirm_reminder` (har 15 daqiqa): `PENDING_CONFIRMATION` 24 soatdan eski → `staff_tasks` (`ORDER_CONFIRM_REMINDER`) + operator va menejerga xabarnoma. Kalit `order_reminder:{order_id}:24h` — ikki marta ishlasa ham bitta vazifa.
- **Band qilish ko'rib chiqish** — `reservation_review`: `review_at` o'tgan band → menejerga `RESERVATION_REVIEW` vazifasi. "Kutamiz" qarorida `review_at` suriladi va yangi oyna — yangi vazifa. 3-moduldagi "Ko'rib chiqish kerak" sahifasi shu vazifalarni ko'rsatadi. Buyurtma o'zgarsa, commerce vazifani yopadi (`resolve_tasks`).
- **Kechki ombor solishtiruvi** — `stock_reconcile` (har kecha 03:30): har shop uchun daftar yig'indisi = qoldiq. Farq chiqsa: shop **egasiga** vazifa (`STOCK_RECONCILE_MISMATCH`, HIGH) va xabar; `job_runs.details` ga son va `alert: true` — platforma panelidagi "Fon ishlari" sahifasida ogohlantirish bo'lib ko'rinadi (QA 5a I7); Sentry alert. Qoldiq avtomatik "tuzatilmaydi" — odam tekshiradi.
- **TD-02, takroriy so'rov kalitlari** — `idempotency_cleanup` (har soat): 24 soatdan eski `platform.idempotency_keys` o'chiriladi.
- **TD-01, partitsiyalar** — `audit_partition_create` (har oy 25-sanasi): `transition_log` va `audit_entries` uchun 12 oy oldinga. Ilova rolida DDL huquqi yo'q, shuning uchun bu `app_migrator` egaligidagi maxsus funksiya orqali (**3-qaror**).
- **Kurs eskirdi** — `exchange_rate_staleness` (har soat): 3 kundan eski kurs → egaga ogohlantirish (bir kunda bir marta).
- **Tozalash** — `outbox_cleanup` (03:00), import qatorlari va xom fayllar (30 kun), `provider_events` (30 kun), eskirgan sayt chati sessiyalari.
- **Rekonsilyatsiya** — `outbox_reconcile` (har 5 daqiqa): Redis ma'lumoti yo'qolgan bo'lsa, bajarilmagan ishlar qayta navbatga qo'yiladi. Navbatda qotib qolgan chiquvchi xabarlar, importlar va xabarnomalar ham shu yerda tiklanadi (06 §6).

**Shoplararo so'rovlar:** "qaysi shoplarda 24 soatdan eski buyurtma bor?" — RLS bunga yo'l qo'ymaydi (bu yaxshi). Shuning uchun `app_migrator` egaligidagi `SECURITY DEFINER` funksiyalar faqat `(shop_id, id)` ro'yxatini qaytaradi. Keyin har shop alohida tranzaksiyada, o'z konteksti bilan ishlanadi (07 §10, 10 §4.6).

---

## 6. Redis'da (bazada emas)

- **arq navbatlari** — Redis db1: `default` (tez ishlar) va `low` (import, eksport).
- **Kesh va so'rovlar chegarasi** — db0; **WebSocket ticket'lar va pub/sub** — db2 (08 §3).

Redis yo'qolsa ham hech narsa yo'qolmaydi: navbat outbox'dan va holat jadvallaridan qayta tiklanadi (06 §6).

---

## engineering/05, 06, 07 dan farqlar

- **Outbox shakli:** 05 §4 dagidek (`event_id` + yo'naltirish ustunlari + `envelope jsonb`), 07 §5.1 dagi ko'p alohida ustunlar o'rniga. `occurred_at` qo'shildi (**1-qaror**).
- **Saqlash muddati:** `PUBLISHED` — 14 kun (07 §5.3 va 06), 05 §4 dagi 7 kun emas (**2-qaror**).
- **`app_scheduler` roli:** 07 §10 da alohida rol bor, pilotda yaratilmaydi — o'rniga `SECURITY DEFINER` funksiyalar (**3-qaror**).
- **Yangi:** `platform.job_runs` (**4-qaror**). `platform.dead_letters` — 05 §7 dagidek, `status`, `resolved_*` qo'shildi.

---

## Founder ko'rib chiqishi uchun qarorlar

Founder 2026-10-26 da ishni to'xtatmasdan davom ettirishni topshirgan. Qarorlar qabul qilingan, o'zgarsa kod moslanadi.

**1. Outbox jadvali 05 §4 shaklida** (`envelope jsonb`).
- Nega: event bir joyda to'liq, versiyalash oson, outbox_worker uni o'zgartirmasdan uzatadi.
- Muqobil: 07 §5.1 dagi alohida ustunlar. Afzallik — SQL bilan filtrlash oson. Kamchilik — envelope maydoni qo'shilsa migratsiya kerak.

**2. Yuborilgan event'lar 14 kun saqlanadi.**
- Nega: 07 §5.3 saqlash muddatlarining yagona manbai deb belgilangan, 06 ham shuni aytadi; 05 dagi 7 kun eski qoldiq.
- Muqobil: 7 kun. Afzallik — kichikroq jadval. Kamchilik — rekonsilyatsiya va tekshiruv oynasi qisqa.

**3. Pilotda alohida `app_scheduler` roli yo'q.**
- Tanlov: shoplararo ro'yxatlar va partitsiya yaratish `app_migrator` egaligidagi `SECURITY DEFINER` funksiyalar orqali; worker'lar `app_runtime` bilan ishlaydi.
- Nega: rollar soni kam, har funksiya faqat kerakli minimumni qaytaradi; RLS hech qayerda o'chirilmaydi.
- Muqobil: alohida `app_scheduler` roli (07 §10). Afzallik — huquq yanada tor. Kamchilik — yana bitta ulanish puli va parol.

**4. `platform.job_runs` jadvali.**
- Nega: monitoring hali yo'q; platforma paneli "ishlar sog'ligi"ni ko'rsatadi, pilotda muammo darhol ko'rinadi.
- Muqobil: faqat metrikalar (Grafana, deploy bilan). Kamchilik — deploygacha ko'rinmaydi.

**5. Kechki solishtiruv qoldiqni avtomatik tuzatmaydi.**
- Tanlov: farq bo'lsa alert va vazifa; odam tekshiradi.
- Nega: farq — xato belgisi, uni avtomatik "yashirish" xavfli (BL-022).
- Muqobil: daftar bo'yicha avtomatik tuzatish. Kamchilik — xato sababi yo'qoladi.
